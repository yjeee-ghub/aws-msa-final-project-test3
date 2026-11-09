"""임시 가짜 AWS CLI로 실패 처리와 복원 대상 제한을 검사합니다. 실제 AWS 호출은 없습니다."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FAKE = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ['MOCK_AWS_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\n')
action = ' '.join(args[:2])
if action == os.environ.get('MOCK_AWS_FAIL'):
    print('AccessDenied: mocked query failure', file=sys.stderr)
    sys.exit(1)
def value(option):
    return args[args.index(option) + 1] if option in args else ''
source = {'DBInstanceIdentifier':'sol-test3-ordermsa-db', 'DBInstanceClass':'db.t4g.micro',
          'DBInstanceArn':'arn:mock:db', 'DBSubnetGroup':{'DBSubnetGroupName':'private-db'},
          'VpcSecurityGroups':[{'VpcSecurityGroupId':'sg-original'}],
          'Endpoint':{'Address':'private.example.invalid'}}
if '--query' in args:
    result = []
elif action == 'sts get-caller-identity':
    result = {'Account':'683668078297'}
elif action == 'ec2 describe-vpcs':
    result = {'Vpcs':[{'VpcId':'vpc-mock','Tags':[{'Key':'Project','Value':'sol-test3'}]}] if os.environ.get('MOCK_VPC') else []}
elif action == 'rds describe-db-instances':
    result = {'DBInstances':[source]}
    if value('--db-instance-identifier').startswith('sol-test3-restore-'):
        result = {'DBInstances':[dict(source, DBInstanceIdentifier=value('--db-instance-identifier'))]}
    if os.environ.get('MOCK_DUPLICATE'):
        result['DBInstances'].append(dict(source, DBInstanceIdentifier='sol-test3-restore-test'))
elif action == 'rds describe-db-snapshots':
    result = {'DBSnapshots':[{'DBInstanceIdentifier':'sol-test3-ordermsa-db','Status':'available', 'DBSnapshotArn':'arn:mock:snapshot'}]}
elif action == 'rds list-tags-for-resource':
    result = {'TagList':[{'Key':'Purpose','Value':'RestoreRehearsal'}]}
else:
    result = {}
print(json.dumps(result))
'''

@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7이 필요합니다.')
class OpsTests(unittest.TestCase):
    def run_script(self, script, *args, **variables):
        with tempfile.TemporaryDirectory() as tmp:
            # Windows에서는 실행 가능한 CMD 래퍼로 같은 가짜 AWS CLI를 호출합니다.
            if os.name == 'nt':
                fake_script = Path(tmp, 'fake_aws.py')
                fake_script.write_text(FAKE, encoding='utf-8')
                Path(tmp, 'aws.cmd').write_text(
                    '@echo off\n"' + sys.executable + '" "' + str(fake_script) + '" %*\n', encoding='utf-8')
            else:
                mock = Path(tmp, 'aws')
                mock.write_text('#!' + sys.executable + '\n' + FAKE, encoding='utf-8')
                mock.chmod(0o755)
            log = Path(tmp, 'calls.jsonl')
            environment = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'],
                               MOCK_AWS_LOG=str(log), **variables)
            command = [shutil.which('pwsh'), '-NoLogo', '-NoProfile', '-File',
                       str(ROOT / 'scripts/ops' / script), *args]
            result = subprocess.run(command, env=environment, text=True, encoding='utf-8', capture_output=True, timeout=90)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_empty_is_success_and_query_failure_is_failure(self):
        result, calls = self.run_script('Get-ProjectResidue.ps1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('해당 자원 없음', result.stdout)
        self.assertIn('의도적 보관', result.stdout)
        self.assertTrue(all(c[1].startswith(('get-', 'list-', 'describe-')) for c in calls))
        result, _ = self.run_script('Get-ProjectResidue.ps1', MOCK_AWS_FAIL='rds describe-db-instances')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('조회 실패', result.stdout)
        self.assertIn('AccessDenied', result.stdout)

    def test_vpc_children_are_queried_even_without_project_tags(self):
        result, calls = self.run_script('Get-ProjectResidue.ps1', MOCK_VPC='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        eni = next(c for c in calls if c[1] == 'describe-network-interfaces')
        nat = next(c for c in calls if c[1] == 'describe-nat-gateways')
        self.assertIn('Name=vpc-id,Values=vpc-mock', eni)
        self.assertIn('--filters', eni)
        self.assertIn('--filter', nat)

    def test_restore_creates_only_separate_private_database(self):
        result, calls = self.run_script('Invoke-RdsRestoreLab.ps1', '-Mode', 'Restore',
                                       '-SnapshotId', 'sol-test3-rehearsal-test', '-RestoreDbId', 'sol-test3-restore-test', '-Confirm:$false')
        self.assertEqual(result.returncode, 0, result.stderr)
        restores = [c for c in calls if c[1] == 'restore-db-instance-from-db-snapshot']
        self.assertEqual(len(restores), 1)
        self.assertIn('--no-publicly-accessible', restores[0])
        self.assertIn('--no-multi-az', restores[0])
        self.assertEqual(restores[0][restores[0].index('--db-instance-identifier') + 1], 'sol-test3-restore-test')
        self.assertFalse(any(c[1] == 'delete-db-instance' for c in calls))

    def test_restore_does_not_treat_access_denied_or_existing_db_as_absent(self):
        for variables in ({'MOCK_AWS_FAIL':'rds describe-db-instances'}, {'MOCK_DUPLICATE':'1'}):
            result, calls = self.run_script('Invoke-RdsRestoreLab.ps1', '-Mode', 'Restore',
                                           '-SnapshotId', 'sol-test3-rehearsal-test', '-RestoreDbId', 'sol-test3-restore-test', '-Confirm:$false', **variables)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(any(c[1] == 'restore-db-instance-from-db-snapshot' for c in calls))

    def test_whatif_does_not_create_snapshot(self):
        result, calls = self.run_script('Invoke-RdsRestoreLab.ps1', '-Mode', 'Snapshot',
                                       '-SnapshotId', 'sol-test3-rehearsal-test', '-WhatIf')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(c[1] == 'create-db-snapshot' for c in calls))
