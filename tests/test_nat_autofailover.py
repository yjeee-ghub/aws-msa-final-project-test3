"""NAT policy, duplicate events, AWS ownership and teardown boundaries. No AWS."""
import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


decision = load('nat_decision', ROOT / 'lambda/nat_failover/decision.py')
with patch.dict(sys.modules, {'decision': decision, 'boto3': SimpleNamespace(),
                            'botocore.config': SimpleNamespace(Config=lambda **kw: None)}):
    controller = load('nat_controller', ROOT / 'lambda/nat_failover/controller.py')
sys.path.insert(0, str(ROOT / 'scripts/ops'))
import nat_failover as ops
from lab_common import CONFIG


def sample(ok=True, ip='1.1.1.1'):
    return {'valid': True, 'ok': ok, 'ip': ip if ok else None}


POLICY = {'primary': {'id': 'na', 'ip': '1.1.1.1'}, 'alternate': {'id': 'nc', 'ip': '2.2.2.2'},
          'failure_threshold': 2, 'recovery_threshold': 3, 'minimum_bypass_seconds': 120}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.normal = {'app': sample(), 'primary': sample(), 'alternate': sample(ip='2.2.2.2')}
        self.failed = {**self.normal, 'app': sample(False), 'primary': sample(False)}

    def test_two_failures_then_three_native_successes_and_hold(self):
        s, target, _ = decision.decide({}, self.failed, 'na', POLICY, 1000)
        self.assertIsNone(target)
        s, target, reason = decision.decide(s, self.failed, 'na', POLICY, 1060)
        self.assertEqual((target, reason), ('nc', 'FAILOVER'))
        recovered = {**self.normal, 'app': sample(ip='2.2.2.2')}
        s = {'last_switch': 1060}
        for now in (1120, 1180):
            s, target, _ = decision.decide(s, recovered, 'nc', POLICY, now)
            self.assertIsNone(target)
        _, target, reason = decision.decide(s, recovered, 'nc', POLICY, 1240)
        self.assertEqual((target, reason), ('na', 'FAILBACK'))

    def test_transient_and_unknown_reset_counters(self):
        s, _, _ = decision.decide({'failures': 1}, self.normal, 'na', POLICY, 1000)
        self.assertEqual(s['failures'], 0)
        for broken in ({'valid': False, 'ok': False, 'ip': None}, {'valid': True, 'ok': 'false', 'ip': None}, sample(ip='garbage')):
            x = {**self.failed, 'primary': broken}
            s, target, reason = decision.decide({'failures': 9, 'recoveries': 9}, x, 'na', POLICY, 1000)
            self.assertEqual((s['failures'], s['recoveries'], target, reason), (0, 0, None, 'CONTROL_UNKNOWN'))

    def test_unhealthy_peer_or_only_app_failure_never_switches(self):
        for x in ({**self.failed, 'alternate': sample(False)}, {**self.normal, 'app': sample(False)}):
            _, target, _ = decision.decide({'failures': 1}, x, 'na', POLICY, 1000)
            self.assertIsNone(target)

    def test_bypass_egress_does_not_prove_native_recovery(self):
        x = {**self.failed, 'app': sample(ip='2.2.2.2')}
        s, target, _ = decision.decide({'last_switch': 0, 'recoveries': 8}, x, 'nc', POLICY, 1000)
        self.assertEqual(s['recoveries'], 0); self.assertIsNone(target)

    def test_hold_down_and_wrong_native_ip(self):
        x = {**self.normal, 'app': sample(ip='2.2.2.2')}
        _, target, _ = decision.decide({'last_switch': 990, 'recoveries': 8}, x, 'nc', POLICY, 1000)
        self.assertIsNone(target)
        x['primary'] = sample(ip='2.2.2.2')
        _, target, reason = decision.decide({'recoveries': 8}, x, 'nc', POLICY, 1000)
        self.assertEqual((target, reason), (None, 'PROBE_PATH_MISMATCH'))

    def test_missing_or_unexpected_route_and_app_ip_fail_closed(self):
        for route in (None, 'third-nat'):
            _, target, reason = decision.decide({'failures': 99}, self.failed, route, POLICY, 1000)
            self.assertEqual((target, reason), (None, 'UNEXPECTED_ROUTE'))
        _, target, reason = decision.decide({}, {**self.normal, 'app': sample(ip='3.3.3.3')}, 'na', POLICY, 1000)
        self.assertEqual((target, reason), (None, 'APP_PATH_MISMATCH'))

    def test_native_recovery_can_rescue_app_when_bypass_also_fails(self):
        x = {'app': sample(False), 'primary': sample(), 'alternate': sample(False)}
        _, target, reason = decision.decide({'recoveries': 2, 'last_switch': 0}, x, 'nc', POLICY, 1000)
        self.assertEqual((target, reason), ('na', 'FAILBACK'))


