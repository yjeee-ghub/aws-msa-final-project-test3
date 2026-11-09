"""Offline regression tests: no Kubernetes or AWS endpoints are contacted."""
import copy
import importlib.util
import io
from pathlib import Path
import contextlib
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = load('credential_sync', 'app/msa/ops/db_credential_sync.py')
verify = load('verify_lab', 'scripts/ops/verify_lab.py')
webhook = load('webhook', 'scripts/ops/wait_webhook.py')
sys.path.insert(0, str(ROOT / 'scripts/ops'))
destroy = load('destroy_lab', 'scripts/ops/destroy_lab.py')
release = load('release_build2', 'scripts/ci/release_manifest.py')


class FakeApi:
    def __init__(self, old=False, failed=False, status=None):
        self.value = 'never-log-this-secret'
        self.calls = []
        self.failed = failed
        self.status = status
        digest = 'previous' if old else sync.fingerprint(self.secret())
        self.apps = {name: {
            'metadata': {'resourceVersion': '7', 'generation': 1},
            'spec': {'replicas': 1, 'template': {'metadata': {'annotations': {sync.ANNOTATION: digest}}}},
            'status': {'observedGeneration': 1, 'updatedReplicas': 1, 'availableReplicas': 1, 'replicas': 1}
        } for name in sync.DEPLOYMENTS}

    def secret(self):
        return {'data': {'DB_PW': self.value}, 'metadata': {'resourceVersion': '999'}}

    def deployment(self, name):
        if self.status:
            raise sync.ApiError(self.status)
        return copy.deepcopy(self.apps[name])

    def stamp(self, name, deployment, digest):
        self.calls.append(name)
        self.apps[name]['spec']['template']['metadata']['annotations'][sync.ANNOTATION] = digest
        if self.failed:
            self.apps[name]['status']['availableReplicas'] = 0


class CredentialPropagationTests(unittest.TestCase):
    def test_unchanged_value_does_not_restart_even_if_secret_metadata_changes(self):
        api = FakeApi()
        self.assertEqual(sync.reconcile(api), 'ready')
        self.assertEqual(api.calls, [])

    def test_changed_password_rolls_all_three_in_order_and_no_secret_is_logged(self):
        api = FakeApi(old=True)
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            sync.reconcile(api)
        self.assertEqual(api.calls, list(sync.DEPLOYMENTS))
        self.assertNotIn(api.value, log.getvalue())
        self.assertNotIn(sync.fingerprint(api.secret()), log.getvalue())
        # A later ESO refresh with unchanged data is a no-op.
        sync.reconcile(api)
        self.assertEqual(len(api.calls), 3)

    def test_failed_first_rollout_stops_before_other_services(self):
        api = FakeApi(old=True, failed=True)
        with self.assertRaises(TimeoutError):
            sync.reconcile(api, timeout=0)
        self.assertEqual(api.calls, ['member-depl'])

    def test_rotation_again_during_rollout_stops_sequence(self):
        api = FakeApi(old=True)
        stamp = api.stamp

        def rotating(*args):
            stamp(*args)
            api.value = 'a-second-password'

        api.stamp = rotating
        with self.assertRaises(RuntimeError):
            sync.reconcile(api)
        self.assertEqual(api.calls, ['member-depl'])

    def test_missing_initial_deployments_wait_but_forbidden_fails(self):
        self.assertEqual(sync.reconcile(FakeApi(status=404)), 'waiting')
        with self.assertRaises(sync.ApiError):
            sync.reconcile(FakeApi(status=403))

    def test_patch_conflict_is_not_overwritten_or_skipped(self):
        api = FakeApi(old=True)

        def conflict(*args):
            raise sync.ApiError(409)

        api.stamp = conflict
        with self.assertRaises(sync.ApiError):
            sync.reconcile(api, sleep=lambda _: None)
        self.assertEqual(api.calls, [])

    def test_later_deployment_changed_while_first_rolls_out_is_read_fresh(self):
        api = FakeApi(old=True)
        stamp = api.stamp
        def changing(name, deployment, digest):
            self.assertEqual(deployment['metadata']['resourceVersion'], api.apps[name]['metadata']['resourceVersion'])
            stamp(name, deployment, digest)
            if name == 'member-depl':
                api.apps['product-depl']['metadata']['resourceVersion'] = '8'
                api.apps['product-depl']['spec']['template']['metadata']['annotations']['unrelated'] = 'preserve'
        api.stamp = changing
        self.assertEqual(sync.reconcile(api), 'ready')
        self.assertEqual(api.calls, list(sync.DEPLOYMENTS))
        self.assertEqual(api.apps['product-depl']['spec']['template']['metadata']['annotations']['unrelated'], 'preserve')

    def test_409_retry_reads_new_resource_version_and_is_bounded(self):
        api = FakeApi(old=True)
        stamp = api.stamp
        attempts = []
        def once(name, deployment, digest):
            attempts.append(deployment['metadata']['resourceVersion'])
            if len(attempts) == 1:
                api.apps[name]['metadata']['resourceVersion'] = '8'
                raise sync.ApiError(409)
            self.assertEqual(deployment['metadata']['resourceVersion'], '8')
            stamp(name, deployment, digest)
        api.stamp = once
        sync.stamp_current(api, 'member-depl', sync.fingerprint(api.secret()), sleep=lambda _: None)
        self.assertEqual(attempts, ['7', '8'])
        calls = []
        def always(*args):
            calls.append(1)
            raise sync.ApiError(409)
        api.stamp = always
        with self.assertRaises(sync.ApiError):
            sync.stamp_current(api, 'product-depl', sync.fingerprint(api.secret()), sleep=lambda _: None)
        self.assertEqual(len(calls), 3)

    def test_permission_errors_are_not_retried_and_logs_are_safe(self):
        api = FakeApi(old=True)
        calls = []
        def denied(*args):
            calls.append(1)
            raise sync.ApiError(403, 'PATCH', 'product-depl')
        api.stamp = denied
        with self.assertRaises(sync.ApiError) as caught:
            sync.stamp_current(api, 'product-depl', sync.fingerprint(api.secret()), sleep=lambda _: None)
        self.assertEqual(len(calls), 1)
        message = sync.failure_message(caught.exception)
        self.assertIn('HTTP 403', message)
        self.assertIn('product-depl', message)
        self.assertNotIn(api.value, message)
        self.assertNotIn('private exception data', sync.failure_message(RuntimeError('private exception data')))

    def test_new_secret_during_conflict_retry_stops_before_patch(self):
        api = FakeApi(old=True)
        calls = []
        def rotating(*args):
            calls.append(1)
            api.value = 'changed-during-retry'
            raise sync.ApiError(409)
        api.stamp = rotating
        with self.assertRaises(RuntimeError):
            sync.stamp_current(api, 'member-depl', sync.fingerprint(api.secret()), sleep=lambda _: None)
        self.assertEqual(len(calls), 1)

    def test_missing_password_fails_closed(self):
        with self.assertRaises(ValueError):
            sync.fingerprint({'data': {}})


