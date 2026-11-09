"""Read-only deployment gates, plus separately authorized rotation/CPU tests."""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

from lab_common import (APP_NAMES, CONFIG, ROOT, Journal, Runner, cluster, connect, ensure_revision,
                        load_settings, now, preflight, save_json, wait_alb)


def credential_ready(runner, *, after=None, timeout=360, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    while True:
        jobs = runner.kube('get', 'jobs', '-n', CONFIG['namespace'])['items']
        candidates = [j for j in jobs if j['metadata']['name'].startswith('db-credential-sync-')]
        candidates.sort(key=lambda j: j['metadata']['creationTimestamp'])
        successes = [j for j in candidates if j.get('status', {}).get('succeeded', 0) >= 1
                     and (not after or datetime.fromisoformat(j['metadata']['creationTimestamp'].replace('Z', '+00:00')) >= after)]
        if successes:
            latest = successes[-1]
            completed = latest.get('status', {}).get('completionTime', latest['metadata']['creationTimestamp'])
            recent = (datetime.now(timezone.utc) - datetime.fromisoformat(completed.replace('Z', '+00:00'))).total_seconds() <= 240
            newer_failure = any(j.get('status', {}).get('failed', 0) and
                                j['metadata']['creationTimestamp'] > latest['metadata']['creationTimestamp'] for j in candidates)
            if recent and not newer_failure:
                text = runner.run(['kubectl', 'logs', 'job/' + latest['metadata']['name'], '-n', CONFIG['namespace'], '--tail=40'])
                expected = ['READY: ' + name for name in APP_NAMES] + ['PASS: DB credential propagation and DB-readiness completed']
                if all(line in text for line in expected):
                    print('PASS: recent credential Job / all three DB-ready services', flush=True)
                    return latest['metadata']['name']
        if clock() >= deadline:
            raise TimeoutError('No recent successful credential Job; inspect latest Job logs (historical failed Jobs are preserved)')
        print('WAIT: latest credential propagation / DB-readiness', flush=True)
        sleep(10)


def expected_revision(runner, explicit=None):
    if explicit:
        return ensure_revision(explicit)
    application = runner.kube('get', 'application', 'final-apps', '-n', 'argocd')
    target = application['spec']['source']['targetRevision']
    if target != 'main':
        return ensure_revision(target)
    result = runner.run(['git', 'ls-remote', 'https://github.com/' + CONFIG['repository'] + '.git', 'refs/heads/main']).split()
    return ensure_revision(result[0])


def basic(runner, settings, revision, manifest_ref, directory):
    evidence = {}
    for phase in ('infra', 'tools', 'load-balancers'):
        path = directory / (phase + '.json')
        if phase == 'load-balancers':
            result = wait_alb(runner, directory, timeout=300, report_name=path.name)
        else:
            runner.run([sys.executable, 'scripts/ops/verify_lab.py', phase, '--report', str(path)])
            result = json.loads(path.read_text(encoding='utf-8'))
        if result.get('status') != 'PASS':
            raise ValueError('Failed phase: ' + phase)
        evidence[phase] = result['details']
        print('PASS: ' + phase, flush=True)
    runner.run([sys.executable, 'scripts/ops/check_release.py', '--revision', revision,
                '--manifest-ref', manifest_ref, '--timeout', '600'], timeout=720)
    evidence['release'] = {'revision': revision, 'checks': ['images', 'availability', 'HTTPS', 'HTML', 'product API']}
    evidence['credentialJob'] = credential_ready(runner)
    for service in APP_NAMES:
        deployment = runner.kube('get', 'deployment', service, '-n', CONFIG['namespace'])
        spec, status = deployment['spec'], deployment.get('status', {})
        desired = spec.get('replicas', 1)
        if status.get('availableReplicas', 0) < desired or status.get('updatedReplicas', 0) != desired:
            raise ValueError('Deployment not fully ready: ' + service)
    maps = runner.aws('lambda', 'list-event-source-mappings', '--function-name', 'sol-test3-order-email')['EventSourceMappings']
    relevant = [m for m in maps if m.get('EventSourceArn', '').endswith(':sol-test3-order-notifications')]
    if len(relevant) != 1 or relevant[0]['State'] != 'Enabled':
        raise ValueError('Order email SQS consumer not Enabled')
    function = runner.aws('lambda', 'get-function-configuration', '--function-name', 'sol-test3-order-email')
    variables = function.get('Environment', {}).get('Variables', {})
    if variables.get('SENDER_EMAIL') != settings['senderEmail'] or variables.get('ADMIN_EMAIL') != settings['adminEmail']:
        raise ValueError('Lambda sender/admin email differs from the local installation settings')
    for address in {settings['senderEmail'], settings['adminEmail'], settings['testRecipientEmail']}:
        if not runner.aws('sesv2', 'get-email-identity', '--email-identity', address).get('VerifiedForSendingStatus'):
            raise ValueError('SES identity not verified')
    admin = runner.kube('get', 'secret', 'final-admin-config', '-n', CONFIG['namespace'])
    if base64.b64decode(admin.get('data', {}).get('admin-email', '')).decode() != settings['adminEmail']:
        raise ValueError('Administrator Secret email differs from notification settings')
    evidence['mailConfiguration'] = 'consumer Enabled; sender/admin/buyer verified; addresses consistent'
    evidence['manualChecks'] = ['Confirm SNS subscription email', 'Buyer order email AND administrator new-order email',
                                'Member/Product/Ordering data survives replacement',
                                'No claim of exactly-once SES delivery or full network/security audit']
    return evidence


def current_version(runner, secret_arn):
    versions = runner.aws('secretsmanager', 'list-secret-version-ids', '--secret-id', secret_arn)['Versions']
    current = [v['VersionId'] for v in versions if 'AWSCURRENT' in v.get('VersionStages', [])]
    if len(current) != 1:
        raise ValueError('Expected one AWSCURRENT secret version')
    return current[0]


def service_uids(runner, *, allow_unready=False):
    pods = runner.kube('get', 'pods', '-n', CONFIG['namespace'], '-l', 'app in (member,product,ordering)')['items']
    result = {}
    for app in ('member', 'product', 'ordering'):
        result[app] = [p['metadata']['uid'] for p in pods if p['metadata'].get('labels', {}).get('app') == app
                       and any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in p.get('status', {}).get('conditions', []))]
        if not result[app] and not allow_unready:
            raise ValueError('No ready Pod for ' + app)
    return result


