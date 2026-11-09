"""Staged teardown helper. Default preview; --execute AND --discard-data required.

Never destroys Terraform roots, the state bucket, or unidentified resources.
Run capture BEFORE deleting Kubernetes resources. A saved manifest records exact
PVC->EBS ownership, so an unrelated CSI volume is never selected for cleanup.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time

from verify_lab import CONFIG, aws, check, kube

REPOS = ('member-service', 'product-service', 'ordering-service', 'apigateway', 'frontend-service')
BUCKETS = (CONFIG['productImageBucket'], f"{CONFIG['project'].lower()}-cloudtrail-{CONFIG['account']}-{CONFIG['region']}",
           CONFIG['verifyBucket'])


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=660)
    if result.returncode:
        raise RuntimeError('command failed: ' + ' '.join(args[:2]) + '; inspect resource state before retry')
    return result.stdout


def identity(require_kubernetes=True):
    check(aws('sts', 'get-caller-identity')['Account'] == CONFIG['account'], 'wrong AWS account')
    if not require_kubernetes:
        return
    expected = f"arn:aws:eks:{CONFIG['region']}:{CONFIG['account']}:cluster/{CONFIG['cluster']}"
    check(command('kubectl', 'config', 'current-context').strip() == expected, 'wrong Kubernetes context')


def capture():
    cluster = aws('eks', 'describe-cluster', '--name', CONFIG['cluster'])['cluster']
    claims = kube('pvc', 'monitoring')['items']
    # Operator-created PVC labels differ from Helm's labels. Match actual mounted
    # claims in the three known monitoring workloads as additional ownership proof.
    mounted = set()
    for pod in kube('pods', 'monitoring')['items']:
        name = pod['metadata']['name']
        if name.startswith(('monitoring-grafana-', 'prometheus-monitoring-kube-prometheus-prometheus-',
                            'alertmanager-monitoring-kube-prometheus-alertmanager-')):
            mounted.update(v['persistentVolumeClaim']['claimName'] for v in pod['spec'].get('volumes', [])
                           if 'persistentVolumeClaim' in v)
    # An interrupted first install may not have created all three claims yet.
    # Every present claim still needs positive ownership + bound-volume proof.
    check(len(claims) <= 3, 'unexpected extra monitoring PVCs; investigate before teardown')
    volumes = []
    for claim in claims:
        labels = claim['metadata'].get('labels', {})
        name = claim['metadata']['name']
        check(name in mounted or labels.get('release') == 'monitoring' or labels.get('app.kubernetes.io/instance') == 'monitoring',
              'unidentified monitoring PVC: ' + name)
        check(bool(claim.get('spec', {}).get('volumeName')), 'PVC not bound yet; wait/investigate before capture: ' + name)
        pv = kube('pv/' + claim['spec']['volumeName'])
        check(pv['spec'].get('csi', {}).get('driver') == 'ebs.csi.aws.com', 'unexpected PV driver')
        check(pv['spec']['persistentVolumeReclaimPolicy'] == 'Delete', 'PV reclaim policy needs manual review')
        volumes.append({'pvc': name, 'pv': pv['metadata']['name'], 'volume': pv['spec']['csi']['volumeHandle']})
    vpc = cluster['resourcesVpcConfig']['vpcId']
    # Inventory only. Extra LBs are a review hold, not a cleanup target.
    lbs = [b for b in aws('elbv2', 'describe-load-balancers')['LoadBalancers'] if b.get('VpcId') == vpc]
    check(all(b['LoadBalancerName'] == CONFIG['loadBalancer'] for b in lbs), 'extra LB needs ownership review')
    classic = [b for b in aws('elb', 'describe-load-balancers')['LoadBalancerDescriptions'] if b.get('VPCId') == vpc]
    check(not classic, 'Classic LB needs ownership review')
    return {'account': CONFIG['account'], 'cluster': CONFIG['cluster'], 'vpc': vpc, 'volumes': volumes}


def leftovers(manifest):
    # Query entire lists then match exact IDs: query errors cannot look like NotFound.
    lbs = [b for b in aws('elbv2', 'describe-load-balancers')['LoadBalancers'] if b.get('VpcId') == manifest['vpc']]
    classic = [b for b in aws('elb', 'describe-load-balancers')['LoadBalancerDescriptions'] if b.get('VPCId') == manifest['vpc']]
    expected = {v['volume'] for v in manifest['volumes']}
    volumes = [v for v in aws('ec2', 'describe-volumes')['Volumes'] if v['VolumeId'] in expected]
    return bool(lbs or classic or volumes)


def wait_empty(manifest, timeout):
    deadline = time.monotonic() + timeout
    while leftovers(manifest):
        if time.monotonic() >= deadline:
            raise TimeoutError('ALB/EBS remain; keep controllers and EKS, inspect finalizers/events')
        print('WAIT: exact VPC load balancers or captured EBS remain')
        time.sleep(10)
    print('PASS: VPC load balancers and captured EBS absent')


def clear_bucket(bucket):
    check(bucket in BUCKETS, 'bucket is outside exact project data allowlist')
    # Explicitly exclude the protected Terraform state bucket.
    check('tfstate' not in bucket, 'state bucket cannot be emptied here')
    owner = ('--expected-bucket-owner', CONFIG['account'])
    for attempt in range(6):
        versions = aws('s3api', 'list-object-versions', '--bucket', bucket, *owner)
        objects = [{'Key': o['Key'], 'VersionId': o['VersionId']}
                   for o in versions.get('Versions', []) + versions.get('DeleteMarkers', [])]
        if not objects:
            current = aws('s3api', 'list-objects-v2', '--bucket', bucket, *owner)
            objects = [{'Key': o['Key']} for o in current.get('Contents', [])]
        if not objects:
            # CloudTrail can deliver delayed objects; a later BucketNotEmpty is retried through this same stage.
            return
        for start in range(0, len(objects), 1000):
            # Large version lists exceed the Windows command-line length limit.
            with tempfile.TemporaryDirectory(prefix='final-s3-delete-') as temporary:
                request_path = Path(temporary) / 'delete.json'
                request_path.write_text(json.dumps({'Objects': objects[start:start + 1000], 'Quiet': True}), encoding='utf-8')
                result = aws('s3api', 'delete-objects', '--bucket', bucket,
                             '--delete', 'file://' + str(request_path), *owner)
            check(not result.get('Errors'), 'S3 returned per-object deletion failures')
        time.sleep(5)
    raise TimeoutError('bucket is still receiving objects; inspect CloudTrail status, then retry storage stage')


def storage():
    trail = f"arn:aws:cloudtrail:{CONFIG['region']}:{CONFIG['account']}:trail/{CONFIG['project']}-management-trail"
    # Exact trail ARN is also checked against Terraform output by the guide before execution.
    trails = aws('cloudtrail', 'describe-trails')['trailList']
    if any(t['TrailARN'] == trail for t in trails):
        aws('cloudtrail', 'stop-logging', '--name', trail)
        check(not aws('cloudtrail', 'get-trail-status', '--name', trail)['IsLogging'], 'CloudTrail logging still enabled')
    existing_buckets = {b['Name'] for b in aws('s3api', 'list-buckets')['Buckets']}
    for bucket in BUCKETS:
        if bucket in existing_buckets:
            clear_bucket(bucket)
    existing_repos = {r['repositoryName'] for r in aws('ecr', 'describe-repositories')['repositories']}
    for repo in REPOS:
        if repo not in existing_repos:
            continue
        images = aws('ecr', 'list-images', '--repository-name', repo)['imageIds']
        # Digests, not mutable tags. Deduplicate entries for images with multiple tags.
        digests = sorted({i['imageDigest'] for i in images})
        for start in range(0, len(digests), 100):
            result = aws('ecr', 'batch-delete-image', '--repository-name', repo,
                         '--image-ids', json.dumps([{'imageDigest': d} for d in digests[start:start + 100]]))
            check(not result.get('failures'), 'ECR image deletion returned failures')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('stage', choices=['capture', 'workloads', 'monitoring', 'wait', 'storage'])
    p.add_argument('--manifest', type=Path, default=Path('.lab/destroy-manifest.json'))
    p.add_argument('--execute', action='store_true')
    p.add_argument('--discard-data', action='store_true')
    p.add_argument('--timeout', type=int, default=600)
    args = p.parse_args()
    if args.stage not in ('capture', 'wait') and not (args.execute and args.discard_data):
        print('PREVIEW ONLY: ' + args.stage + '. Explicit --execute --discard-data required. See docs/14-second-build.md.')
        return
    identity(require_kubernetes=args.stage not in ('wait', 'storage'))
    if args.stage == 'capture':
        data = capture()
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        check(not args.manifest.exists(), 'manifest already exists; preserve original captured EBS IDs')
        args.manifest.write_text(json.dumps(data, indent=2), encoding='utf-8')
        print('CAPTURED: exact VPC and monitoring EBS IDs; no resource changed')
        return
    data = json.loads(args.manifest.read_text(encoding='utf-8'))
    check(data['account'] == CONFIG['account'] and data['cluster'] == CONFIG['cluster'], 'manifest identity mismatch')
    clusters = aws('eks', 'list-clusters')['clusters']
    if CONFIG['cluster'] in clusters:
        live = aws('eks', 'describe-cluster', '--name', CONFIG['cluster'])['cluster']
        check(live['resourcesVpcConfig']['vpcId'] == data['vpc'], 'manifest belongs to a different build')
    else:
        check(args.stage in ('wait', 'storage'), 'EKS already absent; cannot change Kubernetes resources')
    if args.stage == 'workloads':
        # Remove auto-sync before deleting the Application; Argo stays alive to process finalizers.
        app = command('kubectl', 'get', 'application', 'final-apps', '-n', 'argocd', '--ignore-not-found', '-o', 'name')
        if app.strip():
            command('kubectl', 'patch', 'application', 'final-apps', '-n', 'argocd', '--type=merge',
                    '-p', json.dumps({'spec': {'syncPolicy': {'automated': {'enabled': False}}}}))
        command('kubectl', 'delete', 'application', 'final-apps', '-n', 'argocd', '--ignore-not-found', '--wait=true', '--timeout=600s')
        command('kubectl', 'delete', 'ingress', 'argocd-public', '-n', 'argocd', '--ignore-not-found', '--wait=true', '--timeout=300s')
        command('kubectl', 'delete', 'ingress', 'grafana-public', '-n', 'monitoring', '--ignore-not-found', '--wait=true', '--timeout=300s')
    elif args.stage == 'monitoring':
        check(not kube('application', 'argocd')['items'], 'Application must be removed before monitoring')
        # Operator must still exist while its CRs delete their StatefulSets/Pods.
        command('kubectl', 'delete', 'prometheus,alertmanager', '-n', 'monitoring', '-l', 'release=monitoring',
                '--ignore-not-found', '--cascade=foreground', '--wait=true', '--timeout=300s')
        releases = json.loads(command('helm', 'list', '-n', 'monitoring', '--all', '-o', 'json'))
        if any(r['name'] == 'monitoring' for r in releases):
            command('helm', 'uninstall', 'monitoring', '-n', 'monitoring', '--wait', '--timeout', '5m')
        for volume in data['volumes']:
            command('kubectl', 'delete', 'pvc', volume['pvc'], '-n', 'monitoring', '--ignore-not-found', '--wait=true', '--timeout=300s')
    elif args.stage == 'wait':
        wait_empty(data, args.timeout)
    elif args.stage == 'storage':
        check(not leftovers(data), 'ALB/EBS must be absent before clearing data stores')
        storage()
    print('DONE: ' + args.stage + '; continue only after reviewing the result')


if __name__ == '__main__':
    main()
