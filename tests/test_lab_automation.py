"""Offline orchestration/guard tests. All AWS/GitHub mutations are fake."""
import base64
from contextlib import ExitStack, redirect_stdout
import copy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/ops'))
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import lab_common as common
import lab_install as install
import lab_remove as remove
import lab_verify as verify

SHA = 'a' * 40
RELEASE = 'b' * 40
SETTINGS = {'schema': 1, 'account': common.CONFIG['account'],
            'adminArn': 'arn:aws:iam::683668078297:user/unit-test',
            'alertEmail': 'alerts@example.com', 'senderEmail': 'sender@example.com',
            'testRecipientEmail': 'buyer@example.com', 'adminEmail': 'operator@example.com'}


class FakeInstallRunner:
    def __init__(self, root):
        self.root = Path(root)
        self.env = {}
        self.calls = []
        self.live = None
        self.app_active = False
    def tf(self, root, *args):
        self.calls.append(('tf', root, args))
        if args[:2] == ('output', '-json'):
            return json.dumps('arn:aws:iam::683668078297:role/sol-test3-github-actions-ecr-role')
        return ''
    def run(self, args, **kwargs):
        self.calls.append(tuple(args))
        return ''
    def aws(self, service, operation, *args, **kwargs):
        self.calls.append(('aws', service, operation, *args))
        if operation == 'get-email-identity': return {'VerifiedForSendingStatus': True}
        raise AssertionError((service, operation))
    def kube(self, *args):
        self.calls.append(('kubectl', *args))
        if args[1] == 'deployments': return {'items': []}
        if args[1] == 'applications': return {'items': []}
        raise AssertionError(args)


