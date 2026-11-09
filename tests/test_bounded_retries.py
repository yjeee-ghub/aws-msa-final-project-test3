"""Readiness and teardown retries: all commands, time and AWS calls are fake."""
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/ops'))
import destroy_lab
import lab_common as common
import lab_install
import lab_remove as remove
import lab_verify
import verify_lab as gates


def command_error(text='query failed', code=1):
    return common.CommandError(['terraform', '-chdir=terraform', 'apply'],
                               SimpleNamespace(returncode=code, stdout='', stderr=text))


class Clock:
    def __init__(self):
        self.value = 0
        self.waits = []
    def now(self):
        return self.value
    def sleep(self, value):
        self.waits.append(value)
        self.value += value


class ReadinessClassificationTests(unittest.TestCase):
    def aws(self, state='active', targets=('healthy',), extra=False, classic=False, missing=False):
        def call(service, operation, *args):
            if operation == 'get-caller-identity': return {'Account': common.CONFIG['account']}
            if operation == 'describe-cluster': return {'cluster': {'resourcesVpcConfig': {'vpcId': 'vpc-test'}}}
            if service == 'elb': return {'LoadBalancerDescriptions': [{'VPCId': 'vpc-test', 'LoadBalancerName': 'unexpected'}] if classic else []}
            if operation == 'describe-load-balancers':
                lbs = [] if missing else [{'VpcId': 'vpc-test', 'LoadBalancerName': common.CONFIG['loadBalancer'],
                                          'Type': 'application', 'State': {'Code': state}, 'LoadBalancerArn': 'alb-test'}]
                if extra: lbs.append({'VpcId': 'vpc-test', 'LoadBalancerName': 'other', 'Type': 'application'})
                return {'LoadBalancers': lbs}
            if operation == 'describe-target-groups': return {'TargetGroups': [{'TargetGroupArn': 'tg-test'}]}
            if operation == 'describe-target-health': return {'TargetHealthDescriptions': [{'TargetHealth': {'State': s}} for s in targets]}
            raise AssertionError((service, operation))
        return call

    def test_only_known_readiness_conditions_are_pending(self):
        for options in ({'missing': True}, {'state': 'provisioning'}, {'targets': ()},
                        {'targets': ('initial',)}, {'targets': ('healthy', 'draining')}, {'targets': ('unhealthy',)}):
            with patch.object(gates, 'aws', side_effect=self.aws(**options)), self.assertRaises(gates.LoadBalancerPending):
                gates.load_balancers()
        with patch.object(gates, 'aws', side_effect=self.aws()):
            self.assertEqual(len(gates.load_balancers()['v2']), 1)

    def test_extra_lb_failed_alb_unknown_target_and_query_denial_are_not_pending(self):
        for options in ({'extra': True, 'state': 'provisioning'}, {'classic': True, 'missing': True},
                        {'state': 'failed'}, {'targets': ('unknown-state',)}):
            with patch.object(gates, 'aws', side_effect=self.aws(**options)), self.assertRaises(ValueError) as error:
                gates.load_balancers()
            self.assertNotIsInstance(error.exception, gates.LoadBalancerPending)
        with patch.object(gates, 'aws', side_effect=RuntimeError('AccessDenied')), self.assertRaises(RuntimeError):
            gates.load_balancers()

    def test_cli_report_marks_only_pending_readiness_retryable(self):
        for options, retryable in [({'state': 'provisioning'}, True), ({'state': 'failed'}, False)]:
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'report.json'
                with patch.object(gates, 'aws', side_effect=self.aws(**options)), redirect_stdout(io.StringIO()), \
                        patch.object(sys, 'argv', ['verify_lab.py', 'load-balancers', '--report', str(path)]):
                    self.assertEqual(gates.main(), 1)
                self.assertIs(json.loads(path.read_text())['retryable'], retryable)


