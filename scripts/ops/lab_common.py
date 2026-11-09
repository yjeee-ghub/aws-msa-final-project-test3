"""Shared, fail-closed machinery for the PowerShell lab entry points.

No AWS operation runs on import. Secrets stay in memory/process environments;
checkpoints store names, version IDs and completed stages, never secret values.
"""
import base64
import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((Path(__file__).with_name('environment.json')).read_text(encoding='utf-8'))
STATE_BUCKET = CONFIG['stateBucket']
STATE_KEYS = {root: f"{CONFIG['project']}/{state}/terraform.tfstate"
              for root, state in (('terraform', 'infra'), ('terraform-k8s', 'k8s'))}
APP_NAMES = ('member-depl', 'product-depl', 'ordering-depl')
EMAIL = re.compile(r'^[A-Za-z0-9.!#$%&*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')


def now():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)


class CommandError(RuntimeError):
    def __init__(self, args, result):
        self.args_run = list(args)
        self.returncode = result.returncode
        self.stderr = result.stderr or ''
        self.stdout = result.stdout or ''
        match = re.search(r'An error occurred \(([A-Za-z0-9_.-]+)\)', self.stderr)
        self.aws_code = match[1] if match else None
        # No raw stderr: Kubernetes/SDK errors can echo a Secret request body.
        super().__init__(f"{Path(str(args[0])).name} {args[1] if len(args)>1 else ''} failed: exit {result.returncode}" +
                         (f' ({self.aws_code})' if self.aws_code else ''))


class Runner:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.env = dict(os.environ, AWS_PAGER='', PYTHONUTF8='1', TF_IN_AUTOMATION='1', TF_INPUT='0')
        # Do not inherit a user's implicit -target/-auto-approve/provider profile override.
        for key in list(self.env):
            if key.startswith(('TF_CLI_ARGS', 'TF_VAR_')):
                del self.env[key]

    def run(self, args, *, input_text=None, timeout=1800):
        result = subprocess.run([str(a) for a in args], cwd=self.root, env=self.env,
                                input=input_text, capture_output=True, encoding='utf-8', timeout=timeout)
        if result.returncode:
            raise CommandError(args, result)
        return result.stdout.strip()

    def json(self, args, **kwargs):
        text = self.run(args, **kwargs)
        if not text:
            raise ValueError('Expected JSON response: ' + ' '.join(map(str, args[:2])))
        return json.loads(text)

    def aws(self, service, operation, *args, empty=False):
        command = ['aws', service, operation, *args, '--profile', CONFIG['profile'],
                   '--region', CONFIG['region'], '--output', 'json', '--no-cli-pager']
        text = self.run(command, timeout=120)
        if not text and empty:
            return {}
        return json.loads(text)

    def kube(self, *args):
        return self.json(['kubectl', *args, '--request-timeout=30s', '-o', 'json'], timeout=90)

    def tf(self, root, *args):
        # One argument for -chdir/-out: never cmd /c, shell=True or command strings.
        return self.run(['terraform', '-chdir=' + str(root), *args], timeout=3600)


class Journal:
    def __init__(self, path, kind, source=None):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {
            'schema': 1, 'kind': kind, 'account': CONFIG['account'], 'startedAt': now(),
            'completed': [], 'source': source, 'details': {}, 'closed': False}
        if self.data.get('schema') != 1 or self.data.get('kind') != kind or self.data.get('account') != CONFIG['account']:
            raise ValueError('Checkpoint identity mismatch; preserve it and investigate')

    def save(self):
        self.data['updatedAt'] = now()
        save_json(self.path, self.data)

    def stage(self, name, action, *, always=False):
        if not always and name in self.data['completed']:
            print('RESUME: already completed ' + name, flush=True)
            return
        self.data['currentStage'] = name
        self.data['status'] = 'running'
        self.save()
        print('\nSTAGE: ' + name, flush=True)
        try:
            action()
        except Exception as error:
            self.data['status'] = 'failed'
            self.data['errorType'] = type(error).__name__
            self.save()
            raise
        if name not in self.data['completed']:
            self.data['completed'].append(name)
        self.data['status'] = 'ready'
        self.data.pop('errorType', None)
        self.save()