class InstallFlowTests(unittest.TestCase):
    def test_existing_owned_bucket_can_be_adopted_by_a_fresh_checkout(self):
        calls = []
        def tf(module, *args):
            calls.append(args)
            if args == ('state', 'list'):
                raise common.CommandError(['terraform', 'state', 'list'],
                                          SimpleNamespace(returncode=1, stderr='No state file was found!', stdout=''))
            return ''
        def aws(service, operation, *args):
            if operation == 'list-buckets': return {'Buckets': [{'Name': common.STATE_BUCKET}]}
            if operation == 'get-bucket-tagging': return {'TagSet': [{'Key': 'Project', 'Value': 'sol-test3'}, {'Key': 'Purpose', 'Value': 'TerraformState'}]}
            raise AssertionError(operation)
        runner = SimpleNamespace(tf=tf, aws=aws)
        with tempfile.TemporaryDirectory() as tmp, patch.object(install, 'apply_plan') as apply:
            install.bootstrap_state(runner, Path(tmp), True)
            self.assertEqual(len([c for c in calls if c[0] == 'import']), 6)
            apply.assert_called_once()

    def context(self, tmp, fail_tools=False):
        runner = FakeInstallRunner(tmp)
        journal = common.Journal(Path(tmp) / 'install-state.json', 'install')
        events = []
        failures = [fail_tools]
        def apply(runner, root, label, variables=None, **kwargs):
            events.append((label, copy.deepcopy(variables)))
            if label == 'infra':
                runner.live = {'resourcesVpcConfig': {'vpcId': 'vpc-unit'}, 'createdAt': common.now()}
            if label == 'tools' and failures[0]:
                failures[0] = False
                raise RuntimeError('mock tool install failure')
            if label == 'apps': runner.app_active = True
        def images(runner, journal, source):
            events.append(('images', None))
            journal.data['details']['releaseRevision'] = RELEASE
            journal.save()
        stack = ExitStack()
        stack.enter_context(patch.object(install, 'source_revision', return_value=SHA))
        stack.enter_context(patch.object(install, 'public_ip', return_value='203.0.113.2/32'))
        stack.enter_context(patch.object(install, 'cluster', side_effect=lambda runner: runner.live))
        stack.enter_context(patch.object(install, 'bootstrap_state', side_effect=lambda *args: events.append(('bootstrap', None))))
        stack.enter_context(patch.object(install, 'connect', side_effect=lambda *args: events.append(('connect', None))))
        stack.enter_context(patch.object(install, 'prepare_secrets', side_effect=lambda *args: events.append(('secrets', None))))
        stack.enter_context(patch.object(install, 'prepare_admin', side_effect=lambda *args: events.append(('admin', None))))
        stack.enter_context(patch.object(install, 'wait_alb', side_effect=lambda *args: events.append(('alb', None))))
        stack.enter_context(patch.object(install, 'wait_image_release', side_effect=images))
        stack.enter_context(patch.object(install, 'apply_plan', side_effect=apply))
        return stack, runner, journal, events

    def test_install_orders_gates_then_pins_initial_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            stack, runner, journal, events = self.context(tmp)
            with stack, redirect_stdout(io.StringIO()):
                install.install(runner, SETTINGS, journal, Path(tmp), approved=True)
            labels = [e[0] for e in events]
            self.assertLess(labels.index('infra'), labels.index('tools'))
            self.assertLess(labels.index('tools'), labels.index('admin'))
            self.assertLess(labels.index('images'), labels.index('apps'))
            self.assertLess(labels.index('apps'), labels.index('dns-mail'))
            tools = next(e[1] for e in events if e[0] == 'tools')
            apps = next(e[1] for e in events if e[0] == 'apps')
            endpoints = next(e[1] for e in events if e[0] == 'dns-mail')
            self.assertFalse(tools['enable_app_sync'])
            self.assertTrue(apps['enable_app_sync'])
            self.assertEqual(apps['github_revision'], RELEASE)
            self.assertTrue(endpoints['customer_email_enabled'])
            self.assertEqual(endpoints['customer_email_admin'], SETTINGS['adminEmail'])

    def test_failed_stage_stops_and_resume_does_not_recreate_completed_infra(self):
        with tempfile.TemporaryDirectory() as tmp:
            stack, runner, journal, events = self.context(tmp, fail_tools=True)
            with stack, redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    install.install(runner, SETTINGS, journal, Path(tmp), approved=True)
                self.assertNotIn('images', [e[0] for e in events])
                self.assertEqual(journal.data['status'], 'failed')
                resumed = common.Journal(journal.path, 'install')
                install.install(runner, SETTINGS, resumed, Path(tmp), approved=True)
            self.assertEqual([e[0] for e in events].count('infra'), 1)
            self.assertEqual([e[0] for e in events].count('tools'), 2)
            self.assertIn('verify', resumed.data['completed'])

    def test_infrastructure_only_records_checkpoint_and_defers_email_and_apps(self):
        with tempfile.TemporaryDirectory() as tmp:
            stack, runner, journal, events = self.context(tmp)
            with stack, redirect_stdout(io.StringIO()), patch.object(install, 'local_revision', return_value=SHA):
                install.install(runner, None, journal, Path(tmp), approved=True,
                                infrastructure_admin=SETTINGS['adminArn'])
                self.assertEqual(journal.data['completed'], ['bootstrap', 'infra'])
                self.assertEqual(journal.data['details']['infrastructureAdmin'], SETTINGS['adminArn'])
                self.assertEqual(events[-1][1]['alert_email'], '')
                self.assertFalse(any(call[:2] == ('aws', 'sesv2') for call in runner.calls))

                install.install(runner, SETTINGS, journal, Path(tmp), approved=True)
            self.assertEqual([label for label, _ in events].count('infra'), 1)
            self.assertIn('verify', journal.data['completed'])

    def test_existing_live_environment_cannot_use_initial_bootstrap_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            stack, runner, journal, events = self.context(tmp)
            runner.live = {'resourcesVpcConfig': {'vpcId': 'vpc-existing'}, 'createdAt': '2020-01-01T00:00:00+00:00'}
            with stack, self.assertRaises(ValueError):
                install.install(runner, SETTINGS, journal, Path(tmp), approved=True)
            self.assertEqual(events, [])

    def test_changed_source_or_deleted_cluster_stops_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            stack, runner, journal, events = self.context(tmp)
            journal.data['source'] = 'c' * 40
            with stack, self.assertRaises(ValueError):
                install.install(runner, SETTINGS, journal, Path(tmp), approved=True)
            self.assertEqual(events, [])

    def test_unverified_baseline_cannot_promote_to_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = common.Journal(Path(tmp) / 'j.json', 'install')
            journal.data['details']['releaseRevision'] = RELEASE
            with self.assertRaisesRegex(ValueError, 'verify the initial release'):
                install.promote_main(None, SETTINGS, journal, Path(tmp), approved=True)

    def test_resume_accepts_the_image_commit_pushed_by_the_recorded_run(self):
        runner = SimpleNamespace(run=lambda args: SHA if args[-1] == 'HEAD' else '')
        journal = SimpleNamespace(data={'source': SHA, 'details': {'imageRun': 17}})
        with patch.object(install, 'main_revision', return_value=RELEASE), \
                patch.object(install, 'image_release', return_value=(RELEASE, {})) as image_release:
            self.assertEqual(install.source_revision(runner, journal), SHA)
        image_release.assert_called_once_with(runner, SHA, RELEASE, 17)

    def test_image_release_rejects_a_different_run(self):
        def run(args):
            if args[:2] == ['git', 'rev-list']:
                return RELEASE
            if args[:2] == ['git', 'rev-parse']:
                return SHA
            return 'app/msa/kustomization.yaml\ndeploy/release.json'

        runner = SimpleNamespace(run=run, json=lambda args: {'intent': 'release', 'runId': '18'})
        with self.assertRaisesRegex(ValueError, 'recorded build run'):
            install.image_release(runner, SHA, RELEASE, 17)

    def test_custom_config_is_passed_to_the_final_verifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            stack, runner, journal, _ = self.context(tmp)
            config = Path(tmp) / 'school settings.json'
            with stack, redirect_stdout(io.StringIO()):
                install.install(runner, SETTINGS, journal, Path(tmp), approved=True, config_path=config)
            command = next(c for c in runner.calls if len(c) > 1 and c[1] == 'scripts/ops/lab_verify.py')
            self.assertEqual(command[command.index('--config') + 1], str(config))