class BoundedReadinessTests(unittest.TestCase):
    def runner(self, results):
        calls = []
        def run(args, **kwargs):
            calls.append(tuple(args))
            result = results[min(len(calls) - 1, len(results) - 1)]
            path = Path(args[args.index('--report') + 1])
            if result == 'crash': raise command_error('no fresh report')
            report = {'phase': 'load-balancers', 'status': 'PASS' if result == 'ready' else 'FAIL',
                      'retryable': result == 'pending', 'details': {'vpc': 'vpc-test'}}
            common.save_json(path, report)
            if result != 'ready': raise command_error('do not echo private command output')
        return SimpleNamespace(run=run), calls

    def test_pending_rollout_eventually_succeeds_with_fresh_reports(self):
        runner, calls = self.runner(['pending', 'pending', 'ready']); clock = Clock()
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()):
            result = common.wait_alb(runner, temporary, timeout=60, clock=clock.now, sleep=clock.sleep)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(len(calls), 3)
        self.assertEqual(clock.waits, [15, 15])
        self.assertIs(lab_install.wait_alb, common.wait_alb)

    def test_persistent_unhealthy_targets_stop_at_deadline(self):
        runner, calls = self.runner(['pending']); clock = Clock()
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()), self.assertRaises(TimeoutError):
            common.wait_alb(runner, temporary, timeout=20, clock=clock.now, sleep=clock.sleep)
        self.assertEqual(clock.waits, [15, 5])
        self.assertEqual(len(calls), 3)

    def test_failed_query_and_stale_pending_report_never_authorize_retry(self):
        for result in ('denied', 'crash'):
            runner, calls = self.runner([result]); clock = Clock()
            with tempfile.TemporaryDirectory() as temporary:
                common.save_json(Path(temporary) / 'alb-check.json', {'phase': 'load-balancers', 'status': 'FAIL', 'retryable': True})
                with self.assertRaises(common.CommandError):
                    common.wait_alb(runner, temporary, clock=clock.now, sleep=clock.sleep)
            self.assertEqual(len(calls), 1)
            self.assertEqual(clock.waits, [])

    def test_basic_verification_uses_the_same_bounded_gate(self):
        def run(args, **kwargs):
            common.save_json(Path(args[args.index('--report') + 1]), {'status': 'PASS', 'details': {}})
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()):
            with patch.object(lab_verify, 'wait_alb', side_effect=TimeoutError('pending')) as wait:
                with self.assertRaises(TimeoutError):
                    lab_verify.basic(SimpleNamespace(run=run), {}, 'a' * 40, 'a' * 40, Path(temporary))
            self.assertEqual(wait.call_args.kwargs, {'timeout': 300, 'report_name': 'load-balancers.json'})

    def test_missing_or_malformed_success_report_is_not_accepted(self):
        for body in (None, 'not json', '{"phase":"infra","status":"PASS"}'):
            calls = []
            def run(args, **kwargs):
                calls.append(args)
                if body is not None:
                    Path(args[args.index('--report') + 1]).write_text(body)
            with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
                common.wait_alb(SimpleNamespace(run=run), temporary)
            self.assertEqual(len(calls), 1)


BUCKET = f"{common.CONFIG['project'].lower()}-cloudtrail-{common.CONFIG['account']}-{common.CONFIG['region']}"
DIAGNOSTIC = ('Error: deleting S3 Bucket (' + BUCKET + '): operation error S3: DeleteBucket,\n'
              'api error BucketNotEmpty: The bucket you tried to delete is not empty\n\n'
              '  with module.cloudtrail.aws_s3_bucket.logs,\n  on cloudtrail/s3.tf line 9\n')
MANIFEST = {'account': common.CONFIG['account'], 'cluster': common.CONFIG['cluster']}
STATE = {'resources': [{'module': 'module.cloudtrail', 'mode': 'managed', 'type': 'aws_s3_bucket',
                        'name': 'logs', 'instances': [{'attributes': {'id': BUCKET}}]}]}