def config():
    return {'account': '123456789012', 'region': 'ap-northeast-2', 'vpc': 'vpc-owned',
            'rule_arn': 'arn:aws:events:ap-northeast-2:123456789012:rule/owned', 'table': 'owned',
            'policy': {k: POLICY[k] for k in ('failure_threshold', 'recovery_threshold', 'minimum_bypass_seconds')},
            'zones': {z: {'app_route': 'rt-' + z, 'health_route': 'health-rt-' + z,
                         'nat': {'id': 'n' + z, 'ip': POLICY['primary' if z == 'a' else 'alternate']['ip'], 'subnet': 'public-' + z},
                         'probes': {r: {'instance': r + '-' + z, 'subnet': r + '-subnet-' + z} for r in ('app', 'health')}} for z in ('a', 'c')}}


class Table:
    def __init__(self): self.items = {}; self.writes = []
    def get_item(self, **kw): return {'Item': copy.deepcopy(self.items.get(kw['Key']['id'], {}))}
    def put_item(self, **kw):
        self.items[kw['Item']['id']] = copy.deepcopy(kw['Item']); self.writes.append(kw)


class EC2:
    def __init__(self, cfg):
        self.cfg = cfg; self.paths = {z[k]: z['nat']['id'] for z in cfg['zones'].values() for k in ('app_route', 'health_route')}
        self.writes = []; self.failed = {'na'}; self.available = True; self.bad_probe = False; self.bad_vpc = False; self.bad_association = False
    def describe_route_tables(self, **kw):
        subnets = {z[role + '_route']: z['probes'][role]['subnet'] for z in self.cfg['zones'].values() for role in ('app', 'health')}
        return {'RouteTables': [{'RouteTableId': r, 'VpcId': 'other' if self.bad_vpc else self.cfg['vpc'],
            'Associations': [{'SubnetId': 'unrelated-subnet' if self.bad_association else subnets[r]}],
            'Routes': [{'DestinationCidrBlock': '0.0.0.0/0', 'NatGatewayId': self.paths[r]}]} for r in kw['RouteTableIds']]}
    def describe_instances(self, **kw):
        return {'Reservations': [{'Instances': [{'InstanceId': p['instance'], 'SubnetId': 'wrong' if self.bad_probe else p['subnet'],
            'VpcId': self.cfg['vpc'], 'State': {'Name': 'running'}} for z in self.cfg['zones'].values() for p in z['probes'].values()]}]}
    def describe_nat_gateways(self, **kw):
        return {'NatGateways': [{'NatGatewayId': z['nat']['id'], 'VpcId': self.cfg['vpc'], 'SubnetId': z['nat']['subnet'],
             'State': 'available' if self.available or z['nat']['id'] == 'na' else 'deleting'} for z in self.cfg['zones'].values()]}
    def replace_route(self, **kw):
        self.writes.append(kw); self.paths[kw['RouteTableId']] = kw['NatGatewayId']
    def samples(self, ssm, cfg):
        result = {}
        for z, data in cfg['zones'].items():
            for role in ('app', 'health'):
                nat = self.paths[data[role + '_route']]
                ip = POLICY['primary' if nat == 'na' else 'alternate']['ip']
                result[role + ':' + z] = sample(nat not in self.failed, ip)
        return result, 'command-owned'


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config(); self.ec2 = EC2(self.cfg); self.table = Table()
    def run_at(self, now, **kw):
        event = {'source': 'aws.events', 'account': self.cfg['account'], 'region': self.cfg['region'],
                 'resources': [self.cfg['rule_arn']], 'time': datetime.fromtimestamp(now, timezone.utc).isoformat()}
        with patch.object(controller.logging, 'info'):
            return controller.run(kw.pop('event', event), self.cfg, self.ec2, None, self.table,
                                  now=now, sampler=kw.pop('sampler', self.ec2.samples), **kw)
    def test_full_scheduled_failover_and_failback_preserves_native_health(self):
        self.run_at(1200); self.run_at(1260)
        self.assertEqual(self.ec2.paths['rt-a'], 'nc'); self.assertEqual(self.ec2.paths['health-rt-a'], 'na')
        self.ec2.failed.clear()
        for now in (1320, 1380, 1440): self.run_at(now)
        self.assertEqual([x['NatGatewayId'] for x in self.ec2.writes], ['nc', 'na'])
        self.assertTrue(all(x['DestinationCidrBlock'] == '0.0.0.0/0' and x['RouteTableId'] == 'rt-a' for x in self.ec2.writes))
    def test_same_algorithm_handles_c_to_a(self):
        self.ec2.failed = {'nc'}; self.run_at(1200); self.run_at(1260)
        self.assertEqual(self.ec2.paths['rt-c'], 'na'); self.assertEqual(self.ec2.paths['rt-a'], 'na')
    def test_duplicate_event_does_not_count_as_another_failure(self):
        self.run_at(1200)
        result = self.run_at(1200, sampler=lambda *_: self.fail('duplicate must not probe'))
        self.assertEqual(result['event'], 'DUPLICATE_OBSERVATION'); self.assertFalse(self.ec2.writes)
    def test_missed_interval_resets_failure_series(self):
        self.run_at(1200); self.run_at(1380); self.assertFalse(self.ec2.writes)
    def test_manual_dry_run_has_no_route_or_state_writes(self):
        self.run_at(1200); before = copy.deepcopy(self.table.items); writes = len(self.table.writes)
        self.run_at(1260, event={'dryRun': True})
        self.assertEqual(self.table.items, before); self.assertEqual(len(self.table.writes), writes); self.assertFalse(self.ec2.writes)
    def test_wrong_event_origin_stale_or_future_rejected(self):
        for event in ({}, {'source': 'manual'}, {'source': 'aws.events', 'account': 'other'}):
            with self.assertRaises(ValueError): self.run_at(1200, event=event)
        for t in (1000, 1201):
            event = {'source': 'aws.events', 'account': self.cfg['account'], 'region': self.cfg['region'],
                'resources': [self.cfg['rule_arn']], 'time': datetime.fromtimestamp(t, timezone.utc).isoformat()}
            with self.assertRaises(ValueError): self.run_at(1200, event=event)
        self.assertFalse(self.ec2.writes)
    def test_pause_has_no_probe_or_write(self):
        self.table.items['control'] = {'paused': True}
        result = self.run_at(1200, sampler=lambda *_: self.fail('paused must not probe'))
        self.assertEqual(result['event'], 'PAUSED'); self.assertFalse(self.table.writes)
    def test_native_health_drift_or_unowned_probe_or_vpc_refuses_changes(self):
        for fault in ('health', 'probe', 'vpc', 'association'):
            self.setUp()
            if fault == 'health': self.ec2.paths['health-rt-a'] = 'nc'
            if fault == 'probe': self.ec2.bad_probe = True
            if fault == 'vpc': self.ec2.bad_vpc = True
            if fault == 'association': self.ec2.bad_association = True
            with self.assertRaises(ValueError): self.run_at(1200)
            self.assertFalse(self.ec2.writes)
    def test_target_must_be_available(self):
        self.ec2.available = False; self.run_at(1200); result = self.run_at(1260)
        self.assertEqual(result['records'][0]['event'], 'TARGET_NOT_AVAILABLE'); self.assertFalse(self.ec2.writes)
    def test_unknown_control_result_never_causes_route_change(self):
        def bad(ssm, cfg):
            values, cid = self.ec2.samples(ssm, cfg); values['health:a']['valid'] = False; return values, cid
        self.run_at(1200); self.run_at(1260, sampler=bad); self.run_at(1320)
        self.assertFalse(self.ec2.writes)
    def test_external_change_before_write_is_not_overwritten(self):
        self.run_at(1200)
        def changed(ssm, cfg):
            result = self.ec2.samples(ssm, cfg); self.ec2.paths['rt-a'] = 'external'; return result
        result = self.run_at(1260, sampler=changed)
        self.assertEqual(result['records'][0]['event'], 'ROUTE_CHANGED_EXTERNALLY'); self.assertFalse(self.ec2.writes)
    def test_both_paths_down_are_not_a_reason_to_swap(self):
        self.ec2.failed = {'na', 'nc'}; self.run_at(1200); self.run_at(1260)
        self.assertFalse(self.ec2.writes)
    def test_lost_write_response_is_reconciled_with_new_hold_down(self):
        self.run_at(1200)
        replace = self.ec2.replace_route
        def lost(**kw): replace(**kw); raise RuntimeError('write response lost')
        self.ec2.replace_route = lost
        with self.assertRaises(RuntimeError): self.run_at(1260)
        self.assertEqual(self.ec2.paths['rt-a'], 'nc')
        self.ec2.replace_route = replace; self.ec2.failed.clear()
        self.run_at(1320)
        self.assertEqual(self.table.items['a']['last_switch'], 1320)
        self.run_at(1380); self.assertEqual(self.ec2.paths['rt-a'], 'nc')
        self.run_at(1440); self.assertEqual(self.ec2.paths['rt-a'], 'na')


