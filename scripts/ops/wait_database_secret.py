"""Readiness gate: no Secret content is printed or stored."""
import argparse
import subprocess
import time
import os
from wait_webhook import kubeconfig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument("--profile", default="512-team01")
    parser.add_argument("--region", default="ap-northeast-2")
    parser.add_argument("--cluster", default="sol-test3-eks")
    args = parser.parse_args()
    with kubeconfig(args.cluster, args.profile, args.region) as path:
        environment = dict(os.environ, KUBECONFIG=path)
        check(args.timeout, environment)


def check(timeout, environment):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run([
            'kubectl', 'wait', 'externalsecret/database-credentials', '-n', 'soldesk',
            '--for=condition=Ready', '--timeout=10s', '--request-timeout=15s'
        ], capture_output=True, env=environment)
        if result.returncode == 0:
            # Only ask for the key name, never its value.
            key = subprocess.run([
                'kubectl', 'get', 'secret', 'db-credentials', '-n', 'soldesk',
                '-o', 'go-template={{if index .data "DB_PW"}}present{{end}}',
                '--request-timeout=15s'
            ], capture_output=True, text=True, env=environment)
            if key.returncode == 0 and key.stdout == 'present':
                print('PASS: ESO Ready and DB_PW key present')
                return
        time.sleep(5)
    raise SystemExit('FAIL: DB Secret readiness timed out; check ESO/IRSA/Secrets Manager, do not enable app sync')


if __name__ == '__main__':
    main()
