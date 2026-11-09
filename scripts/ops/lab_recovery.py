"""Preserve/rebuild the existing lab without adding another backup service.

Preserve removes EKS, its dependent tools and the DB instance only after native
RDS/EBS snapshots are ready. VPC/NAT, state, product S3, ECR and messaging remain
and continue to cost money. Full Remove-Lab is a separate irreversible action.
"""
import argparse
import base64
import copy
import json
from pathlib import Path
import sys
import time
import uuid

from lab_common import (APP_NAMES, CONFIG, ROOT, CommandError, Journal, Runner, apply_plan,
                        check_identity, clear_runtime_secrets, cluster, confirm, connect,
                        infra_variables, k8s_variables, load_settings, managed, preflight,
                        prepare_secrets, public_ip, save_json, state)
import protected_backup

FOLDER = ROOT / '.lab/recovery'
BACKUP = FOLDER / 'credentials.dpapi'
TARGETS = ('module.eks.aws_eks_cluster.main', 'module.rds.aws_db_instance.main')
PRESERVED_TYPES = {'aws_s3_bucket', 'aws_s3_bucket_versioning', 'aws_s3_bucket_policy',
                   'aws_s3_bucket_public_access_block', 'aws_ecr_repository',
                   'aws_sqs_queue', 'aws_sns_topic', 'aws_dynamodb_table',
                   'aws_vpc', 'aws_subnet', 'aws_nat_gateway'}


def validate_backup(value):
    if value.get('account') != CONFIG['account'] or value.get('cluster') != CONFIG['cluster']:
        raise ValueError('Recovery file belongs to another environment')
    if len(value.get('volumes', [])) != 3 or len({v['pvc'] for v in value['volumes']}) != 3:
        raise ValueError('Expected exactly three distinct bound monitoring volumes')
    for item in value['volumes']:
        if item['az'] not in (CONFIG['region'] + 'a', CONFIG['region'] + 'c'):
            raise ValueError('Unexpected monitoring AZ')
        if item['pvSpec'].get('csi', {}).get('driver') != 'ebs.csi.aws.com':
            raise ValueError('Unexpected monitoring volume driver')
    return value


def backup(runner, journal):
    if BACKUP.exists():
        return validate_backup(protected_backup.load(BACKUP))
    live = cluster(runner)
    app = runner.kube('get', 'application', 'final-apps', '-n', 'argocd')
    if not live or app.get('status', {}).get('health', {}).get('status') != 'Healthy':
        raise ValueError('Preserve requires a healthy source deployment')
    if app.get('status', {}).get('sync', {}).get('status') != 'Synced':
        raise ValueError('Wait for the source deployment to be Synced')
    capture_file = FOLDER / 'destroy-manifest.json'
    if not capture_file.exists():
        runner.run([sys.executable, 'scripts/ops/destroy_lab.py', 'capture', '--manifest', str(capture_file)])
    captured = json.loads(capture_file.read_text(encoding='utf-8'))
    if captured.get('account') != CONFIG['account'] or captured.get('vpc') != live['resourcesVpcConfig']['vpcId']:
        raise ValueError('Stale capture; do not overwrite the recovery file')
    volumes = []
    for item in captured['volumes']:
        pv = runner.kube('get', 'pv', item['pv'])
        pvc = runner.kube('get', 'pvc', item['pvc'], '-n', 'monitoring')
        volume = runner.aws('ec2', 'describe-volumes', '--volume-ids', item['volume'])['Volumes'][0]
        volumes.append(dict(item, pvSpec=pv['spec'], pvcSpec=pvc['spec'], az=volume['AvailabilityZone'],
                            labels=pvc['metadata'].get('labels', {})))
    secrets = {}
    for namespace, name in [('soldesk', 'my-app-secrets'), ('soldesk', 'final-admin-config'),
                            ('monitoring', 'monitoring-grafana')]:
        # Grafana may already use a restored existingSecret on a second preserve.
        if namespace == 'monitoring':
            try:
                obj = runner.kube('get', 'secret', 'monitoring-grafana-restored', '-n', namespace)
            except CommandError as error:
                if 'NotFound' not in error.stderr:
                    raise
                obj = runner.kube('get', 'secret', name, '-n', namespace)
        else:
            obj = runner.kube('get', 'secret', name, '-n', namespace)
        secrets[namespace + '/' + name] = obj['data']
    value = dict(account=CONFIG['account'], cluster=CONFIG['cluster'], vpc=live['resourcesVpcConfig']['vpcId'],
                 session=journal.data['details']['session'], revision=app['status']['sync']['revision'],
                 sourceRef=app['spec']['source']['targetRevision'], volumes=volumes, secrets=secrets)
    validate_backup(value)
    protected_backup.save(BACKUP, value)
    # Decrypt/compare is completed before ANY destructive stage.
    print('Protected backup round-trip verified for this Windows user.', flush=True)
    return value


