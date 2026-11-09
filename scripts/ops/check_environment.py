"""Fail before AWS if shared public settings and literal S3 backends disagree.

Terraform backend blocks cannot reference locals. Keep their literal account,
region, profile and bucket reviewed in Git; never migrate state automatically.
This does not claim that the whole application is portable to another region.
"""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def check(root=ROOT):
    config=json.loads((root/'scripts/ops/environment.json').read_text(encoding='utf-8'))
    for directory, state in (('terraform', 'infra'), ('terraform-k8s', 'k8s')):
        text=(root/directory/'backend.tf').read_text(encoding='utf-8-sig')
        for name, value in [('bucket',config['stateBucket']),('region',config['region']),('profile',config['profile']),
                            ('key', f"{config['project']}/{state}/terraform.tfstate")]:
            found=re.search(r'\b'+name+r'\s*=\s*"([^"]+)"',text)
            if not found or found[1] != value:
                raise ValueError('Backend/shared setting mismatch: '+directory+'/'+name+'; review state location before changing it')
        if config['account'] not in text:
            raise ValueError('Backend account restriction mismatch')
    # Application manifests still intentionally use the selected existing domain.
    # Reject a partial domain conversion, rather than silently deploy split DNS.
    ingress = (root/'app/msa/k8s/k8s-services/ingress.yml').read_text(encoding='utf-8-sig')
    ingress_values = (
        f"host: {config['websiteHost']}",
        f"alb.ingress.kubernetes.io/load-balancer-name: {config['loadBalancer']}",
        f"alb.ingress.kubernetes.io/group.name: {config['project']}-shared",
    )
    if any(value not in ingress for value in ingress_values):
        raise ValueError('Application Ingress hostname or ALB configuration mismatch')
    return config


if __name__=='__main__':
    check()
    print('PASS: shared settings, backend identity and application hostname agree')