class TeardownFlowTests(unittest.TestCase):
    def test_active_image_workflow_blocks_resource_deletion(self):
        calls = []
        runner = SimpleNamespace(
            run=lambda args: calls.append(args),
            json=lambda args: [{'databaseId': 123, 'status': 'in_progress'}])
        with self.assertRaisesRegex(ValueError, 'still active'):
            remove.pause_publishing(runner)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(command[-1] == 'false' for command in calls))

    def test_delayed_cloudtrail_write_recleans_storage_on_resume_and_state_bucket_is_last(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            directory = root / 'removal'; directory.mkdir()
            journal = common.Journal(root / 'remove-state.json', 'remove')
            events = []
            state_values = {
                name: {'resources': [{'type': 'mock', 'name': 'unit', 'mode': 'managed', 'instances': [{}]}],
                       'outputs': {'vpc_id': {'value': 'vpc-unit'}}}
                for name in common.STATE_KEYS
            }
            fail_once = [True]
            def run(command, **kwargs):
                phase = command[2]
                events.append(phase)
                if phase == 'capture':
                    common.save_json(Path(command[command.index('--manifest')+1]), {
                        'account': common.CONFIG['account'], 'cluster': common.CONFIG['cluster'],
                        'vpc': 'vpc-unit', 'volumes': []})
                return ''
            def aws(service, operation, *args, **kwargs):
                if operation == 'list-buckets': return {'Buckets': [{'Name': common.STATE_BUCKET}]}
                if operation == 'list-objects-v2': return {'Contents': [{'Key': key} for key in common.STATE_KEYS.values()]}
                if operation == 'get-caller-identity': return {'Account': common.CONFIG['account'], 'Arn': SETTINGS['adminArn']}
                raise AssertionError((service, operation))
            runner = SimpleNamespace(root=root, env={}, run=run, aws=aws)
            def apply(runner, module, label, *args, **kwargs):
                events.append(label)
                if label == 'destroy-infra':
                    # A clean process drops TF_VAR_* overrides. Destroy still
                    # needs Terraform's required input, even to delete SNS.
                    self.assertEqual(args[0].get('alert_email'), SETTINGS['alertEmail'])
                if label == 'destroy-infra' and fail_once[0]:
                    fail_once[0] = False
                    raise RuntimeError('simulated late CloudTrail BucketNotEmpty')
                state_values[module] = {'resources': []}
            def deleted(*args, **kwargs):
                events.append('residue-final' if kwargs.get('include_state') else 'residue')
                return {'status': 'PASS'}
            stack.enter_context(patch.object(remove, 'ROOT', root))
            stack.enter_context(patch.object(remove, 'pause_publishing', side_effect=lambda r: events.append('pause-publishing')))
            stack.enter_context(patch.object(remove, 'cluster', side_effect=lambda r: None if not common.managed(state_values['terraform']) else {'resourcesVpcConfig': {'vpcId': 'vpc-unit'}}))
            stack.enter_context(patch.object(remove, 'load_remote_states', side_effect=lambda r: copy.deepcopy(state_values)))
            stack.enter_context(patch.object(remove, 'connect'))
            stack.enter_context(patch.object(remove, 'prepare_secrets'))
            stack.enter_context(patch.object(remove, 'public_ip', return_value='203.0.113.2/32'))
            stack.enter_context(patch.object(remove, 'apply_plan', side_effect=apply))
            stack.enter_context(patch.object(remove, 'state', side_effect=lambda r, module: state_values[module]))
            stack.enter_context(patch.object(remove, 'verify_deleted', side_effect=deleted))
            stack.enter_context(patch.object(remove, 'clear_state_bucket', side_effect=lambda *a: events.append('state-bucket')))
            # This orchestration test must never read a real local recovery
            # checkpoint. Snapshot ownership/deletion has its own fake tests.
            stack.enter_context(patch('lab_recovery.discard_snapshots', side_effect=lambda *a: events.append('recovery-snapshots')))
            stack.enter_context(patch.object(remove, 'forget_bootstrap', side_effect=lambda *a: events.append('forget-bootstrap')))
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    remove.remove(runner, journal, directory, approved=True, settings=SETTINGS)
                self.assertNotIn('state-bucket', events)
                remove.remove(runner, common.Journal(journal.path, 'remove'), directory, approved=True, settings=SETTINGS)
            self.assertEqual(events.count('capture'), 1)
            self.assertEqual(events.count('destroy-tools'), 1)
            self.assertEqual(events.count('storage'), 2)
            self.assertLess(events.index('workloads'), events.index('monitoring'))
            self.assertLess(events.index('monitoring'), events.index('wait'))
            self.assertLess(events.index('residue'), events.index('state-bucket'))
            self.assertLess(events.index('recovery-snapshots'), events.index('state-bucket'))
            self.assertEqual(events[-1], 'residue-final')
            self.assertTrue(common.Journal(journal.path, 'remove').data['closed'])


class ImpactVerificationTests(unittest.TestCase):
    def test_rotation_resume_observes_the_same_request_without_rotating_twice(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp); calls = []; versions = iter(('before', 'after', 'after'))
            old = {app: ['old-' + app] for app in ('member', 'product', 'ordering')}
            new = {app: ['new-' + app] for app in old}
            def aws(service, operation, *args):
                calls.append(operation)
                if operation == 'describe-db-instances':
                    return {'DBInstances': [{'DBInstanceStatus': 'available', 'MasterUserSecret': {'SecretStatus': 'active', 'SecretArn': 'arn:unit'}}]}
                if operation == 'modify-db-instance': return {}
                raise AssertionError(operation)
            runner = SimpleNamespace(aws=aws)
            stack.enter_context(patch.object(verify, 'ROOT', root))
            stack.enter_context(patch.object(verify, 'current_version', side_effect=lambda *a: next(versions)))
            stack.enter_context(patch.object(verify, 'service_uids', side_effect=[old, new, new]))
            stack.enter_context(patch.object(verify, 'credential_ready', return_value='db-credential-sync-unit'))
            verify.rotate(runner, root)
            # Simulate a subsequent basic service check failing: checkpoint is still open.
            verify.rotate(runner, root)
            self.assertEqual(calls.count('modify-db-instance'), 1)
            checkpoint = common.Journal(root / '.lab/rotation-state.json', 'rotation')
            self.assertFalse(checkpoint.data['closed'])
            self.assertEqual(checkpoint.data['details']['afterVersion'], 'after')

    def test_failed_load_command_cleans_up_child_and_never_claims_hpa_success(self):
        hpa = {'spec': {'minReplicas': 1, 'maxReplicas': 3, 'targetCPUUtilizationPercentage': 60},
               'status': {'currentReplicas': 1}}
        child = SimpleNamespace(returncode=2, poll=lambda: 2)
        def kube(*args):
            if args[1] == 'hpa': return hpa
            if args[1] == 'pods': return {'items': [{'metadata': {'name': 'unit'}, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}]}
            if args[1] == 'nodes': return {'items': [1, 2, 3]}
            if args[1] == 'deployment': return {'status': {'availableReplicas': 1}}
            raise AssertionError(args)
        runner = SimpleNamespace(kube=kube, env={}, root=ROOT)
        commands = []
        def start(command, **kwargs):
            commands.append(command); return child
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'load command failed'):
            verify.scale(runner, popen=start)
        self.assertEqual(commands[0][-3:], ['180', 'sha256sum', '/dev/zero'])