def scoped_plan(runner, label, variables, *, targets=(), destroy=False, allow_dns=False, approved=False):
    varfile, planfile = FOLDER / (label + '.tfvars.json'), FOLDER / (label + '.tfplan')
    save_json(varfile, variables)
    args = ['plan', '-input=false', '-no-color', '-var-file=' + str(varfile), '-out=' + str(planfile)]
    if destroy:
        args += ['-destroy']
    args += ['-target=' + target for target in targets]
    text = runner.tf('terraform', *args)
    (FOLDER / (label + '-plan.txt')).write_text(text, encoding='utf-8')
    plan = json.loads(runner.tf('terraform', 'show', '-json', str(planfile)))
    changes = [c for c in plan.get('resource_changes', []) if c.get('mode', 'managed') == 'managed'
               and c['change']['actions'] != ['no-op']]
    for item in changes:
        actions = item['change']['actions']
        if destroy and (actions != ['delete'] or item['type'] in PRESERVED_TYPES):
            raise ValueError('Preservation plan would change retained data/network: ' + item['address'])
        if not destroy and 'delete' in actions and not (allow_dns and item['type'] == 'aws_route53_record'
                and item['address'] in ('aws_route53_record.website[0]', 'aws_route53_record.management["argocd"]',
                                        'aws_route53_record.management["grafana"]')):
            raise ValueError('Unexpected deletion in recovery plan: ' + item['address'])
    print('RECOVERY PLAN: ' + label + ': ' + str(len(changes)) + ' changes. See ' + str(FOLDER), flush=True)
    confirm('Apply this bounded preservation plan?', approved)
    if changes:
        (FOLDER / (label + '-apply.txt')).write_text(runner.tf('terraform', 'apply', '-input=false', '-no-color', str(planfile)), encoding='utf-8')


def quiesce(runner):
    # Application removal already stopped app writers. Stop monitoring writers,
    # keeping PVCs/Operator/CSI alive until snapshots have finished.
    runner.run(['kubectl', 'delete', 'prometheus,alertmanager', '-n', 'monitoring', '-l', 'release=monitoring',
                '--ignore-not-found', '--cascade=foreground', '--wait=true', '--timeout=300s'])
    runner.run(['kubectl', 'scale', 'deployment/monitoring-grafana', '-n', 'monitoring', '--replicas=0'])
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        pods = runner.kube('get', 'pods', '-n', 'monitoring')['items']
        if not any(p['metadata']['name'].startswith(('monitoring-grafana-', 'prometheus-monitoring-', 'alertmanager-monitoring-')) for p in pods):
            return
        time.sleep(5)
    raise TimeoutError('Monitoring writers did not stop; no snapshot/delete may proceed')


def snapshots(runner, journal, value):
    details, session = journal.data['details'], value['session']
    db_id = details.setdefault('dbSnapshot', 'sol-test3-preserve-' + session)
    journal.save()
    existing = runner.aws('rds', 'describe-db-snapshots', '--db-instance-identifier', CONFIG['database'])['DBSnapshots']
    if not any(s['DBSnapshotIdentifier'] == db_id for s in existing):
        runner.aws('rds', 'create-db-snapshot', '--db-instance-identifier', CONFIG['database'], '--db-snapshot-identifier', db_id,
                   '--tags', 'Key=Project,Value=sol-test3', 'Key=RecoverySession,Value=' + session)
    runner.run(['aws', 'rds', 'wait', 'db-snapshot-available', '--db-snapshot-identifier', db_id,
                '--region', CONFIG['region'], '--profile', CONFIG['profile']], timeout=3600)
    details.setdefault('ebsSnapshots', {})
    for volume in value['volumes']:
        key = volume['volume']
        if key not in details['ebsSnapshots']:
            matches = runner.aws('ec2', 'describe-snapshots', '--owner-ids', CONFIG['account'], '--filters',
                                 'Name=tag:RecoverySession,Values=' + session, 'Name=volume-id,Values=' + key)['Snapshots']
            if len(matches) > 1:
                raise ValueError('Ambiguous recovery snapshots; inspect before continuing')
            if matches:
                snap = matches[0]
            else:
                tags = [{'ResourceType': 'snapshot', 'Tags': [{'Key': 'Project', 'Value': 'sol-test3'},
                        {'Key': 'RecoverySession', 'Value': session}]}]
                snap = runner.aws('ec2', 'create-snapshot', '--volume-id', key, '--description', 'Final quiesced monitoring recovery',
                                  '--tag-specifications', json.dumps(tags))
            details['ebsSnapshots'][key] = snap['SnapshotId']
            journal.save()
        runner.run(['aws', 'ec2', 'wait', 'snapshot-completed', '--snapshot-ids', details['ebsSnapshots'][key],
                    '--region', CONFIG['region'], '--profile', CONFIG['profile']], timeout=3600)
    print('READY: RDS snapshot and three quiesced EBS snapshots.', flush=True)


