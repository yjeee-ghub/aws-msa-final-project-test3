> **과거 문서 보존본** · 2026-11-04 최신화 전 main `cc040cf`의 원문입니다. 현재 실행 안내가 아닙니다. [현재 README](../../../README.md)와 [검증 범위](../../21-current-validation.md)를 사용하세요.

> **test2 승인 배포 도입 이후:** digest와 release.json을 함께 복구해야 합니다. 아래 과거 태그 수동 변경 대신 [새 복구 PR 절차](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/11-test2-delivery.md#5-배포-후-확인과-롤백)를 우선 사용하세요. DB 호환성 검토 후 병합합니다.

# 이전 배포로 돌아가기

새 버전에 문제가 생겼을 때 이전에 쓰던 버전으로 되돌리는 것을 **롤백**이라고 한다.

내 프로젝트에서는 실행할 이미지 버전을 Git에 적어두고 Argo CD가 반영한다. 따라서 이전 버전으로 돌아갈 때도 Git의 이미지 태그를 바꾸는 방식을 사용한다.

## 어디를 바꾸면 될까?

`app/msa/kustomization.yaml`의 `newTag`가 사용할 이미지 버전이다.

```yaml
images:
  - name: 143710973003.dkr.ecr.ap-northeast-2.amazonaws.com/frontend-service
    newTag: 58ab067dd239160afc60941cf14aee5830ca5840
```

위 코드는 프런트엔드의 예시다. 어떤 버전인지 확인할 때는 [배포 이력](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/RELEASES.md)을 보면 된다.

## 4차에서 3차로 돌아가려면

이번에는 화면·회원 서비스·Gateway를 함께 바꿨다. 앱 전체를 이전 배포로 돌리려면 Kustomize 파일에 있는 **다섯 서비스의 newTag를 모두 아래 값으로 맞춘다.**

```text
58ab067dd239160afc60941cf14aee5830ca5840
```

이것은 4차 대시보드 이전인 3차 배포 이미지다. 태그를 수정한 뒤에는 파일을 Git에 반영한다.

```powershell
Set-Location 'C:\aws-msa-backend-terraform'
git diff -- app/msa/kustomization.yaml
git add app/msa/kustomization.yaml
git commit -m "Roll back app images to the previous release"
git push origin main
```

```text
Git에서 이전 이미지 태그로 변경
  → Argo CD가 변경 확인
  → ECR에 있는 이전 이미지로 파드 교체
```

현재 workflow에서는 Kustomize 태그만 바꾸면 이미지 빌드를 다시 실행하지 않는다. ECR에 저장돼 있는 이미지를 사용한다.

## 되돌아갔는지 확인

```powershell
kubectl get applications -n argocd
kubectl get pods -n soldesk
```

Argo CD의 Synced는 Git 설정과 동기화됐다는 뜻이고, Healthy는 Argo CD가 판단한 앱 상태가 정상이라는 뜻이다. 새로 교체된 파드가 Ready인지 보고 홈페이지도 직접 확인한다.

## 알아둘 점

- Git 기록에 태그가 있어도 ECR에서 이미지를 삭제했다면 그대로 사용할 수 없다. 필요한 이미지가 없다면 과거 소스로 다시 빌드해야 한다.
- `kubectl rollout undo`만 실행하면 Argo CD가 Git의 새 버전으로 다시 맞출 수 있다. 유지할 변경은 Git에도 남긴다.
- 이번 대시보드는 DB 구조를 바꾸지 않았다. DB 구조나 설정도 변경한 배포는 이미지와 함께 호환성을 확인한다. 코드 변경 자체를 되돌릴 때는 `git revert`를 검토한다.

[프로젝트 홈](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/README.md)