class GuardTests(unittest.TestCase):
    def test_install_plan_refuses_real_replacements_and_destroy_refuses_updates(self):
        def plan(actions, kind='aws_eks_cluster'):
            return {'resource_changes': [{'address': 'unit.example', 'type': kind, 'mode': 'managed', 'change': {'actions': actions}}]}
        with self.assertRaises(ValueError): common.check_plan(plan(['delete', 'create']))
        self.assertEqual(len(common.check_plan(plan(['delete', 'create'], 'terraform_data'))), 1)
        with self.assertRaises(ValueError): common.check_plan(plan(['update']), destroy=True)
        self.assertEqual(len(common.check_plan(plan(['delete']), destroy=True)), 1)

    def test_partial_checkpoint_does_not_mark_failed_stage_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'; journal = common.Journal(path, 'install')
            def fail(): raise RuntimeError('test')
            with self.assertRaises(RuntimeError): journal.stage('infra', fail)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['completed'], [])
            self.assertEqual(saved['status'], 'failed')
            self.assertNotIn('test', saved.values())

    def test_wrong_account_never_passes_identity_guard(self):
        with self.assertRaises(ValueError):
            common.check_identity(SimpleNamespace(aws=lambda *args: {'Account': '000000000000'}))

    def test_settings_and_runtime_secret_cleanup(self):
        bad = dict(SETTINGS, adminEmail='bad email')
        with self.assertRaises(ValueError): common.valid_settings(bad)
        runner = SimpleNamespace(env={'PATH': 'safe', 'TF_VAR_jwt_secret': 'unit-only'})
        common.clear_runtime_secrets(runner)
        self.assertEqual(runner.env, {'PATH': 'safe'})


