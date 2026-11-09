"""AWS 없이 메시지 실패·중복·배포 digest·준비 상태를 검증합니다."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/ci'))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
email=load('email_handler','lambda/order_email/handler.py')
release=load('release','scripts/ci/release_manifest.py')
check=load('check_release','scripts/ops/check_release.py')
class Store:
    def __init__(self):self.items={}
    def claim(self,id,token,now):
        if self.items.get(id)=='SENT':return False
        if self.items.get(id)=='PROCESSING':raise email.Busy()
        self.items[id]='PROCESSING';return True
    def sent(self,id,token):self.items[id]='SENT'
    def release(self,id,token):
        if self.items.get(id)=='PROCESSING':self.items[id]='PENDING'
def event():
    return {'schemaVersion':1,'eventType':'ORDER_CREATED','eventId':'12345678-1234-4234-8234-123456789abc','orderId':1,'memberId':7,'recipientEmail':'customer@example.com','productName':'shoe','quantity':2,'total':3000}
def batch(data):return {'Records':[{'messageId':'message-1','body':json.dumps(data)}]}
class DeliveryTests(unittest.TestCase):
    def test_success_and_duplicate_logs_do_not_include_recipient_or_body(self):
        store=Store()
        with patch.object(email.logger,'warning') as logger:
            email.process(batch(event()),store,lambda data:{'MessageId':'accepted-message-123'})
            email.process(batch(event()),store,lambda data:None)
        logs=[json.loads(call.args[0]) for call in logger.call_args_list]
        self.assertEqual([item['event'] for item in logs],['order_email_accepted','order_email_duplicate_skipped'])
        self.assertEqual(logs[0]['sesMessageId'],'accepted-message-123')
        serialized=json.dumps(logs)
        self.assertNotIn(event()['recipientEmail'],serialized)
        self.assertNotIn(event()['productName'],serialized)

    def test_buyer_and_admin_are_delivered_and_deduplicated_independently(self):
        store=Store();sent=[]
        for _ in range(2):
            self.assertEqual(email.process(batch(event()),store,sent.append,admin_email='operator@example.com')['batchItemFailures'],[])
        self.assertEqual([d['notificationKind'] for d in sent], ['customer','admin'])
        self.assertEqual([d['recipientEmail'] for d in sent], ['customer@example.com','operator@example.com'])
        self.assertEqual(len(store.items),2)

    def test_admin_failure_retry_never_resends_successful_customer_delivery(self):
        store=Store();sent=[]
        def fail_admin(data):
            if data['notificationKind']=='admin': raise RuntimeError('private address')
            sent.append(data)
        self.assertTrue(email.process(batch(event()),store,fail_admin,admin_email='operator@example.com')['batchItemFailures'])
        self.assertEqual(email.process(batch(event()),store,sent.append,admin_email='operator@example.com')['batchItemFailures'],[])
        self.assertEqual([d['notificationKind'] for d in sent], ['customer','admin'])

    def test_customer_failure_does_not_prevent_admin_and_retry_skips_admin(self):
        store=Store();sent=[]
        def fail_customer(data):
            if data['notificationKind']=='customer': raise RuntimeError('private address')
            sent.append(data)
        self.assertTrue(email.process(batch(event()),store,fail_customer,admin_email='operator@example.com')['batchItemFailures'])
        self.assertEqual(email.process(batch(event()),store,sent.append,admin_email='operator@example.com')['batchItemFailures'],[])
        self.assertEqual([d['notificationKind'] for d in sent], ['admin','customer'])

    def test_existing_customer_sent_record_is_preserved_when_admin_is_enabled(self):
        store=Store();sent=[]
        store.items[event()['eventId']]='SENT'
        self.assertEqual(email.process(batch(event()),store,sent.append,admin_email='operator@example.com')['batchItemFailures'],[])
        self.assertEqual([d['notificationKind'] for d in sent], ['admin'])

    def test_admin_content_has_time_and_no_buyer_personal_information(self):
        data=dict(event(),occurredAt='2026-10-20T07:00:00Z')
        title,body=email.mail_content(data,'admin')
        self.assertIn('신규 주문 알림',title)
        self.assertIn('2026-10-20 16:00:00 KST',body)
        self.assertNotIn(data['recipientEmail'],body)

    def test_invalid_admin_configuration_fails_without_partial_send(self):
        sent=[]
        self.assertTrue(email.process(batch(event()),Store(),sent.append,admin_email='not-an-email')['batchItemFailures'])
        self.assertEqual(sent,[])
    def test_duplicate_event_is_not_sent_twice(self):
        store=Store();sent=[]
        self.assertEqual(email.process(batch(event()),store,sent.append)['batchItemFailures'],[])
        self.assertEqual(email.process(batch(event()),store,sent.append)['batchItemFailures'],[])
        self.assertEqual(len(sent),1)
    def test_ses_failure_returns_batch_failure_and_can_retry(self):
        store=Store()
        def fail(data):raise RuntimeError('SES failure')
        self.assertEqual(email.process(batch(event()),store,fail)['batchItemFailures'],[{'itemIdentifier':'message-1'}])
        sent=[];self.assertEqual(email.process(batch(event()),store,sent.append)['batchItemFailures'],[]);self.assertEqual(len(sent),1)
    def test_in_flight_event_is_retried_not_acknowledged(self):
        class BusyStore(Store):
            def claim(self,*args):raise email.Busy()
        self.assertEqual(email.process(batch(event()),BusyStore(),lambda e:self.fail('must not send'))['batchItemFailures'],[{'itemIdentifier':'message-1'}])
    def test_bad_messages_are_not_sent(self):
        for mutation in ({'schemaVersion':2},{'recipientEmail':'bad'},{'quantity':0},{'orderId':True},{'total':-1}):
            data=event();data.update(mutation)
            self.assertEqual(len(email.process(batch(data),Store(),lambda e:self.fail('must not send'))['batchItemFailures']),1)
    def test_safe_error_diagnostics_keep_failure_retryable(self):
        class SesError(Exception):
            response = {'Error': {'Code': 'AccessDeniedException', 'Message': 'private recipient'}}
        def fail(data): raise SesError('customer@example.com secret-message')
        with self.assertLogs(email.logger, level='ERROR') as logs:
            result = email.process(batch(event()), Store(), fail)
        diagnostic = json.loads(logs.records[0].getMessage())
        self.assertEqual(diagnostic['stage'], 'send')
        self.assertEqual(diagnostic['awsErrorCode'], 'AccessDeniedException')
        self.assertEqual(diagnostic['orderId'], 1)
        self.assertEqual(result['batchItemFailures'], [{'itemIdentifier': 'message-1'}])
        self.assertNotIn('customer@example.com', str(logs.output))
        self.assertNotIn('secret-message', str(logs.output))
        self.assertNotIn('private recipient', str(logs.output))

    def test_record_sent_failure_is_distinguished_from_ses_failure(self):
        class FailingStore(Store):
            def sent(self, *args): raise RuntimeError('private database error')
        with self.assertLogs(email.logger, level='ERROR') as logs:
            result = email.process(batch(event()), FailingStore(), lambda data: None)
        self.assertEqual(json.loads(logs.records[0].getMessage())['stage'], 'record_sent')
        self.assertEqual(len(result['batchItemFailures']), 1)
        self.assertNotIn('private database error', str(logs.output))

    def test_sns_envelope_is_supported(self):
        self.assertEqual(email.parse(json.dumps({'Message':json.dumps(event())})),event())
    def test_digest_pin_changes_only_selected_service(self):
        original=(ROOT/'app/msa/kustomization.yaml').read_text(encoding='utf-8')
        digest='sha256:'+'a'*64;sha='b'*40
        pinned=release.pin(original,'frontend',sha,digest)
        self.assertIn('digest: '+digest,pinned)
        self.assertEqual(pinned,release.pin(pinned,'frontend',sha,digest))
        updated=release.pin(pinned,'frontend','c'*40,'sha256:'+'d'*64)
        self.assertNotIn(digest,updated)
        with self.assertRaises(ValueError):release.pin(original,'frontend',sha,'bad')
    def test_tag_update_does_not_keep_previous_digest(self):
        original=(ROOT/'tests/fixtures/image-tags.yaml').read_text(encoding='utf-8')
        pinned=release.pin(original,'frontend','b'*40,'sha256:'+'a'*64)
        self.assertNotIn('digest: ',release.update(pinned,['frontend'],'c'*40))
    def test_deployment_must_match_images_generation_and_replicas(self):
        expected=[{'metadata':{'name':'frontend-depl'},'spec':{'template':{'spec':{'containers':[{'image':'repo@sha256:good'}]}}}}]
        actual={'items':[{'metadata':{'name':'frontend-depl','generation':2},'spec':{'replicas':2,'template':{'spec':{'containers':[{'image':'repo@sha256:good'}]}}},'status':{'observedGeneration':2,'updatedReplicas':2,'availableReplicas':2,'replicas':2}}]}
        self.assertTrue(check.deployed(expected,actual))
        actual['items'][0]['status']['updatedReplicas']=1;self.assertFalse(check.deployed(expected,actual))
        actual['items'][0]['status']['updatedReplicas']=2;actual['items'][0]['spec']['template']['spec']['containers'][0]['image']='old';self.assertFalse(check.deployed(expected,actual))
    def test_smoke_refuses_insecure_origin(self):
        for url in ['http://example.com','https://user:pass@example.com','https://example.com/x','https://example.com/?token=secret']:
            with self.assertRaises(ValueError):check.http_checks(url)
if __name__=='__main__':unittest.main()