def preserve(runner, settings, journal, approved):
    from lab_remove import pause_publishing
    details = journal.data['details']
    details.setdefault('session', uuid.uuid4().hex[:20])
    journal.save()
    if journal.data.get('closed'):
        raise ValueError('Recovery belongs to a discarded build; archive its folder before a new preserve')
    live = cluster(runner)
    if live:
        connect(runner, FOLDER, allow_ip_update=True)
    journal.stage('capture', lambda: backup(runner, journal))
    value = validate_backup(protected_backup.load(BACKUP))
    if live and live['resourcesVpcConfig']['vpcId'] != value['vpc']:
        raise ValueError('Recovery backup/live VPC mismatch')
    journal.stage('pause-publishing', lambda: pause_publishing(runner))
    variables = infra_variables(settings, public_ip())
    journal.stage('disable-endpoints', lambda: scoped_plan(runner, 'disable-endpoints', variables, allow_dns=True, approved=approved))
    helper = [sys.executable, 'scripts/ops/destroy_lab.py']
    for stage, action in [
        ('stop-apps', lambda: runner.run(helper + ['workloads', '--manifest', str(FOLDER / 'destroy-manifest.json'), '--execute', '--discard-data'])),
        ('quiesce', lambda: quiesce(runner)),
        ('snapshots', lambda: snapshots(runner, journal, value)),
        ('stop-monitoring', lambda: runner.run(helper + ['monitoring', '--manifest', str(FOLDER / 'destroy-manifest.json'), '--execute', '--discard-data'])),
        ('wait-alb-ebs', lambda: runner.run(helper + ['wait', '--manifest', str(FOLDER / 'destroy-manifest.json')])),
    ]:
        journal.stage(stage, action)
    def tools():
        prepare_secrets(runner, destroy=True)
        apply_plan(runner, 'terraform-k8s', 'preserve-tools', destroy=True, approved=approved, directory=FOLDER)
    journal.stage('remove-tools', tools)
    from nat_failover import quiesce as quiesce_nat
    journal.stage('pause-nat-controller', lambda: quiesce_nat(runner, state(runner, 'terraform')), always=True)
    journal.stage('remove-execution', lambda: scoped_plan(runner, 'preserve-execution', variables, targets=TARGETS, destroy=True, approved=approved))
    if cluster(runner):
        raise ValueError('Preserve did not remove the cluster')
    details['preserved'] = True
    journal.save()
    print('PRESERVED: EKS/DB removed; snapshots, product S3, images, messaging, state, VPC/NAT and NAT probes/endpoints retained (ongoing charges). NAT controller paused.', flush=True)