class StateBucketRunner:
    def __init__(self, *, lock=False, foreign=False, partial_error=False):
        self.calls = []; self.deleted = False; self.cleared = False
        self.lock = lock; self.foreign = foreign; self.partial_error = partial_error
        self.batch_sizes = []
    def aws(self, service, operation, *args, **kwargs):
        self.calls.append((service, operation, args))
        if operation == 'get-caller-identity': return {'Account': common.CONFIG['account']}
        if operation == 'list-buckets': return {'Buckets': [] if self.deleted else [{'Name': common.STATE_BUCKET}]}
        if operation == 'list-objects-v2':
            return {'Contents': [{'Key': 'sol-test3/infra/terraform.tfstate.tflock' if self.lock else 'sol-test3/infra/terraform.tfstate'}]}
        if operation == 'list-object-versions':
            key = 'other-project/state' if self.foreign else 'sol-test3/infra/terraform.tfstate'
            return {} if self.cleared else {'Versions': [{'Key': key, 'VersionId': str(i)} for i in range(1001)]}
        if operation == 'delete-objects':
            data = json.loads(Path(args[args.index('--delete') + 1][7:]).read_text())
            self.batch_sizes.append(len(data['Objects']))
            if self.partial_error: return {'Errors': [{'Code': 'AccessDenied'}]}
            if len(self.batch_sizes) == 2: self.cleared = True
            return {}
        if operation == 'delete-bucket': self.deleted = True; return {}
        raise AssertionError(operation)