class SamplerTests(unittest.TestCase):
    def ssm(self, response):
        return SimpleNamespace(send_command=lambda **kw: {'Command': {'CommandId': 'x'}},
            get_command_invocation=lambda **kw: response,
            exceptions=SimpleNamespace(InvocationDoesNotExist=LookupError))
    def test_successful_command_reports_actual_egress_failure_as_valid(self):
        values, _ = controller.read_samples(self.ssm({'Status': 'Success', 'StandardOutputContent': '{"ok":false,"ip":null}'}), config())
        self.assertTrue(all(v['valid'] and not v['ok'] for v in values.values()))
    def test_command_error_invalid_json_or_ip_are_unknown(self):
        for response in ({'Status': 'Failed', 'StandardOutputContent': '{"ok":false,"ip":null}'},
                         {'Status': 'Success', 'StandardOutputContent': 'not-json'},
                         {'Status': 'Success', 'StandardOutputContent': '{"ok":true,"ip":"not-ip"}'}):
            values, _ = controller.read_samples(self.ssm(response), config())
            self.assertTrue(all(not v['valid'] for v in values.values()))
    def test_pending_control_timeout_is_unknown(self):
        clock = iter([0, 0, 30])
        values, _ = controller.read_samples(self.ssm({'Status': 'InProgress'}), config(), clock=lambda: next(clock), sleep=lambda _: None)
        self.assertTrue(all(not v['valid'] for v in values.values()))


