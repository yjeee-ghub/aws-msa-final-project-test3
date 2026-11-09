"""Failure/ownership boundaries for the integrated build; no AWS credentials."""
import copy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/ops'))
import lab_recovery as recovery
import protected_backup
import run_private_verify as verifier
import lab_common


class PrivateVerifierTests(unittest.TestCase):
    def test_failure_is_not_reported_as_success(self):
        client=SimpleNamespace(aws=lambda *args:{'builds':[{'id':'build-1','buildStatus':'FAILED'}]})
        with self.assertRaisesRegex(RuntimeError,'FAILED'), redirect_stdout(io.StringIO()):
            verifier.wait_build(client,'build-1')

    def test_timeout_stops_exact_build(self):
        calls=[]
        client=SimpleNamespace(aws=lambda *args:calls.append(args))
        with self.assertRaises(TimeoutError):
            verifier.wait_build(client,'exact-build',timeout=0,clock=lambda:0)
        self.assertEqual(calls,[('codebuild','stop-build','--id','exact-build')])

    def test_cancellation_stops_exact_build(self):
        calls=[]
        def aws(*args):
            calls.append(args)
            if args[1]=='stop-build':return {}
            return {'builds':[{'id':'exact-build','buildStatus':'IN_PROGRESS'}]}
        with self.assertRaises(KeyboardInterrupt), redirect_stdout(io.StringIO()):
            verifier.wait_build(SimpleNamespace(aws=aws),'exact-build',sleep=lambda n:(_ for _ in ()).throw(KeyboardInterrupt()))
        self.assertEqual(calls[-1],('codebuild','stop-build','--id','exact-build'))

    def test_revision_and_account_are_validated_before_upload(self):
        client=SimpleNamespace(aws=lambda *args:{'Account':'000000000000'})
        with self.assertRaisesRegex(ValueError,'commit SHA'):
            verifier.submit(client,'main')
        with self.assertRaisesRegex(ValueError,'account'):
            verifier.submit(client,'a'*40)


class RecoveryTests(unittest.TestCase):
    def test_targeted_preserve_refuses_data_or_network_deletion(self):
        for resource_type in ('aws_s3_bucket','aws_sqs_queue','aws_nat_gateway','aws_ecr_repository'):
            plan={'resource_changes':[{'address':'wrong.resource','type':resource_type,'change':{'actions':['delete']}}]}
            applied=[]
            def tf(root,*args):
                if args[0]=='show':return json.dumps(plan)
                applied.append(args[0]);return ''
            with tempfile.TemporaryDirectory() as tmp, patch.object(recovery,'FOLDER',Path(tmp)):
                with self.assertRaises(ValueError):
                    recovery.scoped_plan(SimpleNamespace(tf=tf),'unit',{},targets=recovery.TARGETS,destroy=True,approved=True)
            self.assertNotIn('apply',applied)

    def test_only_exact_service_dns_records_may_be_removed(self):
        plan={'resource_changes':[{'address':'aws_route53_record.website_certificate','type':'aws_route53_record','change':{'actions':['delete']}}]}
        runner=SimpleNamespace(tf=lambda root,*args:json.dumps(plan) if args[0]=='show' else '')
        with tempfile.TemporaryDirectory() as tmp, patch.object(recovery,'FOLDER',Path(tmp)), self.assertRaises(ValueError):
            recovery.scoped_plan(runner,'unit',{},allow_dns=True,approved=True)

    def test_restore_requires_three_distinct_claims_and_ebs_driver(self):
        value={'account':lab_common.CONFIG['account'],'cluster':lab_common.CONFIG['cluster'],
               'volumes':[{'pvc':str(n),'az':lab_common.CONFIG['region']+'c','pvSpec':{'csi':{'driver':'ebs.csi.aws.com'}}} for n in range(3)]}
        recovery.validate_backup(value)
        bad=copy.deepcopy(value);bad['volumes'][1]['pvc']='0'
        with self.assertRaises(ValueError):recovery.validate_backup(bad)
        bad=copy.deepcopy(value);bad['volumes'][1]['pvSpec']['csi']['driver']='unknown'
        with self.assertRaises(ValueError):recovery.validate_backup(bad)

    def test_no_snapshot_is_deleted_if_cluster_is_present(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(recovery,'FOLDER',Path(tmp)):
            journal=lab_common.Journal(Path(tmp)/'checkpoint.json','recovery')
            journal.data['details']['session']='unit-session';journal.save()
            runner=SimpleNamespace(aws=lambda *a:(_ for _ in ()).throw(AssertionError('must not mutate')))
            with patch.object(recovery,'cluster',return_value={'status':'ACTIVE'}),self.assertRaises(ValueError):
                recovery.discard_snapshots(runner)

    @unittest.skipUnless(os.name=='nt','Windows CurrentUser DPAPI')
    def test_backup_is_encrypted_and_same_user_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'backup.dpapi'
            value={'private':'unit-test-sensitive-value'}
            protected_backup.save(path,value)
            self.assertNotIn(b'unit-test-sensitive-value',path.read_bytes())
            self.assertEqual(protected_backup.load(path),value)


if __name__=='__main__':unittest.main()