def check_identity(runner):
    identity = runner.aws('sts', 'get-caller-identity')
    if identity.get('Account') != CONFIG['account']:
        raise ValueError('Wrong AWS account; nothing may be changed')
    return identity


def confirm(prompt, approved=False):
    if not approved and input(prompt + ' [yes/no]: ').strip().lower() != 'yes':
        raise RuntimeError('Stopped before mutation; rerun the same command to resume')


def preflight(runner, *, github=True):
    from check_environment import check
    check(runner.root)
    if sys.version_info < (3, 12):
        raise ValueError('Python 3.12+ is required')
    tools = ['aws', 'terraform', 'kubectl', 'helm', 'git'] + (['gh'] if github else [])
    for tool in tools:
        if not shutil.which(tool, path=runner.env.get('PATH')):
            raise ValueError('Install/add to PATH first: ' + tool)
    version = runner.json(['terraform', 'version', '-json'])['terraform_version']
    if not (tuple(map(int, version.split('.')[:2])) >= (1, 12) and version.split('.')[0] == '1'):
        raise ValueError('Terraform >=1.12,<2 required; tested with 1.16.2')
    helm = runner.run(['helm', 'version', '--short'])
    if not helm.startswith('v3.'):
        raise ValueError('Use Helm 3 (tested: 3.19.0); Helm 4 has incompatible CLI flags')
    client = runner.json(['kubectl', 'version', '--client', '-o', 'json'])['clientVersion']
    minor = int(re.sub(r'[^0-9]', '', client['minor']))
    if client['major'] != '1' or minor not in (34, 35, 36):
        raise ValueError('EKS 1.35 requires kubectl 1.34..1.36; use 1.35.x')
    runner.run([sys.executable, '-c', 'import yaml'])
    check_identity(runner)
    if github:
        repo = runner.json(['gh', 'api', 'repos/' + CONFIG['repository']])
        if repo.get('full_name', '').lower() != CONFIG['repository'].lower() or not repo.get('permissions', {}).get('push'):
            raise ValueError('GitHub repository write access is required')


def valid_settings(settings):
    if settings.get('account') != CONFIG['account'] or settings.get('schema') != 1:
        raise ValueError('Unsupported config/account')
    if not re.fullmatch(r'arn:aws:iam::' + CONFIG['account'] + r':(user|role)/[A-Za-z0-9+=,.@_/-]+', settings.get('adminArn', '')):
        raise ValueError('Use the IAM user/role ARN, not an STS assumed-role ARN')
    for key in ('alertEmail', 'senderEmail', 'testRecipientEmail', 'adminEmail'):
        if not EMAIL.fullmatch(settings.get(key, '')):
            raise ValueError('Invalid email setting: ' + key)
    return settings


def load_settings(path, *, create=False, identity=None):
    path = Path(path)
    if path.exists():
        return valid_settings(json.loads(path.read_text(encoding='utf-8-sig')))
    if not create:
        raise ValueError('Missing local config: run Install-Lab.ps1 first')
    arn = (identity or {}).get('Arn', '')
    if ':iam::' not in arn:
        arn = input('EKS administrator IAM user/role ARN: ').strip()
    settings = {'schema': 1, 'account': CONFIG['account'], 'adminArn': arn,
                'alertEmail': input('Operations alert email: ').strip(),
                'senderEmail': input('SES sender email: ').strip(),
                'testRecipientEmail': input('SES verified buyer test email: ').strip(),
                'adminEmail': input('Administrator account / new order notification email: ').strip()}
    valid_settings(settings)
    save_json(path, settings)
    print('Saved local non-secret settings. Passwords/tokens are not in this file.', flush=True)
    return settings


def public_ip():
    import urllib.request
    with urllib.request.urlopen('https://checkip.amazonaws.com', timeout=15) as response:
        value = response.read(100).decode().strip()
    address = ipaddress.ip_address(value)
    if address.version != 4:
        raise ValueError('Expected public IPv4 address')
    return value + '/32'


