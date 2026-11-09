"""Execute the real provisioner configuration in a provider-free local fixture.

Only local terraform_data state is created in a temporary directory. The probe
scripts do not contact AWS/Kubernetes. Spaces, Unicode and shell characters in
paths/values must survive Terraform -> Python, including sibling-module import.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('terraform'), 'Terraform CLI required for the local execution fixture')
class ReadinessExecTests(unittest.TestCase):
    def test_both_provisioners_execute_without_a_shell(self):
        for resource_file, script_name in [('webhook_ready.tf', 'wait_webhook.py'),
                                           ('external_secrets.tf', 'wait_database_secret.py')]:
            with self.subTest(gate=script_name), tempfile.TemporaryDirectory(prefix='final gate 한글 & ') as folder:
                base = Path(folder)
                root = base / 'terraform-k8s'
                root.mkdir()
                scripts = base / 'scripts' / 'ops'
                scripts.mkdir(parents=True)
                (scripts / 'sibling_probe.py').write_text('VALUE = "imported"\n', encoding='utf-8')
                (scripts / script_name).write_text(
                    'import json, os, pathlib, sys\nfrom sibling_probe import VALUE\n'
                    'pathlib.Path(os.environ["FINAL_TEST_RESULT"]).write_text('
                    'json.dumps({"args": sys.argv[1:], "sibling": VALUE}), encoding="utf-8")\n', encoding='utf-8')
                source = (ROOT / 'terraform-k8s' / resource_file).read_text(encoding='utf-8')
                block = source[source.index('  provisioner "local-exec"'):source.rfind('\n}')]
                self.assertIn('interpreter = ["python", "-c"]', block)
                (root / 'main.tf').write_text(
                    (ROOT / 'terraform-k8s/readiness_exec.tf').read_text(encoding='utf-8')
                    + '\nvariable "cluster_name" { default = "sol-test3-eks" }\n'
                    + 'variable "aws_profile" { default = "test profile & %PATH%" }\n'
                    + 'variable "aws_region" { default = "ap-northeast-2" }\n'
                    + 'resource "terraform_data" "probe" {\n' + block + '\n}\n', encoding='utf-8')
                result_file = base / 'result.json'
                env = dict(os.environ, FINAL_TEST_RESULT=str(result_file), TF_IN_AUTOMATION='1')
                for args in [('init', '-backend=false', '-input=false', '-no-color'),
                             ('apply', '-auto-approve', '-input=false', '-no-color')]:
                    process = subprocess.run(['terraform', '-chdir=' + str(root), *args],
                                             env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
                    self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                actual = json.loads(result_file.read_text(encoding='utf-8'))
                self.assertEqual(actual, {'args': ['--cluster', 'sol-test3-eks', '--profile',
                                                 'test profile & %PATH%', '--region', 'ap-northeast-2'],
                                          'sibling': 'imported'})


if __name__ == '__main__':
    unittest.main()