def wait_rotated_services(runner, before, *, timeout=900, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    while True:
        after = service_uids(runner, allow_unready=True)
        if all(after[app] and not set(after[app]) & set(before[app]) for app in before):
            return after
        if clock() >= deadline:
            raise TimeoutError('Automatic credential replacement did not finish; resume the same rotation checkpoint')
        print('WAIT: all three credential rollouts / old Pod termination', flush=True)
        sleep(min(10, deadline - clock()))


def rotate(runner, directory, *, timeout=1200, clock=time.monotonic, sleep=time.sleep):
    path = ROOT / '.lab/rotation-state.json'
    journal = Journal(path, 'rotation')
    details = journal.data['details']
    if journal.data.get('closed'):
        save_json(directory / ('rotation-previous-' + str(int(time.time())) + '.json'), journal.data)
        path.unlink()
        journal = Journal(path, 'rotation')
        details = journal.data['details']
    if not details:
        db = runner.aws('rds', 'describe-db-instances', '--db-instance-identifier', CONFIG['database'])['DBInstances'][0]
        if db['DBInstanceStatus'] != 'available' or db.get('PendingModifiedValues') or db.get('MasterUserSecret', {}).get('SecretStatus') != 'active':
            raise ValueError('RDS must be available with active managed Secret and no pending modifications')
        details.update(secretArn=db['MasterUserSecret']['SecretArn'], beforeVersion=current_version(runner, db['MasterUserSecret']['SecretArn']),
                       beforePods=service_uids(runner), startedAt=now(), requestRecorded=True)
        journal.save()  # A retry must NEVER blindly rotate the password again.
        runner.aws('rds', 'modify-db-instance', '--db-instance-identifier', CONFIG['database'],
                   '--rotate-master-user-password', '--apply-immediately')
        details['requestAccepted'] = True
        journal.save()
    elif not details.get('requestAccepted'):
        raise ValueError('Previous rotation request outcome is uncertain; inspect RDS/Secret versions before starting another request')
    deadline = clock() + timeout
    while True:
        db = runner.aws('rds', 'describe-db-instances', '--db-instance-identifier', CONFIG['database'])['DBInstances'][0]
        version = current_version(runner, details['secretArn'])
        if db['DBInstanceStatus'] == 'available' and db.get('MasterUserSecret', {}).get('SecretStatus') == 'active' and version != details['beforeVersion']:
            break
        if clock() >= deadline:
            raise TimeoutError('RDS rotation not complete; same command resumes observation without a second rotation request')
        print('WAIT: RDS managed password rotation', flush=True)
        sleep(15)
    after = wait_rotated_services(runner, details['beforePods'], timeout=max(0, deadline - clock()),
                                  clock=clock, sleep=sleep)
    # A Job during the RDS rotation may have validated the OLD Secret. Require
    # another complete DB-readiness pass started after replacement was observed.
    details.setdefault('replacementObservedAt', now())
    journal.save()
    job = credential_ready(runner, after=datetime.fromisoformat(details['replacementObservedAt']), timeout=900)
    details.update(afterVersion=version, afterPods=after, successfulJob=job, completedAt=now())
    journal.data['status'] = 'rotation-complete-awaiting-service-verification'
    journal.save()
    return {'versionChanged': True, 'allThreeServicesReplaced': True, 'successfulJob': job}


def hpa_cpu_percent(hpa, *, current=False):
    """Read equivalent CPU utilization fields from Kubernetes v1/v2 responses."""
    section = hpa.get('status' if current else 'spec', {})
    legacy = 'currentCPUUtilizationPercentage' if current else 'targetCPUUtilizationPercentage'
    if legacy in section:
        return section[legacy]
    metrics = section.get('currentMetrics' if current else 'metrics', [])
    if len(metrics) != 1 or metrics[0].get('type') != 'Resource':
        return None
    resource = metrics[0].get('resource', {})
    if resource.get('name') != 'cpu':
        return None
    value = resource.get('current' if current else 'target', {})
    if not current and value.get('type') != 'Utilization':
        return None
    return value.get('averageUtilization')


def scale(runner, *, timeout=900, clock=time.monotonic, sleep=time.sleep, popen=subprocess.Popen):
    hpa = runner.kube('get', 'hpa', 'member-hpa', '-n', 'soldesk')
    if hpa['spec'].get('minReplicas') != 1 or hpa['spec'].get('maxReplicas') != 3 or hpa_cpu_percent(hpa) != 60:
        raise ValueError('Unexpected HPA bounds; refuse to alter/test an unknown configuration')
    if hpa.get('status', {}).get('currentReplicas') != 1:
        raise ValueError('Wait until the member HPA is at its normal one-replica baseline')
    pods = runner.kube('get', 'pods', '-n', 'soldesk', '-l', 'app=member')['items']
    ready = [p for p in pods if any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in p.get('status', {}).get('conditions', []))]
    if not ready:
        raise ValueError('No ready member Pod')
    pod = ready[0]['metadata']['name']
    command = ['kubectl', 'exec', '-n', 'soldesk', pod, '--', 'timeout', '180', 'sha256sum', '/dev/zero']
    child = popen(command, cwd=runner.root, env=runner.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    observations, expanded = [], False
    deadline = clock() + timeout
    try:
        while clock() < deadline:
            hpa = runner.kube('get', 'hpa', 'member-hpa', '-n', 'soldesk')
            deployment = runner.kube('get', 'deployment', 'member-depl', '-n', 'soldesk')
            nodes = len(runner.kube('get', 'nodes')['items'])
            count = hpa.get('status', {}).get('currentReplicas', 0)
            available = deployment.get('status', {}).get('availableReplicas', 0)
            observations.append({'at': now(), 'replicas': count, 'available': available, 'nodes': nodes,
                                 'cpuPercent': hpa_cpu_percent(hpa, current=True)})
            print(f'HPA: replicas={count}, available={available}, nodes={nodes}', flush=True)
            expanded = expanded or (count >= 2 and available >= count)
            if child.poll() is not None and child.returncode not in (0, 124, 137, 143):
                raise ValueError('CPU load command failed; HPA result is not valid')
            if expanded and child.poll() is not None and count == 1 and available == 1:
                return {'syntheticCpuTest': True, 'expandedAndContracted': True, 'observations': observations,
                        'nodeAutoscaling': 'node count alone does not prove CA cause; inspect CA events/logs'}
            sleep(15)
        raise TimeoutError('HPA expansion/contraction not proven before timeout; remote CPU command is bounded to 180 seconds')
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=20)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['basic', 'rotation', 'scaling'], default='basic')
    parser.add_argument('--allow-impact', action='store_true')
    parser.add_argument('--revision')
    parser.add_argument('--manifest-ref')
    parser.add_argument('--config', type=Path, default=ROOT / '.lab/lab-config.json')
    parser.add_argument('--report', type=Path, default=ROOT / '.lab/runtime/verification.json')
    args = parser.parse_args()
    report = {'schema': 1, 'mode': args.mode, 'startedAt': now(), 'status': 'FAIL'}
    directory = args.report.resolve().parent
    directory.mkdir(parents=True, exist_ok=True)
    try:
        if args.mode != 'basic' and not args.allow_impact:
            raise ValueError('Rotation/scaling can disrupt service or add node costs; explicit -AllowImpact is required')
        runner = Runner()
        preflight(runner, github=False)
        settings = load_settings(args.config)
        connect(runner, directory)  # Basic mode NEVER changes the EKS access configuration.
        revision = expected_revision(runner, args.revision)
        manifest = ensure_revision(args.manifest_ref or revision)
        runner.run(['git', 'fetch', 'origin', manifest])
        if args.mode == 'rotation':
            report['rotation'] = rotate(runner, directory)
        if args.mode == 'scaling':
            report['scaling'] = scale(runner)
        report['checks'] = basic(runner, settings, revision, manifest, directory)
        if args.mode == 'rotation':
            finished = Journal(ROOT / '.lab/rotation-state.json', 'rotation')
            finished.data['closed'] = True
            finished.save()
        report['status'] = 'PASS'
    except Exception as error:
        report['errorType'] = type(error).__name__
        report['reason'] = str(error)
        raise
    finally:
        report['finishedAt'] = now()
        save_json(args.report, report)
    print('PASS: ' + args.mode + '; evidence: ' + str(args.report), flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('STOPPED: remote scaling load is bounded; rotation checkpoint is preserved.', file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print('FAIL: ' + str(error), file=sys.stderr)
        sys.exit(1)
