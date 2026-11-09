"""Scheduled, single-writer NAT route controller; API calls never use the NAT.

Only the two configured app default routes may change. Native health routes
remain immutable. EventBridge retries/duplicates must not advance counters.
"""
from datetime import datetime, timezone
import json
import logging
import os
import time

import boto3
from botocore.config import Config
from decision import decide, valid_sample

logging.getLogger().setLevel(logging.INFO)
CLIENT_CONFIG = Config(connect_timeout=3, read_timeout=5, retries={'max_attempts': 1})
COMMAND = """ip=$(curl --noproxy '*' -4 -fsS --connect-timeout 2 --max-time 4 https://checkip.amazonaws.com 2>/dev/null) || ip=$(curl --noproxy '*' -4 -fsS --connect-timeout 2 --max-time 4 https://api.ipify.org 2>/dev/null) || ip=''
if [ -n "$ip" ]; then printf '{"ok":true,"ip":"%s"}\\n' "$ip"; else printf '{"ok":false,"ip":null}\\n'; fi
"""


def read_samples(ssm, cfg, *, clock=time.monotonic, sleep=time.sleep):
    ids = {role + ':' + zone: value['instance'] for zone, z in cfg['zones'].items()
           for role, value in z['probes'].items()}
    cid = ssm.send_command(InstanceIds=list(ids.values()), DocumentName='AWS-RunShellScript',
        Parameters={'commands': [COMMAND], 'executionTimeout': ['15']}, TimeoutSeconds=30,
        Comment='TEST2 independent NAT path health check')['Command']['CommandId']
    pending, samples, end = dict(ids), {}, clock() + 20
    while pending and clock() < end:
        for name, iid in list(pending.items()):
            try:
                result = ssm.get_command_invocation(CommandId=cid, InstanceId=iid)
            except ssm.exceptions.InvocationDoesNotExist:
                continue
            if result['Status'] in ('Pending', 'InProgress', 'Delayed'):
                continue
            try:
                value = json.loads(result.get('StandardOutputContent', '').strip())
                value['valid'] = result['Status'] == 'Success'
                if not valid_sample(value):
                    raise ValueError('Invalid control result')
            except (ValueError, TypeError, KeyError):
                value = {'valid': False, 'ok': False, 'ip': None}
            samples[name] = value
            del pending[name]
        if pending:
            sleep(1)
    samples.update({name: {'valid': False, 'ok': False, 'ip': None} for name in pending})
    return samples, cid


def routes(ec2, cfg):
    expected = {z[k] for z in cfg['zones'].values() for k in ('app_route', 'health_route')}
    result = ec2.describe_route_tables(RouteTableIds=sorted(expected))['RouteTables']
    if {t['RouteTableId'] for t in result} != expected or any(t['VpcId'] != cfg['vpc'] for t in result):
        raise ValueError('Route table / VPC guard failed')
    subnets = {z[role + '_route']: z['probes'][role]['subnet']
               for z in cfg['zones'].values() for role in ('app', 'health')}
    if any({a['SubnetId'] for a in t.get('Associations', []) if a.get('SubnetId')} != {subnets[t['RouteTableId']]}
           for t in result):
        raise ValueError('Route association drift; refuse writes to a reassigned/shared table')
    return {t['RouteTableId']: next((r.get('NatGatewayId') for r in t['Routes']
                                    if r.get('DestinationCidrBlock') == '0.0.0.0/0'), None) for t in result}


def guard_probes(ec2, cfg):
    expected = {p['instance']: p['subnet'] for z in cfg['zones'].values() for p in z['probes'].values()}
    instances = [i for r in ec2.describe_instances(InstanceIds=sorted(expected))['Reservations'] for i in r['Instances']]
    if {i['InstanceId'] for i in instances} != set(expected) or any(
        i['VpcId'] != cfg['vpc'] or i['SubnetId'] != expected[i['InstanceId']] or i['State']['Name'] != 'running'
        for i in instances):
        raise ValueError('Probe ownership / placement / running-state guard failed')