def infra_variables(settings, cidr, *, dns=False, mail=False):
    valid_settings(settings)
    recovery = recovery_inputs()
    return {**{k:v for k,v in recovery.items() if k == 'db_snapshot_identifier'}, 'eks_admin_principal_arn': settings['adminArn'], 'eks_public_access_cidrs': [cidr],
            'eks_node_instance_types': ['t3.medium'], 'keep_legacy_node_group': False,
            'alert_email': settings['alertEmail'], 'manage_db_password': True,
            'customer_email_sender': settings['senderEmail'], 'customer_email_admin': settings['adminEmail'],
            'customer_email_test_recipients': list(dict.fromkeys([settings['testRecipientEmail'], settings['adminEmail']])),
            'manage_ses_identities': False, 'customer_email_enabled': mail,
            'enable_website_dns': dns, 'enable_management_dns': dns}


def recovery_inputs():
    path = ROOT / '.lab/recovery-inputs.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def k8s_variables(revision='main', *, active=False):
    return {'aws_profile': CONFIG['profile'], 'aws_region': CONFIG['region'], 'cluster_name': CONFIG['cluster'],
            **{k:v for k,v in recovery_inputs().items() if k.startswith('grafana_existing_')}, 'github_repo_url': 'https://github.com/' + CONFIG['repository'] + '.git',
            'github_repository_public': True, 'github_revision': revision,
            'enable_app_sync': active, 'enable_management_ingress': active}


def check_plan(plan, *, destroy=False):
    changes = [c for c in plan.get('resource_changes', []) if c.get('mode', 'managed') == 'managed'
               and c['change']['actions'] != ['no-op']]
    for change in changes:
        actions = change['change']['actions']
        if destroy and actions != ['delete']:
            raise ValueError('Destroy must not create/update anything: ' + change['address'])
        if not destroy and 'delete' in actions and change['type'] != 'terraform_data':
            raise ValueError('Unexpected deletion/replacement; review manually: ' + change['address'])
    return changes


def apply_plan(runner, root, label, variables=None, *, destroy=False, approved=False, directory=None):
    directory = Path(directory or runner.root / '.lab/runtime').resolve()
    directory.mkdir(parents=True, exist_ok=True)
    args = ['plan', '-input=false', '-no-color']
    if destroy:
        args.append('-destroy')
    if variables is not None:
        varfile = directory / (label + '.tfvars.json')
        save_json(varfile, variables)
        args.append('-var-file=' + str(varfile))
    path = directory / (label + '.tfplan')
    text = runner.tf(root, *args, '-out=' + str(path))
    (directory / (label + '-plan.txt')).write_text(text, encoding='utf-8')
    plan = json.loads(runner.tf(root, 'show', '-json', str(path)))
    changes = check_plan(plan, destroy=destroy)
    print(f'PLAN {label}: {len(changes)} resource changes; {directory / (label + "-plan.txt")}', flush=True)
    for item in changes:
        print('  ' + ','.join(item['change']['actions']) + ': ' + item['address'], flush=True)
    if not changes:
        return
    confirm('Apply this reviewed ' + label + ' plan?', approved)
    # The saved plan is always regenerated; never reuse yesterday's plan on resume.
    output = runner.tf(root, 'apply', '-input=false', '-no-color', str(path))
    (directory / (label + '-apply.txt')).write_text(output, encoding='utf-8')
    print('APPLIED: ' + label, flush=True)


def state(runner, root):
    return json.loads(runner.tf(root, 'state', 'pull'))