class StateRemovalTests(unittest.TestCase):
    def test_empty_sqs_inventory_is_explicit_but_remaining_or_denied_queues_block(self):
        keys = ('clusters DBInstances DBSnapshots DBInstanceAutomatedBackups '
                'LoadBalancers LoadBalancerDescriptions Volumes Buckets repositories Roles '
                'Policies Addresses Functions Topics TableNames trailList MetricAlarms '
                'OpenIDConnectProviderList CertificateSummaryList SecretList projects logGroups '
                'ResourceRecordSets Rules InstanceProfiles').split()
        for mode in ('empty', 'remaining', 'denied'):
            def aws(service, operation, *args, **kwargs):
                if (service, operation) == ('sqs', 'list-queues'):
                    self.assertIn('--query', args)
                    # Model the CLI's empty JSON response after the projection.
                    if mode == 'denied':
                        raise common.CommandError(['aws', 'sqs', 'list-queues'], SimpleNamespace(
                            returncode=254, stdout='', stderr='An error occurred (AccessDenied)'))
                    return {'QueueUrls': [] if mode == 'empty' else ['https://sqs.example/sol-test3-leftover']}
                return {key: [] for key in keys}
            runner = SimpleNamespace(aws=aws)
            if mode == 'empty':
                self.assertEqual(remove.verify_deleted(runner, {'volumes': []})['status'], 'PASS')
            else:
                with self.assertRaises((ValueError, common.CommandError)):
                    remove.verify_deleted(runner, {'volumes': []})

    def empty(self):
        return {name: {'resources': []} for name in common.STATE_KEYS}
    def test_state_bucket_is_last_and_versions_are_batched_via_file(self):
        runner = StateBucketRunner()
        with tempfile.TemporaryDirectory() as tmp:
            remove.clear_state_bucket(runner, Path(tmp), self.empty())
            self.assertTrue(Path(tmp, 'terraform-state-empty.json').exists())
        self.assertTrue(runner.deleted)
        self.assertEqual(runner.batch_sizes, [1000, 1])

    def test_active_lock_foreign_keys_and_per_object_errors_preserve_bucket(self):
        for kwargs in ({'lock': True}, {'foreign': True}, {'partial_error': True}):
            runner = StateBucketRunner(**kwargs)
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
                remove.clear_state_bucket(runner, Path(tmp), self.empty())
            self.assertFalse(runner.deleted)

    def test_nonempty_terraform_state_prevents_any_bucket_operation(self):
        values = self.empty()
        values['terraform']['resources'] = [{'mode': 'managed', 'instances': [{}]}]
        runner = StateBucketRunner()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            remove.clear_state_bucket(runner, Path(tmp), values)
        self.assertEqual(runner.calls, [])


class PowerShellEntryTests(unittest.TestCase):
    def test_preview_and_missing_discard_guard_on_available_windows_shells(self):
        shells = [path for name in ('powershell', 'pwsh') if (path := shutil.which(name))]
        if not shells: self.skipTest('PowerShell not installed')
        with tempfile.TemporaryDirectory(prefix='lab path 한글 & ') as tmp:
            root = Path(tmp)
            (root / 'scripts/ops').mkdir(parents=True)
            (root / 'scripts/ci').mkdir(parents=True)
            for name in ('Install-Lab.ps1', 'Remove-Lab.ps1', 'Verify-Lab.ps1'):
                shutil.copy2(ROOT / name, root / name)
            for path in (ROOT / 'scripts/ops').glob('lab_*.py'):
                shutil.copy2(path, root / 'scripts/ops' / path.name)
            shutil.copy2(ROOT / 'scripts/ops/environment.json', root / 'scripts/ops/environment.json')
            # If a preview unexpectedly calls an external AWS CLI, fail immediately.
            trap = root / 'aws-called.txt'
            if os.name == 'nt':
                # Keep CMD source ASCII; the Unicode path travels in the Windows
                # environment, independent of the runner's ANSI code page.
                (root / 'aws.cmd').write_text('@echo off\necho called>"%MOCK_PREVIEW_TRAP%"\nexit /b 99\n', encoding='ascii')
            else:
                (root / 'aws').write_text('#!/bin/sh\ntouch "$MOCK_PREVIEW_TRAP"\nexit 99\n', encoding='ascii')
                (root / 'aws').chmod(0o755)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'], PYTHONUTF8='1', MOCK_PREVIEW_TRAP=str(trap))
            for shell in shells:
                for script in ('Install-Lab.ps1', 'Remove-Lab.ps1'):
                    result = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(root / script)],
                                            capture_output=True, encoding='utf-8', errors='replace', env=env, timeout=60)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('PREVIEW ONLY', result.stdout)
                result = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(root / 'Remove-Lab.ps1'), '-Execute'],
                                        capture_output=True, encoding='utf-8', errors='replace', env=env, timeout=60)
                self.assertNotEqual(result.returncode, 0)
            self.assertFalse(trap.exists())


if __name__ == '__main__':
    unittest.main()