def scheduled_slot(event, cfg, now):
    if (event.get('source') != 'aws.events' or event.get('account') != cfg['account']
            or event.get('region') != cfg['region'] or event.get('resources') != [cfg['rule_arn']]):
        raise ValueError('Writes require the configured scheduled event; manual inspection uses dryRun=true')
    try:
        timestamp = datetime.fromisoformat(event['time'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            raise ValueError('Timezone required')
        observed = timestamp.timestamp()
    except (KeyError, ValueError, TypeError):
        raise ValueError('Missing/invalid scheduled observation time') from None
    if not 0 <= now - observed <= 90:
        raise ValueError('Stale or future scheduled event')
    return int(observed // 60)


def run(event, cfg, ec2, ssm, table, *, now=None, sampler=read_samples):
    now = int(time.time()) if now is None else int(now)
    if type(event.get('dryRun', False)) is not bool:
        raise ValueError('dryRun must be a boolean')
    dry = event.get('dryRun', False)
    slot = now // 60 if dry else scheduled_slot(event, cfg, now)
    if table.get_item(Key={'id': 'control'}, ConsistentRead=True).get('Item', {}).get('paused'):
        return {'event': 'PAUSED'}
    states = {zone: table.get_item(Key={'id': zone}, ConsistentRead=True).get('Item', {}) for zone in cfg['zones']}
    due = [zone for zone, state in states.items() if dry or slot > int(state.get('last_slot', -1))]
    if not due:
        return {'event': 'DUPLICATE_OBSERVATION', 'slot': slot}
    current = routes(ec2, cfg)
    guard_probes(ec2, cfg)
    if any(current[z['health_route']] != z['nat']['id'] for z in cfg['zones'].values()):
        raise ValueError('Native health route drift; refuse all route changes')
    nats = ec2.describe_nat_gateways(NatGatewayIds=[z['nat']['id'] for z in cfg['zones'].values()])['NatGateways']
    nat_by_id = {n['NatGatewayId']: n for n in nats}
    for z in cfg['zones'].values():
        n = nat_by_id.get(z['nat']['id'], {})
        if n.get('VpcId') != cfg['vpc'] or n.get('SubnetId') != z['nat']['subnet']:
            raise ValueError('NAT ownership / placement guard failed')
    samples, cid = sampler(ssm, cfg)
    records = []
    for zone in due:
        z, prior = cfg['zones'][zone], dict(states[zone])
        peer = next(other for other in cfg['zones'] if other != zone)
        original = current[z['app_route']]
        # Missing scheduled intervals and externally observed route changes reset
        # consecutive evidence; a killed write cannot silently bypass hold-down.
        if slot != int(prior.get('last_slot', -1)) + 1:
            prior.update(failures=0, recoveries=0)
        if prior.get('last_route') != original:
            prior.update(failures=0, recoveries=0, last_switch=now)
        subset = {'app': samples['app:' + zone], 'primary': samples['health:' + zone],
                  'alternate': samples['health:' + peer]}
        policy = {**cfg['policy'], 'primary': z['nat'], 'alternate': cfg['zones'][peer]['nat']}
        new, target, reason = decide(prior, subset, original, policy, now)
        record = {'timeUTC': datetime.fromtimestamp(now, timezone.utc).isoformat(), 'zone': zone,
                  'trigger': event.get('source', 'manual-dry-run'), 'dryRun': dry, 'slot': slot,
                  'event': reason, 'routeBefore': original, 'routeAfter': original, 'samples': subset,
                  'commandId': cid, 'failures': new['failures'], 'recoveries': new['recoveries']}
        if target and not dry:
            if nat_by_id[target].get('State') != 'available':
                record['event'] = 'TARGET_NOT_AVAILABLE'
            elif routes(ec2, cfg)[z['app_route']] != original:
                record['event'] = 'ROUTE_CHANGED_EXTERNALLY'
                new.update(failures=0, recoveries=0)
            else:
                ec2.replace_route(RouteTableId=z['app_route'], DestinationCidrBlock='0.0.0.0/0', NatGatewayId=target)
                if routes(ec2, cfg)[z['app_route']] != target:
                    raise ValueError('Route write not confirmed; next observation must reconcile')
                new.update(last_switch=now, failures=0, recoveries=0)
                record.update(event=reason + '_ROUTE_CHANGED', routeAfter=target)
        if not dry:
            table.put_item(Item=dict(new, id=zone, last_slot=slot, last_observed=now,
                                     last_route=record['routeAfter'], latest=json.dumps(record)))
        logging.info(json.dumps(record))
        records.append(record)
    return {'event': 'OBSERVED', 'records': records}


def handler(event, context):
    cfg = json.loads(os.environ['CONFIG'])
    client = lambda service: boto3.client(service, config=CLIENT_CONFIG)
    table = boto3.resource('dynamodb', config=CLIENT_CONFIG).Table(cfg['table'])
    return run(event, cfg, client('ec2'), client('ssm'), table)
