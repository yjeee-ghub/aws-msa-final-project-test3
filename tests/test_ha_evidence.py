"""Offline tests for HA path validation and isolated frontend demo stages."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/ops'))
from verify_lab import verify_ha_network

spec = importlib.util.spec_from_file_location('demo_frontend', ROOT / 'scripts/demo/prepare_frontend.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class HaTests(unittest.TestCase):
    def setUp(self):
        self.subnets = [{'SubnetId': 'pub-' + az, 'AvailabilityZone': az} for az in ('a', 'c')]
        self.subnets += [{'SubnetId': 'app-' + az, 'AvailabilityZone': az,
                          'Tags': [{'Key': 'kubernetes.io/role/internal-elb', 'Value': '1'}]} for az in ('a', 'c')]
        self.nats = [{'NatGatewayId': 'nat-' + az, 'SubnetId': 'pub-' + az, 'State': 'available'} for az in ('a', 'c')]
        self.tables = [{'RouteTableId': 'rt-' + az, 'Associations': [{'SubnetId': 'app-' + az}],
                        'Routes': [{'DestinationCidrBlock': '0.0.0.0/0', 'NatGatewayId': 'nat-' + az, 'State': 'active'}]} for az in ('a', 'c')]
        self.db = {'MultiAZ': True, 'AvailabilityZone': 'a', 'SecondaryAvailabilityZone': 'c'}

    def verify(self):
        return verify_ha_network(self.subnets, self.nats, self.tables, self.db)

    def test_az_local_routes_and_standby_pass(self):
        self.assertEqual(len(self.verify()['natPaths']), 2)

    def test_secondary_az_can_be_corroborated_by_two_scoped_rds_interfaces(self):
        self.db.pop('SecondaryAvailabilityZone')
        self.db.update(
            DBSubnetGroup={'VpcId': 'vpc-db', 'Subnets': [
                {'SubnetIdentifier': 'db-' + az, 'SubnetAvailabilityZone': {'Name': az}} for az in ('a', 'c')]},
            VpcSecurityGroups=[{'VpcSecurityGroupId': 'sg-db'}],
        )
        interfaces = [
            {'VpcId': 'vpc-db', 'SubnetId': 'db-' + az, 'AvailabilityZone': az, 'Groups': [{'GroupId': 'sg-db'}],
             'RequesterManaged': True, 'RequesterId': 'amazon-rds', 'Status': 'in-use',
             'Description': 'RDSNetworkInterface'} for az in ('a', 'c')
        ]
        result = verify_ha_network(self.subnets, self.nats, self.tables, self.db, rds_interfaces=interfaces)
        self.assertEqual(result['standbyAZ'], 'c')
        self.assertEqual(result['standbyAZSource'], 'rds-network-interfaces')
        interfaces[1]['Groups'] = [{'GroupId': 'sg-unrelated'}]
        with self.assertRaisesRegex(ValueError, 'standby AZ not ready'):
            verify_ha_network(self.subnets, self.nats, self.tables, self.db, rds_interfaces=interfaces)

    def test_single_nat_or_cross_az_route_fails(self):
        original = copy.deepcopy(self.nats)
        self.nats.pop()
        with self.assertRaises(ValueError): self.verify()
        self.nats = original
        self.tables[1]['Routes'][0]['NatGatewayId'] = 'nat-a'
        with self.assertRaises(ValueError): self.verify()

    def test_missing_route_blackhole_or_standby_fails(self):
        self.tables[0]['Routes'][0]['State'] = 'blackhole'
        with self.assertRaises(ValueError): self.verify()
        self.tables[0]['Routes'][0]['State'] = 'active'
        self.db['MultiAZ'] = False
        with self.assertRaises(ValueError): self.verify()
        self.db['MultiAZ'] = True
        self.db['SecondaryAvailabilityZone'] = 'a'
        with self.assertRaises(ValueError): self.verify()

    def test_cross_az_requires_separately_confirmed_matching_bypass(self):
        self.tables[0]['Routes'][0]['NatGatewayId'] = 'nat-c'
        result = verify_ha_network(self.subnets, self.nats, self.tables, self.db,
                                   verified_bypasses={'rt-a': 'nat-c'})
        self.assertEqual(result['natPaths'][0]['mode'], 'verified-bypass')
        with self.assertRaises(ValueError):
            verify_ha_network(self.subnets, self.nats, self.tables, self.db, verified_bypasses={'rt-a': 'nat-a'})


@unittest.skipUnless(shutil.which('node'), 'Node required for browser-navigation contract rehearsal')
class DemoTests(unittest.TestCase):
    def test_baseline_fault_and_final_navigation_and_preserved_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for p in demo.FILES:
                source = ROOT / p
                if source.exists():
                    (root / p).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, root / p)
            original = (root / demo.SRC / 'assets/app.js').read_bytes()
            for stage, expected in [('baseline', 0), ('fault', 1), ('final', 0)]:
                demo.prepare(stage, root)
                env = dict(os.environ, FRONTEND_SOURCE=str(root / demo.SRC / 'assets/app.js'))
                result = subprocess.run(['node', '--test', str(ROOT / 'scripts/demo/templates/product-navigation.test.cjs')],
                                        env=env, capture_output=True, timeout=30)
                self.assertEqual(result.returncode == 0, expected == 0, result.stdout)
            self.assertEqual((root / demo.SRC / 'assets/app.js').read_bytes(), original)
            self.assertEqual((root / demo.SRC / 'index.html').read_bytes(), (ROOT / demo.SRC / 'index.html').read_bytes())
            self.assertTrue((root / demo.REGRESSION).exists())

    def test_user_edits_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for p in demo.FILES:
                if (ROOT / p).exists():
                    (root / p).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / p, root / p)
            demo.prepare('baseline', root)
            index = root / demo.SRC / 'index.html'
            index.write_text('user changes', encoding='utf-8')
            with self.assertRaises(ValueError): demo.prepare('fault', root)
            self.assertEqual(index.read_text(encoding='utf-8'), 'user changes')


@unittest.skipUnless(shutil.which('powershell') or shutil.which('pwsh'), 'PowerShell required')
class ObserverTests(unittest.TestCase):
    def test_real_observer_with_fake_commands_writes_selected_fields(self):
        shell = shutil.which('powershell') or shutil.which('pwsh')
        for mode in ('Deployment', 'HA'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                    str(ROOT / 'tests/fixtures/evidence-observer-fake.ps1'),
                    '-Observer', str(ROOT / 'scripts/demo/Watch-LabEvidence.ps1'),
                    '-OutputDirectory', directory, '-Mode', mode], capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                reports = list(Path(directory).glob('*.jsonl'))
                self.assertEqual(len(reports), 1)
                data = json.loads(reports[0].read_text(encoding='utf-8').strip())
                self.assertEqual(data['query'], 'OK', result.stdout)
                if mode == 'Deployment':
                    self.assertTrue(data['pods'][0]['Ready'])
                    self.assertEqual(data['deployment']['available'], 2)
                else:
                    self.assertEqual(len(data['nats']), 2)
                    self.assertTrue(data['rds']['MultiAZ'])


if __name__ == '__main__':
    unittest.main()
