"""Read-only lab gates. Does not deploy, restart, rotate, or delete anything.

Reports contain selected status fields only. Query errors always fail the gate;
AccessDenied is never interpreted as an absent resource.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

CONFIG = json.loads(Path(__file__).with_name('environment.json').read_text())


class LoadBalancerPending(ValueError):
    """Only known readiness states may be retried by the orchestration layer."""


def run(*args):
    result = subprocess.run(args, text=True, encoding='utf-8', capture_output=True, timeout=45)
    if result.returncode:
        raise RuntimeError('query failed: ' + ' '.join(args[:2]))
    # These mutations may succeed with no response body (S3 quiet mode).
    # Empty query output remains an error rather than being treated as absent resources.
    empty_success = {('aws', 'cloudtrail', 'stop-logging'), ('aws', 's3api', 'delete-objects')}
    if not result.stdout.strip() and args[:3] in empty_success:
        return {}
    return json.loads(result.stdout)


def aws(service, operation, *args):
    return run('aws', service, operation, *args, '--profile', CONFIG['profile'],
               '--region', CONFIG['region'], '--output', 'json', '--no-cli-pager')


def kube(kind, namespace=None):
    args = ['kubectl', 'get', kind, '--request-timeout=15s', '-o', 'json']
    if namespace:
        args += ['-n', namespace]
    return run(*args)


def check(condition, message):
    if not condition:
        raise ValueError(message)


def verify_nodes(nodes):
    items = nodes['items']
    check(3 <= len(items) <= 6, 'expected 3..6 nodes; check CA and group min/max')
    for node in items:
        check(node['metadata']['labels'].get('node.kubernetes.io/instance-type') == 't3.medium', 'unexpected node type')
        check(any(c['type'] == 'Ready' and c['status'] == 'True' for c in node['status']['conditions']), 'node not Ready')
    pools = [n['metadata']['labels'].get('final-node-pool') for n in items]
    check(1 <= pools.count('az-a') <= 3 and 2 <= pools.count('az-c') <= 3, 'unexpected AZ distribution')


def verify_volumes(items):
    check(bool(items), 'no monitoring PVC found')
    check(all(v.get('status', {}).get('phase') == 'Bound' for v in items), 'monitoring PVC not Bound')


def verify_ha_network(subnets, nats, tables, db, *, verified_bypasses=None):
    """Require native paths, or a separately confirmed fresh controller bypass."""
    verified_bypasses = verified_bypasses or {}
    check(db.get('MultiAZ') is True, 'RDS Multi-AZ disabled')
    primary, standby = db.get('AvailabilityZone'), db.get('SecondaryAvailabilityZone')
    check(bool(primary) and bool(standby) and primary != standby, 'RDS standby AZ not ready')
    by_subnet = {s['SubnetId']: s for s in subnets}
    active = [n for n in nats if n['State'] != 'deleted']
    check(len(active) == 2 and all(n['State'] == 'available' for n in active), 'expected two available NAT gateways')
    nat_az = {n['NatGatewayId']: by_subnet[n['SubnetId']]['AvailabilityZone'] for n in active}
    check(len(set(nat_az.values())) == 2, 'NAT gateways must occupy two AZs')
    check({primary, standby} == set(nat_az.values()), 'RDS/NAT AZ mismatch')
    paths = []
    for table in tables:
        defaults = [r for r in table.get('Routes', []) if r.get('DestinationCidrBlock') == '0.0.0.0/0' and r.get('NatGatewayId')]
        for association in table.get('Associations', []):
            sid = association.get('SubnetId')
            subnet = by_subnet.get(sid, {})
            if subnet.get('Tags') and any(t['Key'] == 'kubernetes.io/role/internal-elb' and t['Value'] == '1' for t in subnet['Tags']):
                check(len(defaults) == 1, 'app subnet requires exactly one NAT default route')
                route = defaults[0]
                check(route.get('State') == 'active', 'NAT route not active')
                native = nat_az.get(route['NatGatewayId']) == subnet['AvailabilityZone']
                confirmed = (route['NatGatewayId'] in nat_az and verified_bypasses.get(table['RouteTableId']) == route['NatGatewayId'])
                check(native or confirmed, 'app route crosses AZ without fresh verified bypass or references wrong NAT')
                paths.append({'az': subnet['AvailabilityZone'], 'subnet': sid, 'nat': route['NatGatewayId'], 'routeTable': table['RouteTableId'],
                              'mode': 'native' if native else 'verified-bypass'})
    check(len(paths) == 2 and len({p['az'] for p in paths}) == 2, 'expected two app subnet routes in distinct AZs')
    return {'natPaths': paths, 'rdsMultiAZ': True, 'primaryAZ': primary, 'standbyAZ': standby}


def infra():
    cluster = aws('eks', 'describe-cluster', '--name', CONFIG['cluster'])['cluster']
    check(cluster['status'] == 'ACTIVE', 'EKS not ACTIVE')
    net = cluster['resourcesVpcConfig']
    check(net['endpointPrivateAccess'], 'EKS private access disabled')
    check('0.0.0.0/0' not in net.get('publicAccessCidrs', []), 'EKS API open to the whole internet')
    for pool, sizes in [('az-a', (1, 1, 3)), ('az-c', (2, 2, 3))]:
        group = aws('eks', 'describe-nodegroup', '--cluster-name', CONFIG['cluster'],
                    '--nodegroup-name', CONFIG['cluster'] + '-' + pool)['nodegroup']
        config = group['scalingConfig']
        check(group['status'] == 'ACTIVE' and group['instanceTypes'] == ['t3.medium'], 'node group not ready or wrong type')
        check(config['minSize'] == sizes[0] and config['maxSize'] == sizes[2], 'wrong group bounds')
        # CA owns desiredSize; after initial creation it need not equal the initial value.
        check(config['minSize'] <= config['desiredSize'] <= config['maxSize'], 'desired outside group bounds')
    db = aws('rds', 'describe-db-instances', '--db-instance-identifier', CONFIG['database'])['DBInstances'][0]
    check(db['DBInstanceStatus'] == 'available' and not db['PubliclyAccessible'] and db['StorageEncrypted'], 'RDS unavailable/public/unencrypted')
    check(db['DBSubnetGroup']['VpcId'] == net['vpcId'], 'RDS and EKS VPC mismatch')
    check(db['BackupRetentionPeriod'] >= 1, 'RDS backup retention missing')
    vpc_filter = 'Name=vpc-id,Values=' + net['vpcId']
    from lab_common import Runner, state
    from nat_failover import config_from_state, status as nat_status
    runner = Runner()
    controller_config = config_from_state(state(runner, 'terraform'))
    if controller_config and controller_config['vpc'] != net['vpcId']:
        raise ValueError('NAT controller / active EKS VPC mismatch')
    controller = nat_status(runner, controller_config)
    topology = verify_ha_network(
        aws('ec2', 'describe-subnets', '--filters', vpc_filter)['Subnets'],
        aws('ec2', 'describe-nat-gateways', '--filter', vpc_filter)['NatGateways'],
        aws('ec2', 'describe-route-tables', '--filters', vpc_filter)['RouteTables'], db,
        verified_bypasses=controller['bypassRoutes'])
    return {'vpc': net['vpcId'], 'nodeBounds': 'a=1..3 c=2..3', 'database': 'private, encrypted, available',
            **topology, 'natController': controller,
            'manualFollowUp': 'Native or freshly verified bypass routes and RDS MultiAZ observed; fault injection and all SG paths are not proven by this gate'}


def tools():
    verify_nodes(kube('nodes'))
    verify_volumes(kube('pvc', 'monitoring')['items'])
    eso = kube('externalsecret/database-credentials', 'soldesk')
    check(any(c['type'] == 'Ready' and c['status'] == 'True' for c in eso.get('status', {}).get('conditions', [])), 'ESO not Ready')
    return {'nodes': 'Ready, t3.medium, AZ bounds', 'monitoringPVC': 'Bound', 'ESO': 'Ready',
            'manualFollowUp': 'Check Grafana/Prometheus distinct c hosts and CA/Alertmanager a hosts'}


def load_balancers():
    # List both families to investigate the reported second LB; do not guess its purpose.
    vpc = aws('eks', 'describe-cluster', '--name', CONFIG['cluster'])['cluster']['resourcesVpcConfig']['vpcId']
    all_v2 = aws('elbv2', 'describe-load-balancers')['LoadBalancers']
    all_v1 = aws('elb', 'describe-load-balancers')['LoadBalancerDescriptions']
    matches = [b for b in all_v2 if b.get('VpcId') == vpc]
    classic = [b['LoadBalancerName'] for b in all_v1 if b.get('VPCId') == vpc]
    shared = [b for b in matches if b['LoadBalancerName'] == CONFIG['loadBalancer']]
    inventory = {'vpc': vpc, 'v2': [{'name': b['LoadBalancerName'], 'type': b['Type']} for b in matches], 'classic': classic}
    # Inspect ownership/count before readiness, so extra LBs never become a wait.
    check(not classic and len(matches) == len(shared) and len(shared) <= 1,
          'additional LB in VPC; inspect tags, Ingress and Services before accepting (no deletion performed): ' + json.dumps(inventory))
    if not shared:
        raise LoadBalancerPending('shared ALB not created yet')
    check(shared[0]['Type'] == 'application', 'shared load balancer is not an ALB')
    code = shared[0]['State']['Code']
    if code == 'provisioning':
        raise LoadBalancerPending('shared ALB provisioning')
    check(code == 'active', 'shared ALB failed/unknown state; inspect controller and AWS')
    groups = aws('elbv2', 'describe-target-groups', '--load-balancer-arn', shared[0]['LoadBalancerArn'])['TargetGroups']
    if not groups:
        raise LoadBalancerPending('ALB has no target groups yet')
    for group in groups:
        targets = aws('elbv2', 'describe-target-health', '--target-group-arn', group['TargetGroupArn'])['TargetHealthDescriptions']
        states = [t['TargetHealth']['State'] for t in targets]
        check(all(s in {'healthy', 'initial', 'draining', 'unhealthy', 'unused', 'unavailable'} for s in states),
              'unknown ALB target state; inspect target health')
        if not targets or any(s != 'healthy' for s in states):
            raise LoadBalancerPending('ALB targets not all healthy yet')
    return inventory


def main():
    p = argparse.ArgumentParser()
    p.add_argument('phase', choices=['identity', 'infra', 'tools', 'load-balancers'])
    p.add_argument('--report', type=Path)
    args = p.parse_args()
    result = {'phase': args.phase, 'status': 'FAIL', 'retryable': False}
    try:
        identity = aws('sts', 'get-caller-identity')
        check(identity['Account'] == CONFIG['account'], 'wrong AWS account')
        if args.phase in ('tools',):
            context = subprocess.check_output(['kubectl', 'config', 'current-context'], text=True).strip()
            check(context == f"arn:aws:eks:{CONFIG['region']}:{CONFIG['account']}:cluster/{CONFIG['cluster']}", 'wrong Kubernetes context')
        result['details'] = {'identity': 'account matched'} if args.phase == 'identity' else {
            'infra': infra, 'tools': tools, 'load-balancers': load_balancers}[args.phase]()
        result['status'] = 'PASS'
    except LoadBalancerPending as error:
        result.update(reason=str(error), retryable=True)
    except (RuntimeError, ValueError, KeyError, subprocess.SubprocessError, OSError) as error:
        result['reason'] = str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
