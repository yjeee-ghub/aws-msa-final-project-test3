"""선택 누락과 엉뚱한 이미지 태그 변경을 막는 회귀 테스트입니다."""
import importlib.util
from pathlib import Path
import unittest

def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "scripts/ci" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

changes = load("changed_services")
tags = load("update_image_tags")

class CiTests(unittest.TestCase):
    def test_service_and_common_changes(self):
        self.assertEqual(changes.select(["app/msa/member/src/A.java"]), ["member"])
        self.assertEqual(changes.select(["app/msa/frontend/tests/cart.test.cjs"]), ["frontend"])
        self.assertEqual(changes.select(["app/msa/product/build.gradle", "app/msa/ordering/gradle/wrapper/gradle-wrapper.properties"]), ["product", "ordering"])
        self.assertEqual(changes.select(["app/msa/shared/common.txt"]), list(changes.SERVICES))
        self.assertEqual(changes.select([".github/workflows/build-push.yml"]), list(changes.SERVICES))
        self.assertEqual(changes.select([], full=True), list(changes.SERVICES))

    def test_unpublished_changes_survive_later_push(self):
        tags = {s: "a" * 40 for s in changes.SERVICES}
        # 현재 push의 product 외에 이전 게시 실패로 남은 member 변경도 선택해야 합니다.
        paths = ["app/msa/member/src/Previous.java", "app/msa/product/src/Current.java"]
        self.assertEqual(changes.pending_services(tags, lambda _: paths), ["member", "product"])
        tags["frontend"] = "lab-v1"
        self.assertEqual(changes.pending_services(tags, lambda _: []), ["frontend"])

    def test_manifest_only_does_not_rebuild_or_loop(self):
        self.assertEqual(changes.select(["app/msa/kustomization.yaml", "app/msa/member/k8s/depl_svc.yml", "docs/README.md"]), [])

    def test_update_only_selected_images(self):
        original = (Path(__file__).parent / "fixtures/image-tags.yaml").read_text(encoding="utf-8")
        updated = tags.update(original, ["member", "frontend"], "test-123")
        self.assertEqual(updated.count("newTag: test-123"), 2)
        self.assertEqual(sum(a != b for a, b in zip(original.splitlines(), updated.splitlines())), 2)
        with self.assertRaises(ValueError):
            tags.update(original, ["member"], "bad/tag")
        with self.assertRaises(ValueError):
            tags.update("", ["member"], "valid")

if __name__ == "__main__":
    unittest.main()
