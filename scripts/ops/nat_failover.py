"""Read-only controller status, and owned-controller quiescence before teardown."""
import argparse
import json
import time

from lab_common import CONFIG, Runner, check_identity, state


def config_from_state(value):
    return value.get('outputs', {}).get('nat_autofailover', {}).get('value')


def quiesce(runner, value, *, sleep=time.sleep):
    """No VPC/NAT/route mutation. Fail closed on ownership/API errors.

    Scan state too: partial installs may not have produced root outputs yet.
    Blocking new invocations is not enough; drain the function's max timeout.
    """
    expected = CONFIG['project'] + '-nat-autofailover'
    names = set()
    for resource in value.get('resources', []):
        if resource.get('module') == 'module.nat_autofailover[0]':
            for item in resource.get('instances', []):
                attrs = item.get('attributes', {})
                if resource['type'] == 'aws_lambda_function':
                    names.add(attrs.get('function_name'))
                elif resource['type'] == 'aws_cloudwatch_event_rule':
                    names.add(attrs.get('name'))
    config = config_from_state(value)
    if config:
        if config['vpc'] != value.get('outputs', {}).get('vpc_id', {}).get('value'):
            raise ValueError('NAT controller / state VPC mismatch')
        names.update([config['function'], config['rule']])
    if not names:
        return {'status': 'not-managed'}
    if not names <= {expected, expected + '-every-minute'}:
        raise ValueError('Unexpected NAT controller identity in state')
    # A partial state proving ownership of only the rule does not authorize
    # stopping a pre-existing function merely because its name happens to match.
    rule_owned = expected + '-every-minute' in names
    function_owned = expected in names
    rules = runner.aws('events', 'list-rules', '--name-prefix', expected + '-every-minute')['Rules'] if rule_owned else []
    for rule in rules:
        if rule['Name'] != expected + '-every-minute':
            continue
        arn = f"arn:aws:events:{CONFIG['region']}:{CONFIG['account']}:rule/{rule['Name']}"
        if rule['Arn'] != arn:
            raise ValueError('NAT schedule ownership mismatch')
        runner.aws('events', 'disable-rule', '--name', rule['Name'], empty=True)
    functions = runner.aws('lambda', 'list-functions')['Functions'] if function_owned else []
    owned = [f for f in functions if f['FunctionName'] == expected]
    for function in owned:
        arn = f"arn:aws:lambda:{CONFIG['region']}:{CONFIG['account']}:function/{expected}"
        if function['FunctionArn'] != arn:
            raise ValueError('NAT Lambda ownership mismatch')
        cfg = runner.aws('lambda', 'get-function-configuration', '--function-name', expected)
        timeout = cfg['Timeout']
        if not 1 <= timeout <= 40:
            raise ValueError('Unexpected NAT Lambda timeout; inspect before draining')
        result = runner.aws('lambda', 'put-function-concurrency', '--function-name', expected,
                            '--reserved-concurrent-executions', '0')
        if result.get('ReservedConcurrentExecutions') != 0:
            raise ValueError('NAT controller concurrency not stopped')
        sleep(timeout + 5)
    return {'status': 'quiesced', 'function': expected if function_owned else None}


def status(runner, config, *, now=None):
    if not config:
        return {'enabled': False, 'bypassRoutes': {}, 'zones': {}}
    now = int(time.time()) if now is None else int(now)
    rule = runner.aws('events', 'describe-rule', '--name', config['rule'])
    concurrency = runner.aws('lambda', 'get-function-concurrency', '--function-name', config['function'])
    if rule['State'] != 'ENABLED' or concurrency.get('ReservedConcurrentExecutions') != 1:
        raise ValueError('NAT controller disabled/paused; explicitly resume before basic verification')
    control = runner.aws('dynamodb', 'get-item', '--table-name', config['table'], '--consistent-read',
                         '--key', json.dumps({'id': {'S': 'control'}}), empty=True).get('Item', {})
    if control.get('paused', {}).get('BOOL') is True:
        raise ValueError('NAT controller explicitly paused in state')
    routes = runner.aws('ec2', 'describe-route-tables', '--route-table-ids',
                        *[z['app_route'] for z in config['zones'].values()])['RouteTables']
    paths = {r['RouteTableId']: next((x.get('NatGatewayId') for x in r['Routes']
             if x.get('DestinationCidrBlock') == '0.0.0.0/0' and x.get('State') == 'active'), None) for r in routes}
    if len(paths) != 2 or any(r['VpcId'] != config['vpc'] for r in routes):
        raise ValueError('NAT status route/VPC mismatch')
    result = {'enabled': True, 'bypassRoutes': {}, 'zones': {}}
    for zone, z in config['zones'].items():
        item = runner.aws('dynamodb', 'get-item', '--table-name', config['table'], '--consistent-read',
                          '--key', json.dumps({'id': {'S': zone}}), empty=True).get('Item', {})
        observed = int(item.get('last_observed', {}).get('N', '0'))
        if not 0 <= now - observed <= 180:
            raise ValueError('NAT controller observation stale/not ready: ' + zone)
        record = json.loads(item['latest']['S'])
        target = paths[z['app_route']]
        app = record['samples']['app']
        allowed = {v['native_nat']: v['native_ip'] for v in config['zones'].values()}
        if record.get('event') == 'CONTROL_UNKNOWN':
            raise ValueError('NAT controller probe result unknown: ' + zone)
        if (record['dryRun'] or record['trigger'] != 'aws.events' or record['zone'] != zone
                or record['routeAfter'] != target or target not in allowed
                or not app.get('valid') or not app.get('ok') or app.get('ip') != allowed[target]):
            raise ValueError('NAT egress not confirmed by fresh scheduled observation: ' + zone)
        if target != z['native_nat']:
            result['bypassRoutes'][z['app_route']] = target
        result['zones'][zone] = {'routeTable': z['app_route'], 'nat': target,
                                'mode': 'native' if target == z['native_nat'] else 'bypass',
                                'lastObserved': observed, 'event': record['event']}
    return result


def wait_ready(runner, config, *, timeout=360, clock=time.monotonic, sleep=time.sleep):
    end = clock() + timeout
    while True:
        try:
            return status(runner, config)
        except ValueError as error:
            # Only the initial absence/staleness is a readiness wait. IAM and
            # transport errors, paused controllers, unexpected routes fail now.
            if not str(error).startswith(('NAT controller observation stale/not ready:', 'NAT controller probe result unknown:')) or clock() >= end:
                raise
            sleep(15)


def main():
    parser = argparse.ArgumentParser(description='NAT controller read-only status (no fault injection)')
    parser.add_argument('--wait-ready', action='store_true')
    args = parser.parse_args()
    runner = Runner(); check_identity(runner)
    config = config_from_state(state(runner, 'terraform'))
    print(json.dumps((wait_ready if args.wait_ready else status)(runner, config), indent=2))


if __name__ == '__main__':
    main()