def restore_monitoring(runner, journal, value):
    tracked = set(runner.tf('terraform-k8s', 'state', 'list').splitlines())
    for name in ('soldesk', 'argocd', 'monitoring'):
        runner.run(['kubectl', 'apply', '-f', '-'], input_text=json.dumps({'apiVersion':'v1', 'kind':'Namespace', 'metadata':{'name': name}}))
        address = 'kubernetes_namespace_v1.' + name
        if address not in tracked:
            runner.tf('terraform-k8s', 'import', '-input=false', address, name)
    details = journal.data['details']
    details.setdefault('restoredVolumes', {})
    for item in value['volumes']:
        original = item['volume']
        if original not in details['restoredVolumes']:
            restored = runner.aws('ec2', 'create-volume', '--snapshot-id', details['ebsSnapshots'][original],
                '--availability-zone', item['az'], '--volume-type', 'gp3', '--encrypted',
                '--client-token', value['session'] + '-' + original,
                '--tag-specifications', json.dumps([{'ResourceType':'volume','Tags':[
                    {'Key':'Project','Value':'sol-test3'}, {'Key':'RecoverySession','Value':value['session']},
                    {'Key':'ebs.csi.aws.com/cluster','Value':'true'}]}]))
            details['restoredVolumes'][original] = restored['VolumeId']
            journal.save()
        volume_id = details['restoredVolumes'][original]
        runner.run(['aws','ec2','wait','volume-available','--volume-ids',volume_id,'--region',CONFIG['region'],'--profile',CONFIG['profile']],timeout=900)
        pv_spec = copy.deepcopy(item['pvSpec'])
        pv_spec.pop('claimRef', None)
        pv_spec['persistentVolumeReclaimPolicy'] = 'Delete'
        pv_spec['csi']['volumeHandle'] = volume_id
        pv_spec['claimRef'] = {'namespace':'monitoring', 'name':item['pvc']}
        pv_name = 'sol-test3-restore-' + volume_id
        pvc_spec = copy.deepcopy(item['pvcSpec'])
        pvc_spec['volumeName'] = pv_name
        objects = [{'apiVersion':'v1','kind':'PersistentVolume','metadata':{'name':pv_name},'spec':pv_spec},
                   {'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':item['pvc'],'namespace':'monitoring',
                    'labels':item['labels']},'spec':pvc_spec}]
        runner.run(['kubectl','apply','-f','-'],input_text=json.dumps({'apiVersion':'v1','kind':'List','items':objects}))
    for key, data in value['secrets'].items():
        namespace, name = key.split('/')
        if name == 'my-app-secrets':
            continue  # Restored through Terraform's write-only attributes, with the NEW RDS endpoint.
        if namespace == 'monitoring':
            name = 'monitoring-grafana-restored'
        runner.run(['kubectl','apply','-f','-'],input_text=json.dumps({'apiVersion':'v1','kind':'Secret',
                    'metadata':{'namespace':namespace,'name':name},'type':'Opaque','data':data}))


def resume(runner, settings, journal, approved):
    from lab_install import wait_alb, ensure_ses
    details = journal.data['details']
    if not details.get('preserved'):
        raise ValueError('Preserve must finish before Resume')
    value = validate_backup(protected_backup.load(BACKUP))
    # Refuse another PC/config/DB snapshot silently becoming the restore source.
    check_identity(runner)
    ensure_ses(runner, settings)
    variables = infra_variables(settings, public_ip())
    variables['db_snapshot_identifier'] = details['dbSnapshot']
    journal.stage('restore-infra', lambda: apply_plan(runner, 'terraform', 'restore-infra', variables, approved=approved, directory=FOLDER))
    runner.run([sys.executable, 'scripts/ops/nat_failover.py', '--wait-ready'])
    live = connect(runner, FOLDER)
    if live['resourcesVpcConfig']['vpcId'] != value['vpc']:
        raise ValueError('Recovery must use the retained VPC')
    for field, env in [('JWT_SECRET','jwt_secret'),('JWT_REFRESH_SECRET','jwt_refresh_secret'),('INTERNAL_SERVICE_TOKEN','internal_service_token')]:
        runner.env['TF_VAR_' + env] = base64.b64decode(value['secrets']['soldesk/my-app-secrets'][field]).decode()
    runner.env['TF_VAR_github_repository_public'] = 'true'
    runner.tf('terraform-k8s', 'init', '-input=false', '-no-color')
    journal.stage('restore-volumes', lambda: restore_monitoring(runner, journal, value))
    kvars = k8s_variables(value['revision'], active=False)
    grafana = next(v['pvc'] for v in value['volumes'] if v['pvc'] == 'monitoring-grafana')
    kvars.update(grafana_existing_claim=grafana, grafana_existing_secret='monitoring-grafana-restored')
    # Write the chosen restore parameters locally so later promotion keeps the same claims.
    save_json(ROOT / '.lab/recovery-inputs.json', {'db_snapshot_identifier':details['dbSnapshot'],
              'grafana_existing_claim':grafana,'grafana_existing_secret':'monitoring-grafana-restored'})
    journal.stage('restore-tools', lambda: apply_plan(runner,'terraform-k8s','restore-tools',kvars,approved=approved,directory=FOLDER))
    kvars.update(enable_app_sync=True, enable_management_ingress=True)
    journal.stage('restore-apps', lambda: apply_plan(runner,'terraform-k8s','restore-apps',kvars,approved=approved,directory=FOLDER))
    wait_alb(runner,FOLDER)
    variables.update(enable_website_dns=True,enable_management_dns=True,customer_email_enabled=True)
    journal.stage('restore-endpoints', lambda: apply_plan(runner,'terraform','restore-endpoints',variables,approved=approved,directory=FOLDER))
    runner.run([sys.executable,'scripts/ops/lab_verify.py','--revision',value['revision'],'--manifest-ref',value['revision'],
                '--report',str(FOLDER/'restore-verification.json')],timeout=1200)
    runner.run([sys.executable,'scripts/ops/run_private_verify.py','--revision',value['revision'],'--profile',CONFIG['profile'],
                '--report',str(FOLDER/'restore-private-verification.json')],timeout=1500)
    details['restored'] = True
    journal.save()
    # Bind the installer to the recreated cluster, retaining its approved release baseline.
    install = Journal(ROOT/'.lab/install-state.json','install')
    install.data['details']['vpc'] = value['vpc']
    install.save()
    print('RESTORED: infrastructure/service checks passed. Compare the pre-stop product/order IDs and saved monitoring data before declaring data recovery PASS.',flush=True)


