"""Readiness plus server dry-run admission; creates no persisted Kubernetes object."""
from contextlib import contextmanager
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time


def command(args, input=None):
    return subprocess.run(args, input=input, capture_output=True, text=True, encoding="utf-8", timeout=35)


def endpoints_ready(data):
    return any(endpoint.get("conditions", {}).get("ready") is True
               for item in data.get("items", []) for endpoint in item.get("endpoints", []))


@contextmanager
def kubeconfig(cluster, profile, region):
    response = command(["aws", "eks", "describe-cluster", "--name", cluster,
                        "--region", region, "--profile", profile, "--output", "json", "--no-cli-pager"])
    if response.returncode:
        raise RuntimeError("Cannot describe the intended EKS cluster")
    info = json.loads(response.stdout)["cluster"]
    if info["name"] != cluster or info.get("status") != "ACTIVE":
        raise RuntimeError("EKS is not ACTIVE")
    config = {"apiVersion": "v1", "kind": "Config", "current-context": "webhook-check",
              "clusters": [{"name": "target", "cluster": {"server": info["endpoint"], "certificate-authority-data": info["certificateAuthority"]["data"]}}],
              "contexts": [{"name": "webhook-check", "context": {"cluster": "target", "user": "target"}}],
              "users": [{"name": "target", "user": {"exec": {"apiVersion": "client.authentication.k8s.io/v1beta1", "command": "aws", "args": ["eks", "get-token", "--cluster-name", cluster, "--region", region, "--profile", profile]}}}]}
    with tempfile.TemporaryDirectory(prefix="final-webhook-") as folder:
        path = Path(folder) / "kubeconfig.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        yield str(path)


def wait(cluster, profile, region, timeout=300):
    with kubeconfig(cluster, profile, region) as path:
        kubectl = ["kubectl", "--kubeconfig", str(path), "--request-timeout=20s"]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            dep = command(kubectl + ["get", "deployment", "aws-load-balancer-controller", "-n", "kube-system", "-o", "json"])
            eps = command(kubectl + ["get", "endpointslices", "-n", "kube-system", "-l", "kubernetes.io/service-name=aws-load-balancer-webhook-service", "-o", "json"])
            if not dep.returncode and not eps.returncode:
                d = json.loads(dep.stdout)
                ready = d.get("status", {}).get("availableReplicas", 0) >= d["spec"].get("replicas", 1)
                if ready and endpoints_ready(json.loads(eps.stdout)):
                    probe = {"apiVersion": "v1", "kind": "Service", "metadata": {"generateName": "final-webhook-readiness-", "namespace": "default"}, "spec": {"ports": [{"port": 80}], "type": "ClusterIP"}}
                    admitted = command(kubectl + ["create", "--dry-run=server", "-f", "-", "-o", "name"], json.dumps(probe))
                    if admitted.returncode == 0:
                        print("PASS: ALB Controller, webhook endpoints and admission dry-run")
                        return
            print("WAIT: ALB webhook is not ready; dependent charts are held")
            time.sleep(5)
    raise TimeoutError("ALB webhook readiness timed out; inspect Controller logs/events before retry")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cluster", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--region", required=True)
    p.add_argument("--timeout", type=int, default=300)
    args = p.parse_args()
    wait(args.cluster, args.profile, args.region, args.timeout)