class CloudTrailRetryTests(unittest.TestCase):
    def runner(self, state=None, *, account=None, region=None, logging=False, denied=False):
        calls = []
        def aws(service, operation, *args, **kwargs):
            calls.append((service, operation, args))
            if operation == 'get-caller-identity': return {'Account': account or common.CONFIG['account']}
            if operation == 'get-bucket-location':
                if denied: raise command_error('AccessDenied', 254)
                self.assertEqual(args[args.index('--expected-bucket-owner') + 1], common.CONFIG['account'])
                return {'LocationConstraint': region or common.CONFIG['region']}
            if operation == 'describe-trails':
                return {'trailList': [{'TrailARN': f"arn:aws:cloudtrail:{common.CONFIG['region']}:{common.CONFIG['account']}:trail/sol-test3-management-trail"}]} if logging else {'trailList': []}
            if operation == 'stop-logging': return {}
            if operation == 'get-trail-status': return {'IsLogging': True}
            raise AssertionError(operation)
        runner = SimpleNamespace(aws=aws, tf=lambda *args: json.dumps(STATE if state is None else state))
        return runner, calls

    def test_exact_refilled_log_bucket_is_recleaned_and_replanned(self):
        runner, calls = self.runner(); clock = Clock()
        with patch.object(remove, 'apply_plan', side_effect=[command_error(DIAGNOSTIC), None]) as apply, \
                patch.object(destroy_lab, 'clear_bucket') as clear, redirect_stdout(io.StringIO()):
            remove.destroy_infrastructure(runner, {}, MANIFEST, Path('unused'), approved=True, sleep=clock.sleep)
        self.assertEqual(apply.call_count, 2)
        clear.assert_called_once_with(BUCKET)
        self.assertEqual(clock.waits, [10])
        self.assertTrue(all(c.kwargs['destroy'] for c in apply.call_args_list))

    def test_persistent_refills_stop_after_three_plans(self):
        runner, _ = self.runner(); clock = Clock()
        with patch.object(remove, 'apply_plan', side_effect=command_error(DIAGNOSTIC)) as apply, \
                patch.object(destroy_lab, 'clear_bucket') as clear, redirect_stdout(io.StringIO()), self.assertRaises(common.CommandError):
            remove.destroy_infrastructure(runner, {}, MANIFEST, Path('unused'), approved=True, sleep=clock.sleep)
        self.assertEqual(apply.call_count, 3)
        self.assertEqual(clear.call_count, 2)
        self.assertEqual(clock.waits, [10, 20])

    def test_other_bucket_access_denied_and_mixed_diagnostics_never_retry(self):
        for text in (DIAGNOSTIC.replace(BUCKET, 'foreign-bucket'), DIAGNOSTIC.replace('BucketNotEmpty', 'AccessDenied'),
                     DIAGNOSTIC + '\nError: deleting another resource: AccessDenied\n',
                     DIAGNOSTIC.replace('module.cloudtrail.aws_s3_bucket.logs', 'module.other.aws_s3_bucket.logs')):
            runner, _ = self.runner()
            with patch.object(remove, 'apply_plan', side_effect=command_error(text)) as apply, \
                    patch.object(destroy_lab, 'clear_bucket') as clear, self.assertRaises(common.CommandError):
                remove.destroy_infrastructure(runner, {}, MANIFEST, Path('unused'), approved=True)
            self.assertEqual(apply.call_count, 1)
            clear.assert_not_called()

    def test_wrong_account_foreign_state_region_denial_and_active_logging_stop_cleanup(self):
        foreign = copy.deepcopy(STATE); foreign['resources'][0]['instances'][0]['attributes']['id'] = 'foreign-bucket'
        extra = copy.deepcopy(STATE); extra['resources'].append(copy.deepcopy(extra['resources'][0]))
        for options in ({'account': '000000000000'}, {'state': foreign}, {'state': extra},
                        {'region': 'us-west-2'}, {'denied': True}, {'logging': True}):
            runner, _ = self.runner(**options)
            with patch.object(remove, 'apply_plan', side_effect=command_error(DIAGNOSTIC)) as apply, \
                    patch.object(destroy_lab, 'clear_bucket') as clear, self.assertRaises((ValueError, common.CommandError)):
                remove.destroy_infrastructure(runner, {}, MANIFEST, Path('unused'), approved=True)
            self.assertEqual(apply.call_count, 1)
            clear.assert_not_called()

    def test_plan_failure_or_mismatched_manifest_cannot_trigger_cleanup(self):
        runner, calls = self.runner()
        error = command_error(DIAGNOSTIC)
        error.args_run[2] = 'plan'
        with patch.object(remove, 'apply_plan', side_effect=error), patch.object(destroy_lab, 'clear_bucket') as clear:
            with self.assertRaises(common.CommandError):
                remove.destroy_infrastructure(runner, {}, MANIFEST, Path('unused'), approved=True)
            clear.assert_not_called()
        with patch.object(destroy_lab, 'clear_bucket') as clear:
            with self.assertRaises(ValueError):
                remove.reclean_cloudtrail(runner, {'account': 'foreign'}, BUCKET)
            clear.assert_not_called()
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