class StoragePayloadTests(unittest.TestCase):
    def test_large_s3_version_batch_uses_temporary_file_and_checks_errors(self):
        saved_paths = []
        listed = [False]
        def fake_aws(service, operation, *args):
            self.assertEqual(args[args.index('--expected-bucket-owner') + 1], destroy.CONFIG['account'])
            if operation == 'list-object-versions':
                if listed[0]: return {}
                listed[0] = True
                return {'Versions': [{'Key': 'long-key-' + 'x' * 100 + str(i), 'VersionId': str(i)} for i in range(1000)]}
            if operation == 'list-objects-v2': return {}
            if operation == 'delete-objects':
                request = args[args.index('--delete') + 1]
                self.assertTrue(request.startswith('file://'))
                path = Path(request[7:]);saved_paths.append(path)
                import json
                self.assertEqual(len(json.loads(path.read_text(encoding='utf-8'))['Objects']), 1000)
                return {}
            self.fail(operation)
        with patch.object(destroy, 'aws', side_effect=fake_aws), patch.object(destroy.time, 'sleep'):
            destroy.clear_bucket(destroy.BUCKETS[0])
        self.assertEqual(len(saved_paths), 1)
        self.assertFalse(saved_paths[0].exists())


class EmptyAwsResponseTests(unittest.TestCase):
    def test_successful_stop_logging_has_no_json_body(self):
        with patch.object(verify.subprocess, 'run', return_value=MagicMock(returncode=0, stdout='')):
            self.assertEqual(verify.run('aws', 'cloudtrail', 'stop-logging', '--name', 'test'), {})
            self.assertEqual(verify.run('aws', 's3api', 'delete-objects', '--bucket', 'test'), {})

    def test_empty_query_and_failed_stop_logging_are_not_success(self):
        with patch.object(verify.subprocess, 'run', return_value=MagicMock(returncode=0, stdout='')):
            with self.assertRaises(ValueError):
                verify.run('aws', 'ec2', 'describe-volumes')
        with patch.object(verify.subprocess, 'run', return_value=MagicMock(returncode=1, stdout='')):
            with self.assertRaises(RuntimeError):
                verify.run('aws', 'cloudtrail', 'stop-logging')