def wait_alb(runner, directory, *, timeout=600, report_name='alb-check.json',
             clock=time.monotonic, sleep=time.sleep):
    """Retry fresh, explicitly pending reports; never hide query/ownership errors."""
    path = Path(directory) / report_name
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = clock() + timeout
    while True:
        # A previous pending report must not authorize retry after a crashed query.
        path.unlink(missing_ok=True)
        failure = None
        try:
            runner.run([sys.executable, 'scripts/ops/verify_lab.py', 'load-balancers', '--report', str(path)],
                       timeout=max(1, min(180, deadline - clock())))
        except CommandError as error:
            failure = error
        if not path.exists():
            if failure:
                raise failure
            raise ValueError('ALB verifier did not produce a fresh report')
        result = json.loads(path.read_text(encoding='utf-8'))
        if result.get('phase') != 'load-balancers':
            raise ValueError('Unexpected ALB verifier report')
        if not failure and result.get('status') == 'PASS':
            return result
        if (not failure or failure.returncode != 1 or result.get('status') != 'FAIL'
                or result.get('retryable') is not True):
            if failure:
                raise failure
            raise ValueError('ALB verifier failed without a retryable readiness result')
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError('ALB readiness timed out; keep the report and inspect targets/controller before resuming')
        print('WAIT: ALB provisioning/target readiness; bounded retry (report: ' + str(path) + ')', flush=True)
        sleep(min(15, remaining))


def managed(state_value):
    return [r for r in state_value.get('resources', []) if r.get('mode') == 'managed' and r.get('instances')]


def cluster(runner):
    try:
        return runner.aws('eks', 'describe-cluster', '--name', CONFIG['cluster'])['cluster']
    except CommandError as error:
        if error.aws_code == 'ResourceNotFoundException':
            return None
        raise


def connect(runner, directory, *, allow_ip_update=False, timeout=900):
    live = cluster(runner)
    if not live or live['status'] != 'ACTIVE':
        raise ValueError('Expected ACTIVE sol-test3-eks')
    cidr = public_ip()
    address = ipaddress.ip_network(cidr).network_address
    allowed = live['resourcesVpcConfig'].get('publicAccessCidrs', [])
    if not live['resourcesVpcConfig'].get('endpointPublicAccess'):
        raise ValueError('This PC needs an approved path to the private EKS endpoint')
    if not any(address in ipaddress.ip_network(item) for item in allowed):
        if not allow_ip_update:
            raise ValueError('Current PC IP is not allowed; review eks_public_access_cidrs before continuing')
        request = Path(directory) / 'eks-access.json'
        save_json(request, {'publicAccessCidrs': sorted(set(allowed + [cidr]))})
        update = runner.aws('eks', 'update-cluster-config', '--name', CONFIG['cluster'],
                            '--resources-vpc-config', 'file://' + str(request))['update']['id']
        deadline = time.monotonic() + timeout
        while True:
            result = runner.aws('eks', 'describe-update', '--name', CONFIG['cluster'], '--update-id', update)['update']
            if result['status'] == 'Successful':
                break
            if result['status'] in ('Failed', 'Cancelled') or time.monotonic() >= deadline:
                raise RuntimeError('EKS access update did not complete')
            time.sleep(10)
    kubeconfig = Path(directory).resolve() / 'kubeconfig'
    runner.run(['aws', 'eks', 'update-kubeconfig', '--name', CONFIG['cluster'], '--region', CONFIG['region'],
                '--profile', CONFIG['profile'], '--kubeconfig', str(kubeconfig)])
    runner.env['KUBECONFIG'] = str(kubeconfig)
    runner.kube('get', 'nodes')
    return live


def prepare_secrets(runner, *, destroy=False):
    values = {}
    if not destroy:
        try:
            values = runner.kube('get', 'secret', 'my-app-secrets', '-n', 'soldesk').get('data', {})
        except CommandError as error:
            if 'NotFound' not in error.stderr and 'not found' not in error.stderr:
                raise
    for field, variable in [('JWT_SECRET', 'jwt_secret'), ('JWT_REFRESH_SECRET', 'jwt_refresh_secret'),
                            ('INTERNAL_SERVICE_TOKEN', 'internal_service_token')]:
        value = base64.b64decode(values[field]).decode() if values.get(field) else base64.b64encode(secrets.token_bytes(64)).decode()
        runner.env['TF_VAR_' + variable] = value
    runner.env['TF_VAR_github_repository_public'] = 'true'


def ensure_revision(value):
    if not re.fullmatch(r'[a-f0-9]{40}', value):
        raise ValueError('Expected immutable Git commit SHA')
    return value


def clear_runtime_secrets(runner):
    for key in list(runner.env):
        if key.startswith('TF_VAR_'):
            del runner.env[key]
