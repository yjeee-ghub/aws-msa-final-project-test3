"""Git 차이로 빌드 대상을 선택합니다. 공통 파일은 보수적으로 전체 빌드합니다."""
import argparse
import json
import os
import re
from pathlib import Path
import subprocess

SERVICES = ("member", "product", "ordering", "apigateway", "frontend")

def select(paths, full=False):
    if full:
        return list(SERVICES)
    selected = set()
    for path in paths:
        if path.startswith(("scripts/ci/", "tests/")) or path == ".github/workflows/build-push.yml":
            return list(SERVICES)
        if not path.startswith("app/msa/"):
            continue
        rest = path[len("app/msa/"):]
        parts = rest.split("/")
        if parts[0] in SERVICES:
            # 배포 매니페스트와 문서만 바꾸면 이미지를 다시 만들지 않습니다.
            if len(parts) > 1 and parts[1] != "k8s" and not path.endswith(".md"):
                selected.add(parts[0])
        elif parts[0] not in ("k8s", "legacy", "scripts", "ops") and rest != "kustomization.yaml" and not path.endswith((".md", ".ps1")):
            return list(SERVICES)
    return [s for s in SERVICES if s in selected]

def pending_services(tags, diff_paths):
    # 이전 실행이 실패하거나 동시 push가 묶여도 미게시 변경을 놓치지 않습니다.
    selected = []
    for service in SERVICES:
        base = tags.get(service, "")
        if not re.fullmatch(r"[0-9a-f]{40}", base):
            selected.append(service)
            continue
        try:
            changed = select(diff_paths(base))
        except subprocess.CalledProcessError:
            # 예전 이미지 커밋을 조회할 수 없으면 해당 서비스를 안전하게 다시 빌드합니다.
            selected.append(service)
            continue
        if service in changed:
            selected.append(service)
    return selected

def diff_paths(base, head):
    return subprocess.check_output(["git", "diff", "--no-renames", "--name-only", "-z", base, head]).decode().split("\0")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--all", action="store_true")
    p.add_argument("--since-image-tags", action="store_true")
    args = p.parse_args()
    if args.since_image_tags and not args.all:
        manifest = Path("app/msa/kustomization.yaml").read_text(encoding="utf-8")
        tags = {}
        for service in SERVICES:
            image = service if service == "apigateway" else service + "-service"
            match = re.search(r"/" + image + r"\n    newTag: ([^\n]+)", manifest)
            tags[service] = match[1].strip() if match else ""
        release = Path("deploy/release.json")
        if release.exists():
            # A rollback changes the deployed image, but does not make the
            # already-present source changes eligible for automatic publication.
            tags.update(json.loads(release.read_text(encoding="utf-8")).get("buildBaselines", {}))
        services = pending_services(tags, lambda base: diff_paths(base, args.head))
    elif args.all or not args.base or set(args.base) == {"0"}:
        services = select([], full=True)
    else:
        # 삭제·이름 변경의 이전 경로도 포함합니다. diff 실패를 전체 성공으로 숨기지 않습니다.
        paths = diff_paths(args.base, args.head)
        services = select(paths)
    result = json.dumps(services)
    print(result)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("services=" + result + "\n")
