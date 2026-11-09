"""SNS/SQS 주문 이벤트 → SES. 비밀값/이메일/본문을 로그에 출력하지 않습니다."""
import json
import logging
import hashlib
import os
import re
import time
import uuid
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

class Busy(Exception):
    pass

def parse(body):
    event = json.loads(body)
    if isinstance(event, dict) and isinstance(event.get('Message'), str):
        event = json.loads(event['Message'])
    if not isinstance(event, dict) or event.get('schemaVersion') != 1 or event.get('eventType') != 'ORDER_CREATED':
        raise ValueError('Invalid event schema')
    if not re.fullmatch(r'[a-f0-9-]{36}', str(event.get('eventId', ''))):
        raise ValueError('Invalid event ID')
    if str(uuid.UUID(event['eventId'])) != event['eventId']:
        raise ValueError('Invalid canonical event ID')
    for field in ('orderId', 'memberId', 'quantity'):
        if type(event.get(field)) is not int or event[field] < 1:
            raise ValueError('Invalid order numbers')
    if type(event.get('total')) is not int or event['total'] < 0:
        raise ValueError('Invalid amount')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', str(event.get('recipientEmail', ''))):
        raise ValueError('Invalid recipient')
    name = event.get('productName')
    if not isinstance(name, str) or not name.strip() or len(name) > 255:
        raise ValueError('Invalid product')
    return event

def delivery_targets(data, admin_email):
    # Keep the customer key compatible with already-recorded SENT events.
    yield data['eventId'], dict(data, notificationKind='customer')
    if admin_email:
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', admin_email):
            raise ValueError('Invalid administrator recipient')
        suffix = hashlib.sha256(admin_email.encode()).hexdigest()
        yield data['eventId'] + ':admin:' + suffix, dict(
            data, notificationKind='admin', recipientEmail=admin_email)


def failure_log(failure, stage, data=None, kind=None):
    response = getattr(failure, 'response', {})
    error = response.get('Error', {}) if isinstance(response, dict) else {}
    code = error.get('Code', '') if isinstance(error, dict) else ''
    if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', code):
        code = 'Unavailable'
    logger.error(json.dumps({
        'event': 'order_email_failed', 'stage': stage, 'awsErrorCode': code,
        'errorType': type(failure).__name__, 'notificationKind': kind,
        'orderId': data['orderId'] if data else None,
        'eventId': data['eventId'] if data else None,
    }))


def processing_log(event, data, kind, response=None):
    item = {'event': event, 'eventId': data['eventId'], 'orderId': data['orderId'],
            'notificationKind': kind}
    message_id = response.get('MessageId') if isinstance(response, dict) else None
    if isinstance(message_id, str) and re.fullmatch(r'[A-Za-z0-9-]{1,200}', message_id):
        item['sesMessageId'] = message_id
    # WARNING is deliberate: Lambda's default Python logger otherwise omits INFO.
    logger.warning(json.dumps(item))


def process(event, store, send, now=None, admin_email=None):
    now = int(time.time()) if now is None else now
    failures = []
    for record in event.get('Records', []):
        data = None
        try:
            data = parse(record['body'])
            targets = list(delivery_targets(data, admin_email))
        except Exception as failure:
            failure_log(failure, 'parse', data)
            failures.append({'itemIdentifier': record['messageId']})
            continue
        failed = False
        for key, delivery in targets:
            token = str(uuid.uuid4())
            claimed = False
            stage = 'claim'
            try:
                if not store.claim(key, token, now):
                    processing_log('order_email_duplicate_skipped', data, delivery['notificationKind'])
                    continue
                claimed = True
                stage = 'send'
                response = send(delivery)
                processing_log('order_email_accepted', data, delivery['notificationKind'], response)
                stage = 'record_sent'
                store.sent(key, token)
            except Exception as failure:
                failure_log(failure, stage, data, delivery['notificationKind'])
                # A failed admin delivery must not resend a SENT customer delivery.
                # SES acceptance followed by a failed SENT write can still duplicate mail.
                failed = True
                if not claimed:
                    continue
                try:
                    store.release(key, token)
                except Exception as release_error:
                    failure_log(release_error, 'release', data, delivery['notificationKind'])
        if failed:
            failures.append({'itemIdentifier': record['messageId']})
    return {'batchItemFailures': failures}

class DynamoStore:
    def __init__(self, table):
        self.table = table

    def claim(self, event_id, token, now):
        try:
            self.table.update_item(
                Key={'eventId': event_id},
                UpdateExpression='SET #s=:processing, leaseToken=:token, leaseUntil=:lease, expiresAt=:ttl',
                ConditionExpression='attribute_not_exists(eventId) OR (#s <> :sent AND (attribute_not_exists(leaseUntil) OR leaseUntil < :now))',
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={':processing':'PROCESSING', ':sent':'SENT', ':token':token, ':lease':now+90, ':now':now, ':ttl':now+30*86400})
            return True
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            item = self.table.get_item(Key={'eventId':event_id}, ConsistentRead=True).get('Item', {})
            if item.get('status') == 'SENT':
                return False
            raise Busy('Event is being processed')

    def sent(self, event_id, token):
        self.table.update_item(Key={'eventId':event_id}, UpdateExpression='SET #s=:sent REMOVE leaseToken, leaseUntil',
            ConditionExpression='leaseToken=:token', ExpressionAttributeNames={'#s':'status'},
            ExpressionAttributeValues={':sent':'SENT',':token':token})

    def release(self, event_id, token):
        self.table.update_item(Key={'eventId':event_id}, UpdateExpression='SET leaseUntil=:zero',
            ConditionExpression='leaseToken=:token', ExpressionAttributeValues={':zero':0,':token':token})

def handler(event, context):
    import boto3
    from botocore.config import Config
    config = Config(connect_timeout=2, read_timeout=5, retries={'total_max_attempts':1})
    store = DynamoStore(boto3.resource('dynamodb', config=config).Table(os.environ['DEDUP_TABLE']))
    ses = boto3.client('sesv2', config=config)
    def send(data):
        kind = data['notificationKind']
        title, body = mail_content(data, kind)
        return ses.send_email(FromEmailAddress=os.environ['SENDER_EMAIL'], Destination={'ToAddresses':[data['recipientEmail']]},
            Content={'Simple':{'Subject':{'Data':title,'Charset':'UTF-8'},
            'Body':{'Text':{'Data':body,'Charset':'UTF-8'}}}})
    return process(event, store, send, admin_email=os.environ.get('ADMIN_EMAIL', '').strip())


def mail_content(data, kind):
    title = ('신규 주문 알림' if kind == 'admin' else '주문 완료 안내') + f" #{data['orderId']}"
    body = f"주문번호: {data['orderId']}\n상품: {data['productName']}\n수량: {data['quantity']}\n금액: {data['total']}원"
    if kind == 'admin':
        # No buyer email/name/address in the administrator notification.
        occurred = '기록 없음'
        try:
            instant = datetime.fromisoformat(data.get('occurredAt', '').replace('Z', '+00:00'))
            if instant.tzinfo is not None:
                occurred = instant.astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S KST')
        except (ValueError, TypeError, AttributeError):
            pass
        body += '\n주문 시각: ' + occurred
    return title, body