class ReadinessTests(unittest.TestCase):
    def test_webhook_needs_a_ready_endpoint(self):
        self.assertFalse(webhook.endpoints_ready({'items': []}))
        self.assertFalse(webhook.endpoints_ready({'items': [{'endpoints': [{'conditions': {'ready': False}}]}]}))
        self.assertTrue(webhook.endpoints_ready({'items': [{'endpoints': [{'conditions': {'ready': True}}]}]}))

    def test_pending_pvc_never_passes(self):
        with self.assertRaises(ValueError):
            verify.verify_volumes([{'status': {'phase': 'Pending'}}])
        with self.assertRaises(ValueError):
            verify.verify_volumes([])
        verify.verify_volumes([{'status': {'phase': 'Bound'}}])

    def test_wrong_node_az_distribution_fails(self):
        def node(pool):
            return {'metadata': {'labels': {'node.kubernetes.io/instance-type': 't3.medium', 'final-node-pool': pool}},
                    'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
        verify.verify_nodes({'items': [node('az-a'), node('az-c'), node('az-c')]})
        with self.assertRaises(ValueError):
            verify.verify_nodes({'items': [node('az-a'), node('az-a'), node('az-c')]})


class OperationalGuardsTests(unittest.TestCase):
    def test_cleanup_preview_does_not_even_query_aws(self):
        with patch.object(sys, 'argv', ['destroy_lab.py', 'storage']), patch.object(destroy, 'identity') as identity:
            destroy.main()
            identity.assert_not_called()

    def test_unapproved_bucket_and_state_bucket_cannot_be_emptied(self):
        with patch.object(destroy, 'aws') as api:
            for name in ('someone-else-bucket', 'sol-test3-tfstate-683668078297-ap-northeast-2'):
                with self.assertRaises(ValueError):
                    destroy.clear_bucket(name)
            api.assert_not_called()

    def test_failed_inventory_does_not_mean_all_resources_are_gone(self):
        with patch.object(destroy, 'aws', side_effect=RuntimeError('AccessDenied')):
            with self.assertRaises(RuntimeError):
                destroy.leftovers({'vpc': 'vpc-example', 'volumes': []})

    def test_already_removed_storage_is_skipped_only_after_successful_inventory(self):
        answers = [{'trailList': []}, {'Buckets': []}, {'repositories': []}]
        with patch.object(destroy, 'aws', side_effect=answers) as api:
            destroy.storage()
            self.assertEqual([c.args[:2] for c in api.call_args_list], [
                ('cloudtrail', 'describe-trails'), ('s3api', 'list-buckets'), ('ecr', 'describe-repositories')])

    def test_s3_partial_delete_error_fails_stage(self):
        answers = [{'Versions': [{'Key': 'example', 'VersionId': '1'}]}, {'Errors': [{'Code': 'AccessDenied'}]}]
        with patch.object(destroy, 'aws', side_effect=answers):
            with self.assertRaises(ValueError):
                destroy.clear_bucket(destroy.BUCKETS[0])

    def test_bot_release_pushes_only_the_validated_declaration_to_main(self):
        sha = 'a' * 40
        revision = 'b' * 40
        calls = []

        def run(*args):
            calls.append(args)
            if args[:2] == ('git', 'ls-remote'):
                return sha + '\trefs/heads/main'
            if args[:2] == ('git', 'rev-parse'):
                return revision if ('git', 'push', 'origin', 'HEAD:refs/heads/main') in calls else sha
            return ''

        with patch.dict(os.environ, {'GITHUB_SHA': sha, 'GITHUB_OUTPUT': 'step-output'}), \
                patch.object(release, 'run', side_effect=run), patch.object(release, 'validate') as validate, \
                patch.object(release, 'Path') as output_path:
            release.deploy()
        validate.assert_called_once_with('')
        self.assertIn(('git', 'push', 'origin', 'HEAD:refs/heads/main'), calls)
        output_path.return_value.open.return_value.__enter__.return_value.write.assert_called_once_with(
            'revision=' + revision + '\n')

    def test_stale_release_stops_before_committing_or_pushing(self):
        with patch.dict(os.environ, {'GITHUB_SHA': 'a' * 40}), \
                patch.object(release, 'run', return_value='b' * 40) as run:
            with self.assertRaisesRegex(ValueError, 'Main changed'):
                release.deploy()
        run.assert_called_once_with('git', 'ls-remote', 'origin', 'refs/heads/main')


if __name__ == '__main__':
    unittest.main()
