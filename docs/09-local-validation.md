> **과거 기록의 적용 범위** · 아래는 당시 코드·계정·브랜치·준비 상태를 보존한 원문입니다. 현재 main의 실행 안내는 [README](../README.md), 실제 완료 범위는 [최신 검증 정리](21-current-validation.md)를 사용하세요. “미실행/예정”은 작성 당시 기준입니다.

# 개선 변경의 로컬 검증 기록

검증일: 2026-10-15. 대상은 `test` 브랜치 코드다. AWS CLI를 통한 실제 AWS 조회·변경, Terraform apply/destroy, ECR 게시, EKS 배포는 실행하지 않았다. 아래 결과는 AWS 운영 환경 성공을 뜻하지 않는다.

| 항목 | 결과 |
| --- | --- |
| Java 17 / Gradle 8.12.1 | 네 서비스 `bootJar` 및 선택 테스트 성공 |
| member | 기존 관리자 테스트 9개 + DB 장애/복구 health group 테스트 1개 통과 |
| product | H2 동시 재고 테스트 1개 통과 |
| ordering | 주문 검증·저장·알림 테스트 3개 통과 |
| apigateway | 전체 기존 테스트 5개 통과 |
| frontend | 기존 Node 테스트 5개 통과 |
| CI 선택·태그 갱신 | Python 테스트 4개 통과 |
| 운영 스크립트 | 가짜 AWS CLI를 사용한 PowerShell 테스트 5개 통과 (빈 결과/AccessDenied 구분, VPC 미태그 하위 자원 조회, 별도 비공개 복원 대상, 기존 대상 및 권한 실패 거부, WhatIf) |
| GitHub Actions | actionlint 1.7.7 통과, test/PR에서 publish job 및 OIDC 인증 진입 차단 조건 확인 |
| Terraform | 1.13.5로 세 루트 `init -backend=false` 및 validate 성공, 기존 Kubernetes 모의 테스트 1개 통과 |
| Kubernetes | kubectl 1.35.0의 `kustomize app/msa` 성공, PDB 포함 18개 리소스 렌더링 |
| 설정 파일 | 변경 YAML 중복 키 검사, PowerShell 전체 파일 parser 검사, bash 문법 검사, git diff --check 통과 |
| Gateway 실행 | 새 JAR를 로컬 별도 포트에서 실행, liveness/readiness 모두 HTTP 200 / UP, 인증 없는 관리자 요청 401 확인 후 종료 |
| frontend 이미지 | 로컬 Docker 빌드 및 Gateway DNS를 대체한 nginx -t 성공, 이미지 게시 없음 |

재현 가능한 핵심 명령 (저장소 루트, JDK 17·Node·Python·PowerShell 7 준비):

```bash
python3 -m unittest discover -s tests -v
node --test app/msa/frontend/tests/*.test.cjs
bash scripts/ci/test-service.sh member
bash scripts/ci/test-service.sh product
bash scripts/ci/test-service.sh ordering
bash scripts/ci/test-service.sh apigateway
bash -n scripts/ci/test-service.sh
actionlint .github/workflows/build-push.yml
kubectl kustomize app/msa
```

PowerShell를 설치하지 않은 환경에서는 운영 스크립트 mock 테스트가 skip되므로 통과 개수와 skip 개수를 구분한다. 이번 검증에서는 PowerShell 7.5.4로 skip 없이 실행했다. 운영 MySQL/AWS가 필요한 member/product/ordering의 전체 context 테스트는 실행하지 않았다. Java 4개 서비스의 Docker 이미지 빌드 자체는 CI에서 수행하며, 이번 로컬 검증은 Java JAR 빌드와 frontend Docker 빌드를 확인했다.

Terraform은 backend 자격증명 사용을 피하기 위해 저장소 외부의 검증 복사본에서 검사했다. 기존 Windows용 h1 외에 Linux용 h1이 필요해 복사본에서 공식 서명 provider 설치로 플랫폼 해시를 추가했으며, 기존 두 루트의 추적 lockfile은 바꾸지 않았다. 새 bootstrap lockfile만 공식 provider 설치 결과로 추가했다. 체크섬·TLS 검증을 비활성화하지 않았다. mock test는 실제 S3 remote_state를 읽지 않고 기존 override_data를 사용한다.

월요일에는 S3 버전 관리·잠금 동시 실행·접근 제어, 실제 state 이전, EKS 로그 수집/14일 보관, ALB 및 DNS/HTTPS, DB 장애 시 Ready·restartCount, frontend 두 파드 배치/축출/롤링 자원 여유, 실제 RDS 스냅샷·복원 데이터, Actions 선택 빌드와 Argo CD revision을 확인해야 한다. [월요일 순서](06-monday-runbook.md)를 따른다.
