"""선택한 이미지의 태그만 변경하고 다른 이미지의 태그는 보존합니다."""
import argparse
import json
import re
from pathlib import Path

ENVIRONMENT = json.loads((Path(__file__).resolve().parents[1] / "ops/environment.json").read_text(encoding="utf-8"))
REGISTRY = f"{ENVIRONMENT['account']}.dkr.ecr.{ENVIRONMENT['region']}.amazonaws.com"
IMAGES = {s: s + "-service" for s in ("member", "product", "ordering", "frontend")}
IMAGES["apigateway"] = "apigateway"

def update(text, services, tag):
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag):
        raise ValueError("잘못된 이미지 태그")
    for service in services:
        image = IMAGES[service]
        pattern = r"(^  - name: " + re.escape(REGISTRY + "/" + image) + r"\n    newTag: )[^\n]+(?:\n    digest: [^\n]+)?"
        text, count = re.subn(pattern, lambda m: m[1] + tag, text, flags=re.M)
        if count != 1:
            raise ValueError(f"이미지 항목은 정확히 하나여야 합니다: {service}")
    return text

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tag", required=True)
    p.add_argument("services", nargs="+", choices=list(IMAGES))
    args = p.parse_args()
    path = Path("app/msa/kustomization.yaml")
    # Windows의 기본 CP949와 관계없이 저장소의 UTF-8을 유지합니다.
    path.write_text(update(path.read_text(encoding="utf-8"), args.services, args.tag), encoding="utf-8")