class QuiesceTests(unittest.TestCase):
    def test_legacy_state_without_controller_does_not_call_aws(self):
        runner = SimpleNamespace(aws=lambda *a, **kw: self.fail('legacy state must skip'))
        self.assertEqual(ops.quiesce(runner, {})['status'], 'not-managed')
    def test_schedule_stops_then_concurrency_drains_before_destroy(self):
        name = CONFIG['project'] + '-nat-autofailover'; calls = []; waits = []
        arn = f"arn:aws:lambda:{CONFIG['region']}:{CONFIG['account']}:function/{name}"
        value = {'resources': [{'module': 'module.nat_autofailover[0]', 'type': 'aws_lambda_function',
                  'instances': [{'attributes': {'function_name': name}}]},
                  {'module': 'module.nat_autofailover[0]', 'type': 'aws_cloudwatch_event_rule',
                   'instances': [{'attributes': {'name': name + '-every-minute'}}]}]}
        def aws(service, operation, *args, **kw):
            calls.append((service, operation))
            return {'list-rules': {'Rules': [{'Name': name + '-every-minute', 'Arn': f"arn:aws:events:{CONFIG['region']}:{CONFIG['account']}:rule/{name}-every-minute"}]},
                    'disable-rule': {}, 'list-functions': {'Functions': [{'FunctionName': name, 'FunctionArn': arn}]},
                    'get-function-configuration': {'Timeout': 40}, 'put-function-concurrency': {'ReservedConcurrentExecutions': 0}}[operation]
        self.assertEqual(ops.quiesce(SimpleNamespace(aws=aws), value, sleep=waits.append)['status'], 'quiesced')
        self.assertLess(calls.index(('events', 'disable-rule')), calls.index(('lambda', 'put-function-concurrency')))
        self.assertEqual(waits, [45])
    def test_state_cannot_target_another_function(self):
        value = {'resources': [{'module': 'module.nat_autofailover[0]', 'type': 'aws_lambda_function',
                  'instances': [{'attributes': {'function_name': 'unrelated'}}]}]}
        with self.assertRaises(ValueError): ops.quiesce(SimpleNamespace(aws=lambda *a, **kw: self.fail('must reject before API')), value)
    def test_permission_error_never_becomes_controller_absent(self):
        value = {'resources': [{'module': 'module.nat_autofailover[0]', 'type': 'aws_lambda_function',
                  'instances': [{'attributes': {'function_name': CONFIG['project'] + '-nat-autofailover'}}]}]}
        def denied(*args, **kw): raise RuntimeError('AccessDenied')
        with self.assertRaisesRegex(RuntimeError, 'AccessDenied'):
            ops.quiesce(SimpleNamespace(aws=denied), value, sleep=lambda _: self.fail('no draining after error'))
    def test_partial_rule_state_does_not_authorize_touching_untracked_lambda(self):
        name = CONFIG['project'] + '-nat-autofailover-every-minute'
        value = {'resources': [{'module': 'module.nat_autofailover[0]', 'type': 'aws_cloudwatch_event_rule',
                  'instances': [{'attributes': {'name': name}}]}]}
        def aws(service, operation, *args, **kwargs):
            self.assertEqual(service, 'events', 'no Lambda API authorized by this partial state')
            return {'Rules': []}
        result = ops.quiesce(SimpleNamespace(aws=aws), value, sleep=lambda _: self.fail('no Lambda to drain'))
        self.assertIsNone(result['function'])


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {'function': 'owned', 'rule': 'owned-rule', 'table': 'owned-state', 'vpc': 'vpc-owned',
            'zones': {z: {'app_route': 'rt-' + z, 'native_nat': 'n' + z,
                          'native_ip': '1.1.1.1' if z == 'a' else '2.2.2.2'} for z in ('a', 'c')}}
        self.paths = {'rt-a': 'na', 'rt-c': 'nc'}; self.now = 1200; self.enabled = True; self.paused = False
        self.records = {z: {'zone': z, 'dryRun': False, 'trigger': 'aws.events', 'event': 'NORMAL',
                          'routeAfter': 'n' + z, 'samples': {'app': sample(ip=v['native_ip'])}} for z, v in self.cfg['zones'].items()}
    def aws(self, service, op, *args, **kwargs):
        if op == 'describe-rule': return {'State': 'ENABLED' if self.enabled else 'DISABLED'}
        if op == 'get-function-concurrency': return {'ReservedConcurrentExecutions': 1}
        if op == 'describe-route-tables':
            return {'RouteTables': [{'RouteTableId': k, 'VpcId': 'vpc-owned', 'Routes': [
                {'DestinationCidrBlock': '0.0.0.0/0', 'NatGatewayId': v, 'State': 'active'}]} for k, v in self.paths.items()]}
        if op == 'get-item':
            zone = json.loads(args[args.index('--key') + 1])['id']['S']
            if zone == 'control': return {'Item': {'paused': {'BOOL': self.paused}}}
            return {'Item': {'last_observed': {'N': str(self.now)}, 'latest': {'S': json.dumps(self.records[zone])}}}
        raise AssertionError((service, op))
    def status(self): return ops.status(SimpleNamespace(aws=self.aws), self.cfg, now=1200)
    def test_native_and_fresh_verified_bypass(self):
        self.assertEqual(self.status()['bypassRoutes'], {})
        self.paths['rt-a'] = 'nc'; self.records['a'].update(routeAfter='nc')
        self.records['a']['samples']['app'] = sample(ip='2.2.2.2')
        self.assertEqual(self.status()['bypassRoutes'], {'rt-a': 'nc'})
    def test_missing_optional_control_item_can_be_a_blank_cli_response(self):
        def aws(service, op, *args, **kwargs):
            if op == 'get-item':
                self.assertTrue(kwargs.get('empty'))
                key = json.loads(args[args.index('--key') + 1])
                if key['id']['S'] == 'control':
                    return {}
            return self.aws(service, op, *args, **kwargs)

        result = ops.status(SimpleNamespace(aws=aws), self.cfg, now=self.now)
        self.assertEqual(set(result['zones']), {'a', 'c'})
    def test_stale_dry_unknown_or_mismatched_sample_does_not_authorize_bypass(self):
        self.now = 900
        with self.assertRaisesRegex(ValueError, 'stale'): self.status()
        self.now = 1200
        for update in ({'dryRun': True}, {'routeAfter': 'third-nat'}, {'trigger': 'manual'}, {'event': 'CONTROL_UNKNOWN'}):
            saved = dict(self.records['a']); self.records['a'].update(update)
            with self.assertRaises(ValueError): self.status()
            self.records['a'] = saved
        self.paths['rt-a'] = 'nc'
        with self.assertRaises(ValueError): self.status()
    def test_disabled_or_explicitly_paused_is_not_healthy(self):
        self.enabled = False
        with self.assertRaises(ValueError): self.status()
        self.enabled = True; self.paused = True
        with self.assertRaises(ValueError): self.status()
    def test_wait_retries_only_initial_unknown_or_absent_observations(self):
        runner = SimpleNamespace(); calls = []
        with patch.object(ops, 'status', side_effect=[ValueError('NAT controller probe result unknown: a'), {'ready': True}]):
            result = ops.wait_ready(runner, self.cfg, clock=lambda: 0, sleep=calls.append)
        self.assertEqual(result, {'ready': True}); self.assertEqual(calls, [15])
        with patch.object(ops, 'status', side_effect=RuntimeError('AccessDenied')):
            with self.assertRaises(RuntimeError): ops.wait_ready(runner, self.cfg, clock=lambda: 0, sleep=lambda _: self.fail('no retry'))
        with patch.object(ops, 'status', side_effect=ValueError('Unexpected route')):
            with self.assertRaises(ValueError): ops.wait_ready(runner, self.cfg, clock=lambda: 0, sleep=lambda _: self.fail('no retry'))


