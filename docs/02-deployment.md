# 테스트한 이미지를 GitOps로 배포하기

개인 실습에서는 CI가 검사한 이미지의 digest를 main에 기록합니다. 팀 승인으로 운영했던 시연은 [과거 배포 기록](RELEASES.md)에 보존합니다.

## 소스 검사와 이미지 게시

[build-push.yml](../.github/workflows/build-push.yml)은 변경 서비스를 선택하고 자동화 단위 검사·설정 검사·Windows 실행 검사를 수행합니다. 서비스 검사와 Docker 빌드가 통과한 이미지 산출물을 보관한 후, 게시 단계에서 동일 산출물을 ECR에 올립니다. 게시를 위한 별도 미검증 재빌드를 하지 않습니다.

[test-service.sh](../scripts/ci/test-service.sh)는 Member·Product·Ordering의 지정된 테스트, Gateway 테스트, 프런트엔드 Node 검사를 실행합니다. 모든 Java 테스트와 실제 RDS 통합 검사를 무조건 실행하는 구성은 아닙니다. Python 자동화 검사의 다수도 모의 실행입니다.

이미지 게시는 main에서 `ENABLE_IMAGE_PUBLISH` 또는 명시적 dispatch 입력이 활성화된 경우에 실행됩니다.

## main 배포 커밋과 Argo CD

OIDC로 ECR 게시 권한을 얻고 서비스별 digest를 고정합니다. 워크플로는 검사한 소스가 여전히 main의 최신 커밋인지 확인한 뒤 다음 두 파일만 새 커밋으로 추가합니다.

- [app/msa/kustomization.yaml](../app/msa/kustomization.yaml): 실행할 이미지 digest
- [deploy/release.json](../deploy/release.json): 서비스별 소스 SHA·digest·워크플로 출처

Argo CD는 Git의 선언을 읽어 EKS를 동기화하고, 노드는 ECR에서 이미지를 받습니다. 개인 저장소의 main 규칙은 Actions의 일반 push를 허용해야 합니다. 소스 커밋이 빌드 도중 바뀌면 다음 실행에서 다시 검사합니다.

최초 설치는 main에 게시된 release commit에 고정하고 초기 검증 후 `Install-Lab.ps1 -Execute -PromoteMain` 경로로 main 추적에 전환합니다. 실제 실행 전 [설치 가이드](15-one-command-lab.md)의 체크포인트를 확인합니다.

## VPC CodeBuild의 배포 후 검사

[deploy-check.yml](../.github/workflows/deploy-check.yml)은 게시 워크플로에서 배포 커밋 SHA로 호출됩니다. 사용자가 main에 배포 선언을 push하거나 수동 실행할 때도 `ENABLE_DEPLOY_CHECKS` 조건으로 실행됩니다. GitHub OIDC→검증 소스 ZIP S3→VPC CodeBuild 순서입니다. CodeBuild는 사설 EKS API에 접근할 수 있도록 기존 프라이빗 서브넷을 사용합니다.

검사 대상은 revision·이미지·가용성·TLS·HTML·상품 API입니다. EKS 권한은 soldesk Deployment와 지정 Argo Application의 조회 중심으로 제한하며 Secret 읽기·배포 변경 권한을 주지 않습니다. 정상 검증과 의도적으로 잘못된 revision 실패는 [10월 실제 기록](17-validation-20261021.md)에서 확인합니다.

이 검사를 통과해도 모든 사용자 동작이 정상인 것은 아닙니다. V2의 상품 상세 오류는 기존 기본 검사를 통과했으므로 V3에서 카드→상세 회귀 검사를 추가했습니다. [실제 흐름과 PR](RELEASES.md)

## 롤백과 다음 버전

복구도 Git에 선언하고 검토하는 변경입니다. [rollback_release.py](../scripts/ops/rollback_release.py)는 이전 main의 release에서 이미지 digest를 가져와 main에 복구 커밋을 추가합니다. 복구 범위는 앱 이미지입니다. 스키마·외부 API 호환성과 ECR 이미지 존재를 먼저 확인합니다. [절차](ROLLBACK.md)

애플리케이션 자동 배포와 Terraform 인프라 적용은 별도입니다. 개인 실습 경로의 실제 실행 결과는 별도로 기록합니다.
