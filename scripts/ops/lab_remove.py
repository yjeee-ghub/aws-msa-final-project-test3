"""Destroy-only orchestration; the versioned state bucket is always last.

Public hosted zone, SES identities, AWS/GitHub accounts and unrelated OIDC
providers are not deleted. No arbitrary tag-based bulk deletion or force-finalizer
removal is performed. Lost state/unknown ownership is a stop condition.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import uuid

from lab_common import (CONFIG, ROOT, STATE_BUCKET, STATE_KEYS, Journal, Runner, CommandError, apply_plan,
                        check_identity, clear_runtime_secrets, cluster, confirm, connect,
                        load_settings, managed, now, preflight, prepare_secrets, public_ip, save_json, state)

STAGES = ('pause-publishing', 'pause-nat-controller', 'capture', 'workloads', 'monitoring', 'wait-alb-ebs', 'storage', 'tools', 'infra', 'residue', 'state-bucket')


def pause_publishing(runner):
    # Do not leave main pushes trying to publish into tomorrow's deleted ECR.
    # An already-running publisher may have passed its gate, so refuse teardown
    # until it has finished/cancelled rather than race its AWS writes.
    for name in ('ENABLE_IMAGE_PUBLISH', 'ENABLE_DEPLOY_CHECKS'):
        runner.run(['gh', 'variable', 'set', name, '--repo', CONFIG['repository'], '--body', 'false'])
    for workflow in ('build-push.yml', 'deploy-check.yml'):
        runs = runner.json(['gh', 'run', 'list', '--repo', CONFIG['repository'], '--workflow', workflow,
                            '--branch', 'main', '--limit', '100', '--json', 'databaseId,status'])
        if any(run['status'] != 'completed' for run in runs):
            raise ValueError('A main workflow is still active; wait/cancel it, then rerun removal before deleting AWS resources: ' + workflow)
    projects = runner.aws('codebuild', 'list-projects')['projects']
    if CONFIG['verifyProject'] in projects:
        ids = runner.aws('codebuild', 'list-builds-for-project', '--project-name', CONFIG['verifyProject'],
                         '--sort-order', 'DESCENDING', '--max-items', '100').get('ids', [])
        if ids:
            builds = runner.aws('codebuild', 'batch-get-builds', '--ids', *ids)['builds']
            if any(b['buildStatus'] == 'IN_PROGRESS' for b in builds):
                raise ValueError('Private verification is still active; wait/stop it before teardown')



def empty_remote_state():
    return {'version': 4, 'resources': [], 'outputs': {}}


def load_remote_states(runner):
    objects = runner.aws('s3api', 'list-objects-v2', '--bucket', STATE_BUCKET,
                         '--expected-bucket-owner', CONFIG['account'])
    keys = {item['Key'] for item in objects.get('Contents', [])}
    values = {}
    for root, key in STATE_KEYS.items():
        runner.tf(root, 'init', '-input=false', '-no-color')
        values[root] = state(runner, root) if key in keys else empty_remote_state()
    return values


def cloudtrail_bucket_not_empty(error, bucket):
    """Recognize one exact provider diagnostic, not arbitrary destroy failures."""
    if (not isinstance(error, CommandError)
            or error.args_run[1:3] != ['-chdir=terraform', 'apply']):
        return False
    text = error.stdout + '\n' + error.stderr
    diagnostics = re.findall(r'(?m)^Error: (.*?)(?=^Error: |\Z)', text, re.S | re.M)
    return (len(diagnostics) == 1
            and re.match(r'deleting S3 Bucket \(' + re.escape(bucket) + r'\):', diagnostics[0]) is not None
            and 'DeleteBucket' in diagnostics[0] and 'BucketNotEmpty' in diagnostics[0]
            and re.search(r'with module\.cloudtrail\.aws_s3_bucket\.logs,', diagnostics[0]) is not None)


def reclean_cloudtrail(runner, manifest, bucket):
    # Never widen cleanup to other buckets/resources after a partial destroy.
    if manifest.get('account') != CONFIG['account'] or manifest.get('cluster') != CONFIG['cluster']:
        raise ValueError('CloudTrail cleanup manifest identity mismatch')
    check_identity(runner)
    resources = managed(state(runner, 'terraform'))
    if (len(resources) != 1 or resources[0].get('module') != 'module.cloudtrail'
            or resources[0].get('type') != 'aws_s3_bucket' or resources[0].get('name') != 'logs'
            or len(resources[0].get('instances', [])) != 1
            or resources[0]['instances'][0].get('attributes', {}).get('id') != bucket):
        raise ValueError('CloudTrail retry requires only the exact recorded log bucket remaining in state')
    location = runner.aws('s3api', 'get-bucket-location', '--bucket', bucket,
                          '--expected-bucket-owner', CONFIG['account'])
    if (location.get('LocationConstraint') or 'us-east-1') != CONFIG['region']:
        raise ValueError('CloudTrail log bucket region mismatch')
    trail = f"arn:aws:cloudtrail:{CONFIG['region']}:{CONFIG['account']}:trail/{CONFIG['project']}-management-trail"
    trails = runner.aws('cloudtrail', 'describe-trails')['trailList']
    if any(t['TrailARN'] == trail for t in trails):
        runner.aws('cloudtrail', 'stop-logging', '--name', trail, empty=True)
        if runner.aws('cloudtrail', 'get-trail-status', '--name', trail)['IsLogging']:
            raise ValueError('CloudTrail still logging; stop before emptying logs')
    from destroy_lab import clear_bucket
    clear_bucket(bucket)


def destroy_infrastructure(runner, variables, manifest, directory, *, approved=False,
                           max_attempts=3, sleep=time.sleep):
    bucket = f"{CONFIG['project'].lower()}-cloudtrail-{CONFIG['account']}-{CONFIG['region']}"
    if max_attempts not in (1, 2, 3):
        raise ValueError('CloudTrail destroy attempts must be bounded to 1..3')
    for attempt in range(1, max_attempts + 1):
        try:
            # Every attempt regenerates, inspects and approves its own saved plan.
            apply_plan(runner, 'terraform', 'destroy-infra', variables, destroy=True,
                       approved=approved, directory=directory)
            return
        except CommandError as error:
            if attempt == max_attempts or not cloudtrail_bucket_not_empty(error, bucket):
                raise
            reclean_cloudtrail(runner, manifest, bucket)
            print(f'RETRY: exact CloudTrail log bucket refilled; destroy attempt {attempt + 1}/{max_attempts}', flush=True)
            sleep(10 * attempt)


def verify_deleted(runner, manifest, *, include_state=False):
    """Positive successful API reads, not empty/error-prone filtered shell output."""
    remaining = {}
    vpc = manifest.get('vpc')
    owned_volumes = {item['volume'] for item in manifest.get('volumes', [])}
    eks = runner.aws('eks', 'list-clusters')['clusters']
    if CONFIG['cluster'] in eks:
        remaining['eks'] = [CONFIG['cluster']]
    dbs = runner.aws('rds', 'describe-db-instances')['DBInstances']
    if any(d['DBInstanceIdentifier'] == CONFIG['database'] for d in dbs):
        remaining['rds'] = [CONFIG['database']]
    snapshots = runner.aws('rds', 'describe-db-snapshots', '--db-instance-identifier', CONFIG['database'])['DBSnapshots']
    if snapshots:
        remaining['rdsSnapshots'] = [s['DBSnapshotIdentifier'] for s in snapshots]
    backups = runner.aws('rds', 'describe-db-instance-automated-backups')['DBInstanceAutomatedBackups']
    matching = [b['DBInstanceIdentifier'] for b in backups if b.get('DBInstanceIdentifier') == CONFIG['database']]
    if matching:
        remaining['automatedBackups'] = matching
    if vpc:
        for operation, response_key, id_key in [
            ('describe-vpcs', 'Vpcs', 'VpcId'), ('describe-subnets', 'Subnets', 'SubnetId'),
            ('describe-network-interfaces', 'NetworkInterfaces', 'NetworkInterfaceId'),
            ('describe-security-groups', 'SecurityGroups', 'GroupId'), ('describe-route-tables', 'RouteTables', 'RouteTableId'),
            ('describe-vpc-endpoints', 'VpcEndpoints', 'VpcEndpointId')]:
            result = runner.aws('ec2', operation, '--filters', 'Name=vpc-id,Values=' + vpc)[response_key]
            if result:
                remaining[response_key] = [item[id_key] for item in result]
        nats = runner.aws('ec2', 'describe-nat-gateways', '--filter', 'Name=vpc-id,Values=' + vpc)['NatGateways']
        if any(n['State'] != 'deleted' for n in nats):
            remaining['nat'] = [n['NatGatewayId'] for n in nats if n['State'] != 'deleted']
        instances = runner.aws('ec2', 'describe-instances', '--filters', 'Name=vpc-id,Values=' + vpc)['Reservations']
        live = [i['InstanceId'] for r in instances for i in r['Instances'] if i['State']['Name'] != 'terminated']
        if live:
            remaining['ec2'] = live
    for service, operation, key, match in [
        ('elbv2', 'describe-load-balancers', 'LoadBalancers', lambda b: b.get('VpcId') == vpc),
        ('elb', 'describe-load-balancers', 'LoadBalancerDescriptions', lambda b: b.get('VPCId') == vpc)]:
        items = runner.aws(service, operation)[key]
        hits = [b['LoadBalancerName'] for b in items if vpc and match(b)]
        if hits:
            remaining[service] = hits
    volumes = runner.aws('ec2', 'describe-volumes')['Volumes']
    hits = []
    for volume in volumes:
        tags = {t['Key']: t['Value'] for t in volume.get('Tags', [])}
        # Candidates are a review hold, not an automatic deletion target.
        if (volume['VolumeId'] in owned_volumes or tags.get('Project') == 'sol-test3'
                or tags.get('kubernetes.io/cluster/sol-test3-eks') in ('owned', 'shared')):
            hits.append(volume['VolumeId'])
    if hits:
        remaining['ebs'] = hits
    buckets = {b['Name'] for b in runner.aws('s3api', 'list-buckets')['Buckets']}
    expected_buckets = {CONFIG['productImageBucket'], f"{CONFIG['project'].lower()}-cloudtrail-{CONFIG['account']}-{CONFIG['region']}", CONFIG['verifyBucket']}
    if include_state:
        expected_buckets.add(STATE_BUCKET)
    if buckets & expected_buckets:
        remaining['s3'] = sorted(buckets & expected_buckets)
    repos = runner.aws('ecr', 'describe-repositories')['repositories']
    expected_repos = {'apigateway', 'member-service', 'product-service', 'ordering-service', 'frontend-service'}
    if any(r['repositoryName'] in expected_repos for r in repos):
        remaining['ecr'] = [r['repositoryName'] for r in repos if r['repositoryName'] in expected_repos]
    roles = runner.aws('iam', 'list-roles')['Roles']
    if any(r['RoleName'].startswith('sol-test3-') for r in roles):
        remaining['iamRoles'] = [r['RoleName'] for r in roles if r['RoleName'].startswith('sol-test3-')]
    profiles = runner.aws('iam', 'list-instance-profiles')['InstanceProfiles']
    if any(p['InstanceProfileName'] == 'sol-test3-nat-autofailover-probe' for p in profiles):
        remaining['natInstanceProfile'] = ['sol-test3-nat-autofailover-probe']
    policies = runner.aws('iam', 'list-policies', '--scope', 'Local')['Policies']
    if any(p['PolicyName'].startswith('sol-test3-') for p in policies):
        remaining['iamPolicies'] = [p['PolicyName'] for p in policies if p['PolicyName'].startswith('sol-test3-')]
    addresses = runner.aws('ec2', 'describe-addresses')['Addresses']
    if any(any(t['Key'] == 'Project' and t['Value'] == 'sol-test3' for t in a.get('Tags', [])) for a in addresses):
        remaining['eip'] = [a['AllocationId'] for a in addresses if any(t['Key'] == 'Project' and t['Value'] == 'sol-test3' for t in a.get('Tags', []))]
    functions = runner.aws('lambda', 'list-functions')['Functions']
    owned_functions = [f['FunctionName'] for f in functions if f['FunctionName'] in {'sol-test3-order-email', 'sol-test3-nat-autofailover'}]
    if owned_functions:
        remaining['lambda'] = owned_functions
    nat_rules = runner.aws('events', 'list-rules', '--name-prefix', 'sol-test3-nat-autofailover-every-minute')['Rules']
    if any(r['Name'] == 'sol-test3-nat-autofailover-every-minute' for r in nat_rules):
        remaining['natSchedule'] = ['sol-test3-nat-autofailover-every-minute']
    # AWS CLI emits no JSON at all for an empty SQS ListQueues response.
    # Project an explicit object so an empty successful inventory is distinct
    # from AccessDenied/transport errors (which Runner still rejects).
    queues = runner.aws('sqs', 'list-queues', '--queue-name-prefix', 'sol-test3-',
                        '--query', '{QueueUrls: QueueUrls || `[]`}')['QueueUrls']
    if queues:
        remaining['sqs'] = queues
    topics = [t['TopicArn'] for t in runner.aws('sns', 'list-topics')['Topics'] if ':sol-test3-' in t['TopicArn']]
    if topics:
        remaining['sns'] = topics
    owned_tables = {'sol-test3-order-email-dedup', 'sol-test3-nat-autofailover-state'} & set(runner.aws('dynamodb', 'list-tables')['TableNames'])
    if owned_tables:
        remaining['dynamodb'] = sorted(owned_tables)
    trails = [t['Name'] for t in runner.aws('cloudtrail', 'describe-trails')['trailList'] if t['Name'].startswith('sol-test3-')]
    if trails:
        remaining['cloudtrail'] = trails
    alarms = [a['AlarmName'] for a in runner.aws('cloudwatch', 'describe-alarms')['MetricAlarms'] if a['AlarmName'].startswith('sol-test3-')]
    if alarms:
        remaining['alarms'] = alarms
    owned = manifest.get('owned', {})
    providers = {p['Arn'] for p in runner.aws('iam', 'list-open-id-connect-providers')['OpenIDConnectProviderList']}
    if providers & set(owned.get('oidc', [])):
        remaining['oidc'] = sorted(providers & set(owned['oidc']))
    certificates = runner.aws('acm', 'list-certificates')['CertificateSummaryList']
    matching_certificates = [c['CertificateArn'] for c in certificates if c['CertificateArn'] in owned.get('acm', [])]
    if matching_certificates:
        remaining['acm'] = matching_certificates
    secret_list = runner.aws('secretsmanager', 'list-secrets', '--include-planned-deletion')['SecretList']
    matching_secrets = [s['ARN'] for s in secret_list if s['ARN'] in owned.get('secrets', [])]
    if matching_secrets:
        remaining['managedSecrets'] = matching_secrets
    builds = runner.aws('codebuild', 'list-projects')['projects']
    if CONFIG['verifyProject'] in builds:
        remaining['codebuild'] = [CONFIG['verifyProject']]
    for prefix in ('/aws/eks/sol-test3-eks/', '/aws/lambda/sol-test3-order-email', '/aws/lambda/sol-test3-nat-autofailover', '/aws/codebuild/' + CONFIG['verifyProject']):
        logs = runner.aws('logs', 'describe-log-groups', '--log-group-name-prefix', prefix)['logGroups']
        if logs:
            remaining['logs:' + prefix] = [l['logGroupName'] for l in logs]
    records = runner.aws('route53', 'list-resource-record-sets', '--hosted-zone-id', CONFIG['hostedZoneId'])['ResourceRecordSets']
    names = tuple(CONFIG[key] + '.' for key in ('websiteHost', 'argoHost', 'grafanaHost'))
    matching = [r['Name'] for r in records if any(r['Name'] == name or r['Name'].endswith('.' + name) for name in names)]
    if matching:
        remaining['dns'] = matching
    if remaining:
        raise ValueError('Resources remain (no blind deletion): ' + json.dumps(remaining))
    return {'status': 'PASS', 'at': now(), 'stateBucketChecked': include_state,
            'retained': ['Existing Route53 hosted zone', 'SES verified identities', 'Unrelated IAM/OIDC/account settings']}


def clear_state_bucket(runner, directory, empty_states):
    if set(empty_states) != set(STATE_KEYS) or any(managed(s) for s in empty_states.values()):
        raise ValueError('Both Terraform states must be verified empty before bucket removal')
    check_identity(runner)
    for root, value in empty_states.items():
        save_json(directory / (root + '-state-empty.json'), value)
    buckets = {b['Name'] for b in runner.aws('s3api', 'list-buckets')['Buckets']}
    if STATE_BUCKET not in buckets:
        print('State bucket already absent (confirmed by successful inventory).', flush=True)
        return
    owner = ['--expected-bucket-owner', CONFIG['account']]
    current = runner.aws('s3api', 'list-objects-v2', '--bucket', STATE_BUCKET, *owner)
    if any(o['Key'] not in set(STATE_KEYS.values()) for o in current.get('Contents', [])):
        raise ValueError('Unexpected state-bucket object or active lock; preserve bucket')
    versions = runner.aws('s3api', 'list-object-versions', '--bucket', STATE_BUCKET, *owner)
    objects = [{'Key': o['Key'], 'VersionId': o['VersionId']} for o in versions.get('Versions', []) + versions.get('DeleteMarkers', [])]
    allowed = set(STATE_KEYS.values()) | {k + '.tflock' for k in STATE_KEYS.values()}
    if any(o['Key'] not in allowed for o in objects):
        raise ValueError('Other state roots/files found; do not delete their bucket')
    with tempfile.TemporaryDirectory(prefix='final-state-delete-') as temporary:
        path = Path(temporary) / 'delete.json'
        for start in range(0, len(objects), 1000):
            save_json(path, {'Objects': objects[start:start + 1000], 'Quiet': True})
            result = runner.aws('s3api', 'delete-objects', '--bucket', STATE_BUCKET, *owner,
                                '--delete', 'file://' + str(path), empty=True)
            if result.get('Errors'):
                raise ValueError('Some state versions failed deletion; bucket is retained')
    remaining = runner.aws('s3api', 'list-object-versions', '--bucket', STATE_BUCKET, *owner)
    if remaining.get('Versions') or remaining.get('DeleteMarkers'):
        raise ValueError('State bucket is not empty; do not force-delete')
    runner.aws('s3api', 'delete-bucket', '--bucket', STATE_BUCKET, *owner, empty=True)
    if STATE_BUCKET in {b['Name'] for b in runner.aws('s3api', 'list-buckets')['Buckets']}:
        raise ValueError('State bucket deletion not confirmed')
    print('DELETED: exact state bucket and all historical versions', flush=True)


def forget_bootstrap(runner, directory):
    path = runner.root / 'terraform-state-bootstrap/terraform.tfstate'
    if not path.exists():
        return
    value = json.loads(path.read_text(encoding='utf-8'))
    expected = {'aws_s3_bucket.state', 'aws_s3_bucket_versioning.state',
                'aws_s3_bucket_server_side_encryption_configuration.state', 'aws_s3_bucket_public_access_block.state',
                'aws_s3_bucket_ownership_controls.state', 'aws_s3_bucket_policy.state'}
    addresses = {r['type'] + '.' + r['name'] for r in managed(value)}
    if not addresses <= expected:
        raise ValueError('Unexpected bootstrap resources; retain local state for review')
    for resource in managed(value):
        if any(i.get('attributes', {}).get('id') != STATE_BUCKET for i in resource['instances']):
            raise ValueError('Bootstrap state refers to another bucket; do not forget it')
    if addresses:
        save_json(directory / 'bootstrap-state-before-forget.json', value)
        runner.tf('terraform-state-bootstrap', 'state', 'rm', *sorted(addresses))


def remove(runner, journal, directory, approved=False, keep_state=False, settings=None):
    journal.stage('pause-publishing', lambda: pause_publishing(runner), always=True)
    details = journal.data['details']
    buckets = {b['Name'] for b in runner.aws('s3api', 'list-buckets')['Buckets']}
    live = cluster(runner)
    if STATE_BUCKET not in buckets:
        if live:
            raise ValueError('Cluster exists but state bucket is missing; recover state instead of guessing deletions')
        if not details.get('emptyStatesSaved'):
            raise ValueError('No state bucket/checkpoint; inspect residue before declaring a deleted environment')
        evidence = verify_deleted(runner, details['manifest'], include_state=True)
        forget_bootstrap(runner, directory)
        save_json(directory / 'residue-final.json', evidence)
        journal.data['closed'] = True
        journal.save()
        install_checkpoint = ROOT / '.lab/install-state.json'
        if install_checkpoint.exists():
            prior = Journal(install_checkpoint, 'install')
            prior.data['closed'] = True
            prior.save()
        print('DONE: confirmed absent, including the state bucket.', flush=True)
        return
    values = load_remote_states(runner)
    for root, value in values.items():
        # Preserve the first snapshot, not a partially destroyed version on every retry.
        backup = directory / (root + '-state-before.json')
        if not backup.exists():
            save_json(backup, value)
    recorded_vpc = details.get('vpc')
    if live:
        actual_vpc = live['resourcesVpcConfig']['vpcId']
        state_vpc = values['terraform'].get('outputs', {}).get('vpc_id', {}).get('value')
        if (state_vpc not in (None, actual_vpc) or recorded_vpc not in (None, actual_vpc)
                or (state_vpc is None and recorded_vpc is None)):
            raise ValueError('State/checkpoint/live VPC mismatch')
        details['vpc'] = actual_vpc
    if 'owned' not in details:
        initial = values['terraform']
        owned = {'oidc': [], 'acm': [], 'secrets': []}
        for resource in managed(initial):
            category = {'aws_iam_openid_connect_provider': 'oidc', 'aws_acm_certificate': 'acm'}.get(resource['type'])
            if category:
                owned[category].extend(i['attributes']['arn'] for i in resource['instances'])
        secret_arn = initial.get('outputs', {}).get('database_secret_arn', {}).get('value')
        if secret_arn:
            owned['secrets'].append(secret_arn)
        details['owned'] = owned
    journal.save()
    capture_path = directory / 'destroy-manifest.json'
    from nat_failover import quiesce as quiesce_nat
    journal.stage('pause-nat-controller', lambda: quiesce_nat(runner, values['terraform']), always=True)
    helper = [sys.executable, 'scripts/ops/destroy_lab.py']

    if live and managed(values['terraform-k8s']):
        connect(runner, directory, allow_ip_update=True)
        def capture():
            if capture_path.exists():
                manifest = json.loads(capture_path.read_text(encoding='utf-8'))
                if manifest.get('vpc') != details['vpc'] or manifest.get('account') != CONFIG['account']:
                    raise ValueError('Capture belongs to another build; do not overwrite it')
            else:
                runner.run(helper + ['capture', '--manifest', str(capture_path)])
            details['manifest'] = json.loads(capture_path.read_text(encoding='utf-8'))
            journal.save()
        journal.stage('capture', capture)
        for phase in ('workloads', 'monitoring'):
            journal.stage(phase, lambda phase=phase: print(runner.run(helper + [phase, '--manifest', str(capture_path), '--execute', '--discard-data']), flush=True))
    elif live and 'tools' not in journal.data['completed'] and not details.get('manifest'):
        # First install may fail before any Kubernetes tool was created.
        connect(runner, directory, allow_ip_update=True)
        runner.run(helper + ['capture', '--manifest', str(capture_path)])
        details['manifest'] = json.loads(capture_path.read_text(encoding='utf-8'))
        if details['manifest']['volumes']:
            raise ValueError('Kubernetes state is missing but disks exist; preserve capture and recover state')
        journal.save()
    if not details.get('manifest'):
        # A failure before EKS creation has no CSI/ALB. Still preserve known VPC ownership.
        details['manifest'] = {'account': CONFIG['account'], 'cluster': CONFIG['cluster'],
                               'vpc': details.get('vpc') or values['terraform'].get('outputs', {}).get('vpc_id', {}).get('value'), 'volumes': []}
        save_json(capture_path, details['manifest'])
        journal.save()
    manifest = details['manifest']
    manifest['owned'] = details['owned']
    save_json(capture_path, manifest)
    journal.save()
    if manifest.get('vpc'):
        journal.stage('wait-alb-ebs', lambda: print(runner.run(helper + ['wait', '--manifest', str(capture_path)]), flush=True))
    # CloudTrail can deliver delayed objects after an earlier empty pass.
    # Recheck/empty exact project stores on resume until infrastructure destroy succeeds.
    journal.stage('storage', lambda: print(runner.run(helper + ['storage', '--manifest', str(capture_path), '--execute', '--discard-data']), flush=True),
                  always='infra' not in journal.data['completed'])

    def tools():
        if managed(values['terraform-k8s']):
            prepare_secrets(runner, destroy=True)
            apply_plan(runner, 'terraform-k8s', 'destroy-tools', destroy=True, approved=approved, directory=directory)
    journal.stage('tools', tools)

    def infrastructure():
        if managed(values['terraform']):
            identity = check_identity(runner)
            arn = settings['adminArn'] if settings else identity['Arn']
            if ':iam::' not in arn:
                raise ValueError('An IAM user/role ARN is needed for required destroy inputs; supply -ConfigPath')
            variables = {'eks_admin_principal_arn': arn, 'eks_public_access_cidrs': [public_ip()],
                         'alert_email': settings['alertEmail'] if settings else '',
                         'enable_website_dns': False, 'enable_management_dns': False, 'customer_email_enabled': False}
            destroy_infrastructure(runner, variables, manifest, directory, approved=approved)
    journal.stage('infra', infrastructure)
    from lab_recovery import discard_snapshots
    journal.stage('recovery-snapshots', lambda: discard_snapshots(runner), always=True)

    def residue():
        evidence = verify_deleted(runner, manifest)
        save_json(directory / 'residue-before-state-bucket.json', evidence)
    journal.stage('residue', residue, always=True)
    empty = {root: state(runner, root) if STATE_KEYS[root] in {o['Key'] for o in runner.aws('s3api', 'list-objects-v2', '--bucket', STATE_BUCKET).get('Contents', [])}
             else empty_remote_state() for root in STATE_KEYS}
    if any(managed(value) for value in empty.values()):
        raise ValueError('Terraform still tracks resources; state bucket must remain')
    for root, value in empty.items():
        save_json(directory / (root + '-state-empty.json'), value)
    details['emptyStatesSaved'] = True
    journal.save()
    if not keep_state:
        journal.stage('state-bucket', lambda: clear_state_bucket(runner, directory, empty))
        forget_bootstrap(runner, directory)
        save_json(directory / 'residue-final.json', verify_deleted(runner, manifest, include_state=True))
    else:
        print('RETAINED by request: Terraform state bucket', flush=True)
    journal.data['closed'] = True
    journal.save()
    install_checkpoint = ROOT / '.lab/install-state.json'
    if install_checkpoint.exists():
        prior = Journal(install_checkpoint, 'install')
        prior.data['closed'] = True
        prior.save()
    print('DONE: project teardown verified; source files and shared account/domain settings preserved.', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--discard-data', action='store_true')
    parser.add_argument('--keep-state-bucket', action='store_true')
    parser.add_argument('--approve-plans', action='store_true')
    parser.add_argument('--config', type=Path, default=ROOT / '.lab/lab-config.json')
    args = parser.parse_args()
    if not args.execute:
        print('PREVIEW ONLY. Teardown stages: ' + ' -> '.join(STAGES))
        print('No AWS queries/mutations. Actual full teardown: .\\Remove-Lab.ps1 -Execute -DiscardData')
        return
    if not args.discard_data:
        raise ValueError('Explicit -DiscardData required: accounts/products/orders/logs/images and state history are irreversibly removed')
    runner = Runner()
    directory = ROOT / '.lab/removal'
    directory.mkdir(parents=True, exist_ok=True)
    try:
        preflight(runner)
        journal = Journal(ROOT / '.lab/remove-state.json', 'remove')
        # New installation => new VPC. Preserve old capture/checkpoint rather than reusing it.
        install_path = ROOT / '.lab/install-state.json'
        active_install = install_path.exists() and not json.loads(install_path.read_text(encoding='utf-8')).get('closed')
        if journal.data.get('closed') and (cluster(runner) or active_install):
            archive = ROOT / '.lab/archive' / ('removal-' + uuid.uuid4().hex)
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(directory), str(archive))
            directory.mkdir(parents=True)
            journal.path.unlink()
            journal = Journal(journal.path, 'remove')
        confirm('Delete this test2 environment and its data/images/logs' + (' (retain state bucket)?' if args.keep_state_bucket else ', INCLUDING the state bucket?'), args.approve_plans)
        settings = load_settings(args.config) if args.config.exists() else None
        remove(runner, journal, directory, args.approve_plans, args.keep_state_bucket, settings)
    finally:
        clear_runtime_secrets(runner)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('STOPPED: capture/state/checkpoint kept. Rerun the same removal command.', file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print('FAIL: ' + str(error), file=sys.stderr)
        sys.exit(1)
