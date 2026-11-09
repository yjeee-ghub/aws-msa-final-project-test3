"""Upload an immutable, tracked Git archive and wait for the VPC CodeBuild reader.

No Kubernetes credentials or Secrets are exported to GitHub. This command uses
the caller's AWS credentials (OIDC in Actions, profile in the lab installer).
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import uuid

ENV = json.loads(Path(__file__).with_name('environment.json').read_text(encoding='utf-8'))


class Client:
    def __init__(self, profile=None):
        self.profile = profile

    def aws(self, *args):
        command = ['aws', *args, '--region', ENV['region'], '--output', 'json', '--no-cli-pager']
        if self.profile:
            command += ['--profile', self.profile]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=120)
        if result.returncode:
            # AWS errors can echo request values. Do not relay them wholesale.
            raise RuntimeError('Private verifier AWS operation failed: ' + str(args[0:2]))
        return json.loads(result.stdout) if result.stdout.strip() else {}


def wait_build(client, build_id, *, timeout=1200, clock=time.monotonic, sleep=time.sleep):
    deadline, token, finished = clock() + timeout, None, False
    try:
        while clock() < deadline:
            builds = client.aws('codebuild', 'batch-get-builds', '--ids', build_id).get('builds', [])
            if len(builds) != 1 or builds[0]['id'] != build_id:
                raise ValueError('Expected exact CodeBuild ID')
            build = builds[0]
            logs = build.get('logs', {})
            if logs.get('groupName') and logs.get('streamName'):
                args = ['logs', 'get-log-events', '--log-group-name', logs['groupName'],
                        '--log-stream-name', logs['streamName'], '--start-from-head']
                if token:
                    args += ['--next-token', token]
                page = client.aws(*args)
                token = page.get('nextForwardToken')
                for item in page.get('events', []):
                    print(item['message'].rstrip(), flush=True)
            status = build['buildStatus']
            print('PRIVATE VERIFY: ' + status + ' / ' + str(build.get('currentPhase', '')), flush=True)
            if status != 'IN_PROGRESS':
                finished = True
                if status != 'SUCCEEDED':
                    raise RuntimeError('Private verifier failed: ' + status + ' (inspect CodeBuild phases/logs)')
                return {'buildId': build_id, 'status': status}
            sleep(10)
        raise TimeoutError('Private verifier exceeded its bounded wait')
    finally:
        if not finished:
            client.aws('codebuild', 'stop-build', '--id', build_id)


def submit(client, revision, *, project=None, bucket=None):
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('Expected immutable commit SHA')
    if client.aws('sts', 'get-caller-identity')['Account'] != ENV['account']:
        raise ValueError('Wrong verifier AWS account')
    project, bucket = project or ENV['verifyProject'], bucket or ENV['verifyBucket']
    if project != ENV['verifyProject'] or bucket != ENV['verifyBucket']:
        raise ValueError('Unexpected verifier destination')
    key = f'sources/{revision}/{uuid.uuid4().hex}.zip'
    with tempfile.TemporaryDirectory(prefix='final-verify-') as folder:
        archive = Path(folder) / 'source.zip'
        # git archive excludes .lab, state, local tfvars and other untracked files.
        subprocess.run(['git', 'archive', '--format=zip', '-o', str(archive), revision], check=True, timeout=60)
        client.aws('s3api', 'put-object', '--bucket', bucket, '--key', key, '--body', str(archive),
                   '--server-side-encryption', 'AES256', '--expected-bucket-owner', ENV['account'])
    build = client.aws('codebuild', 'start-build', '--project-name', project,
                       '--source-location-override', bucket + '/' + key,
                       '--environment-variables-override', 'name=REVISION,value=' + revision + ',type=PLAINTEXT')['build']
    print('Started private verifier: ' + build['id'], flush=True)
    return wait_build(client, build['id'])


def main():
    def terminate(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser()
    parser.add_argument('--revision', default=os.environ.get('GITHUB_SHA'), required=not os.environ.get('GITHUB_SHA'))
    parser.add_argument('--profile')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = submit(Client(args.profile), args.revision)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