def discard_snapshots(runner):
    """Called only by full Remove-Lab -DiscardData after EKS/DB destruction."""
    path = FOLDER / 'checkpoint.json'
    if not path.exists():
        return
    journal = Journal(path, 'recovery')
    details = journal.data['details']
    session = details.get('session')
    if not session:
        raise ValueError('Recovery ownership session missing; retain snapshots')
    if cluster(runner):
        raise ValueError('Do not discard recovery while the cluster still exists')
    ids = set(details.get('restoredVolumes', {}).values())
    volumes = runner.aws('ec2','describe-volumes','--filters','Name=tag:RecoverySession,Values='+session)['Volumes']
    for volume in volumes:
        if volume['VolumeId'] not in ids or volume['State'] != 'available' or volume.get('Attachments'):
            raise ValueError('Unidentified/attached recovery volume; retain it')
        runner.aws('ec2','delete-volume','--volume-id',volume['VolumeId'],empty=True)
    snapshots = runner.aws('ec2','describe-snapshots','--owner-ids',CONFIG['account'],
                           '--filters','Name=tag:RecoverySession,Values='+session)['Snapshots']
    owned = set(details.get('ebsSnapshots',{}).values())
    for snapshot in snapshots:
        if snapshot['SnapshotId'] not in owned:
            raise ValueError('Unrecorded recovery snapshot; retain it')
        runner.aws('ec2','delete-snapshot','--snapshot-id',snapshot['SnapshotId'],empty=True)
    dbs = runner.aws('rds','describe-db-snapshots','--db-instance-identifier',CONFIG['database'])['DBSnapshots']
    for snapshot in dbs:
        if snapshot['DBSnapshotIdentifier'] != details.get('dbSnapshot'):
            continue
        tags = runner.aws('rds','list-tags-for-resource','--resource-name',snapshot['DBSnapshotArn'])['TagList']
        if {t['Key']:t['Value'] for t in tags}.get('RecoverySession') != session:
            raise ValueError('RDS recovery snapshot ownership mismatch')
        runner.aws('rds','delete-db-snapshot','--db-snapshot-identifier',snapshot['DBSnapshotIdentifier'])
        runner.run(['aws','rds','wait','db-snapshot-deleted','--db-snapshot-identifier',snapshot['DBSnapshotIdentifier'],
                    '--region',CONFIG['region'],'--profile',CONFIG['profile']],timeout=1800)
    journal.data['closed']=True
    journal.save()
    inputs = ROOT/'.lab/recovery-inputs.json'
    if inputs.exists():
        inputs.unlink()
    print('DISCARDED: exact recorded recovery snapshots and orphan restore volumes.',flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['preserve','resume'])
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--approve-plans',action='store_true')
    parser.add_argument('--config',type=Path,default=ROOT/'.lab/lab-config.json')
    args=parser.parse_args()
    if not args.execute:
        print('PREVIEW ONLY: '+args.mode+'. No AWS queries/mutations. Same Windows account required; retained NAT/storage/snapshots cost money.')
        return
    FOLDER.mkdir(parents=True,exist_ok=True)
    runner=Runner()
    try:
        preflight(runner)
        settings=load_settings(args.config)
        journal=Journal(FOLDER/'checkpoint.json','recovery')
        confirm('Preserve/rebuild the lab with native snapshots (retain VPC/NAT/storage charges)?',args.approve_plans)
        (preserve if args.mode=='preserve' else resume)(runner,settings,journal,args.approve_plans)
    finally:
        clear_runtime_secrets(runner)


if __name__=='__main__':
    try:
        main()
    except (Exception,KeyboardInterrupt) as error:
        print('RECOVERY STOPPED: '+type(error).__name__+'. Keep .lab/recovery and retry after inspecting the stage; secrets are not printed.',file=sys.stderr)
        sys.exit(1)