class ResidueTests(unittest.TestCase):
    def test_new_controller_resources_block_a_clean_deletion_result(self):
        import lab_remove
        keys = ('clusters DBInstances DBSnapshots DBInstanceAutomatedBackups LoadBalancers '
                'LoadBalancerDescriptions Volumes Buckets repositories Roles Policies Addresses '
                'Functions Topics TableNames trailList MetricAlarms OpenIDConnectProviderList '
                'CertificateSummaryList SecretList projects logGroups ResourceRecordSets Rules InstanceProfiles').split()
        for op, key, item in [
            ('list-functions', 'Functions', {'FunctionName': 'sol-test3-nat-autofailover'}),
            ('list-rules', 'Rules', {'Name': 'sol-test3-nat-autofailover-every-minute'}),
            ('list-tables', 'TableNames', 'sol-test3-nat-autofailover-state'),
            ('list-instance-profiles', 'InstanceProfiles', {'InstanceProfileName': 'sol-test3-nat-autofailover-probe'})]:
            def aws(service, operation, *args, **kwargs):
                if operation == 'list-queues': return {'QueueUrls': []}
                result = {k: [] for k in keys}
                if operation == op: result[key] = [item]
                return result
            with self.subTest(operation=op), self.assertRaisesRegex(ValueError, 'Resources remain'):
                lab_remove.verify_deleted(SimpleNamespace(aws=aws), {'volumes': []})


if __name__ == '__main__': unittest.main()
