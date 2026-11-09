> **과거 기록의 적용 범위** · 아래는 당시 코드·계정·브랜치·준비 상태를 보존한 원문입니다. 현재 main의 실행 안내는 [README](../README.md), 실제 완료 범위는 [최신 검증 정리](21-current-validation.md)를 사용하세요. “미실행/예정”은 작성 당시 기준입니다.

# test2: 주문 복구·고객 이메일·비밀값·승인 배포

이 문서는 test2의 코드 변경과 적용 절차입니다. **test2 push는 테스트만 실행하며 AWS 게시·apply·실제 앱 배포는 하지 않습니다.** main은 기존 기준 버전입니다. 코드의 로컬 검사 결과와 실제 AWS 검증은 구분합니다.

## 반영 범위

| 항목 | 구현 |
| --- | --- |
| 주문 복구 | 요청 ID·DB 유일 제약, 상품 서비스의 재고 확보/확정/해제, 내구성 있는 처리 상태·임대·주기적 복구 |
| Outbox | 주문 확정과 이벤트 저장의 한 로컬 트랜잭션, 임대·재시도·최종 실패, eventId 유지 |
| 이메일 | SNS→SQS→Lambda(Python)→SES, DynamoDB 중복 처리, 부분 배치 실패·DLQ |
| Secrets Manager | RDS 관리형 관리자 비밀번호, ARN만 Terraform에 전달, ESO→db-credentials, IRSA 최소 범위 |
| 승인 배포 | required-ci, 코드 PR/main 보호 설정 파일, 테스트한 이미지 산출물 게시, digest 고정 배포 PR |
| 검증·롤백 | 별도 읽기 역할, Argo revision/이미지/Ready/TLS/API 검사, 이전 정상 이미지 복구 PR |

## 1. 주문 상태와 복구

```text
PENDING → 상품 재고 확보 → 주문 스냅샷·이메일 저장 → CONFIRMING
 → 상품 재고 확정 → ORDERED + Outbox 저장

확보/스냅샷 저장 실패 → COMPENSATING → 상품 재고 해제 → FAILED
```

- `Idempotency-Key`는 16–80자의 영문·숫자·하이픈/밑줄입니다. 같은 회원/키/내용은 같은 주문을 반환하며 다른 내용은 409입니다.
- 상품 서비스는 예약 ID별 행 잠금과 상품 행 잠금을 사용합니다. 같은 확보·해제를 반복해도 재고는 한 번만 변합니다. 해제 기록이 먼저 도착하면 뒤늦은 확보를 거부합니다.
- CONFIRMING 상태는 원격 확정 응답 유실 또는 DB 장애 뒤 재개합니다. 확정된 재고를 임의 해제하지 않습니다. COMPENSATING은 해제가 성공할 때까지 유지합니다.
- 주문 처리 워커는 PENDING/CONFIRMING/COMPENSATING을 다시 조회합니다. 일시 장애에는 재시도하고, 장기 미복구는 주문 DB 상태·상품 예약 상태·원인 서비스 로그를 함께 확인합니다. 모든 장애에서 즉시 완료되거나 자동으로 끝난다는 보장은 아닙니다.
- 내부 API는 공유 내부 키로 보호하고 Gateway에서 `/internal/` 경로 및 클라이언트 내부 키 전달을 차단합니다. 향후 서비스별 IAM/mTLS/NetworkPolicy로 더 세분화할 수 있습니다.
- 수신자 주소는 브라우저 입력 대신 회원 서비스의 내부 API에서 조회합니다. `/ordering/mine`, `/ordering/{id}`는 해당 회원의 결과만 반환합니다.
- 장바구니는 요청 키를 전송 전에 저장합니다. 네트워크 오류/202에서는 같은 키를 유지하고, 완료한 상품만 제거합니다. 실패·재고 해제 완료는 새 요청을 허용합니다. 상품별 주문이므로 장바구니 전체가 하나의 원자적 주문은 아닙니다.

### API 변경

POST `/ordering-service/ordering/create`: 기존 productId/productCount와 `Idempotency-Key` 헤더. 응답은 숫자 대신 `{id,productId,quantity,status,productName,unitPrice}`입니다. ORDERED=201, 처리 중=202, FAILED=409입니다. 처리 중에는 같은 키로 재조회/재시도하거나 GET `/ordering-service/ordering/{id}`를 사용하세요.

주문·상품 서비스의 주문 상태 컬럼은 Flyway V1으로 ENUM에서 VARCHAR(32)로 명시적으로 전환하고 기존 주문은 보존합니다. 전용 ordering_schema_history와 baseline-version=0을 사용합니다. 나머지 nullable 신규 필드와 새 테이블은 Hibernate update로 준비합니다. 상품 서비스의 기존 ddl-auto=none은 신규 예약 테이블 준비를 위해 update로 맞췄습니다. 데이터 초기화 스크립트는 없습니다. 실제 MySQL에서 기존 enum/DDL 변경과 이전 이미지 호환성은 적용 전 스냅샷·검증 DB에서 확인해야 합니다. 이전 앱 이미지의 무조건적인 호환성을 보장하지 않습니다.

## 2. Outbox와 이메일

`order_outbox`: PENDING→SENDING→SENT. 실패는 지수 대기 후 재시도하며 10회 실패 뒤 FAILED입니다. SENT는 SNS 수락입니다. 실패 원인 수정 후 정확한 eventId를 확인하여 운영자가 해당 FAILED 행만 PENDING으로 재설정하고 attempts/next_attempt/lease를 초기화합니다. 전체 테이블 초기화는 하지 않습니다.

Lambda는 schemaVersion=1, eventType=ORDER_CREATED JSON을 검사합니다. eventId/orderId/memberId/recipientEmail/productName/quantity/total/occurredAt을 전달합니다. 로그에 이메일·본문·비밀값을 출력하지 않습니다.

DynamoDB SENT 기록은 30일 보관합니다. PROCESSING은 임대 만료 후 재개합니다. SES 수락 뒤 SENT 기록 전에 종료되는 구간에는 중복 메일 가능성이 남습니다. 정확히 한 번 메일 도착을 보장하지 않습니다. DLQ를 장기간 보관한 뒤 재처리할 때 중복 기록 만료도 고려하세요.

### SES 준비와 소비자 활성화

1. `terraform/test2.tfvars.example`의 발신자와 테스트 수신자 주소를 실제 값으로 준비합니다. 비밀번호와 개인 tfvars는 Git에 올리지 않습니다.
2. 기본 `manage_ses_identities=false`: 계정에서 이미 인증한 SES 이메일 ID를 사용합니다. 전용 새 ID를 Terraform 소유로 생성하려면 true로 설정하고 공유 자원이 아닌지 확인합니다.
3. 발신자·샌드박스 테스트 수신자의 인증 메일을 승인합니다. SES sandbox/production 상태와 발송 권한을 확인합니다.
4. 인증 확인 후 `customer_email_enabled=true`로 변경하여 plan/apply합니다. false일 때 이벤트는 큐에 남을 수 있으며 큐 보관 기간도 고려하세요.
5. 실제 주문 → 고객 메일 → eventId/주문 번호 대조 → 실패 메시지 DLQ → 원인 수정·선택 redrive 순서로 검증합니다. redrive는 ReceiveCount만 초기화할 수 있으며, 멱등성 기록과 실제 발송 여부를 함께 확인합니다.

## 3. Secrets Manager 전환

기본 `manage_db_password=true`: RDS가 관리자 비밀번호를 생성하여 Secrets Manager에 저장합니다. Terraform은 원문을 조회하지 않습니다. RDS 관리형 비밀값의 회전 정책은 AWS에서 확인해야 합니다.

1. infra 먼저 apply. 기존 환경 업그레이드는 스냅샷/복구 경로를 확보하고 앱 영향 시간을 정합니다.
2. 같은 PowerShell에서 `terraform-k8s/Prepare-Secrets.ps1`을 실행합니다. JWT와 내부 키를 생성/재사용합니다. 관리형 모드에서는 DB 비밀번호를 묻지 않습니다.
3. k8s apply 시 `enable_app_sync=false`를 유지하고 ESO와 database-secret 차트를 먼저 준비합니다.
4. `kubectl wait externalsecret/database-credentials -n soldesk --for=condition=Ready --timeout=180s`로 확인합니다. 값 자체를 출력하지 않습니다.
5. DB 비밀번호는 `db-credentials/DB_PW`, JWT·DB_HOST·내부 키는 `my-app-secrets`가 담당합니다. 기존 Secret과 ESO가 같은 비밀번호 필드를 동시에 관리하지 않습니다. 기본 app_secret_revision은 2이며 개인 tfvars에서 1로 고정했다면 2 이상으로 올립니다.
6. 처음 전체 이미지 준비 후 앱 sync를 켜고 DB readiness/조회/주문을 확인합니다. API의 내부 키가 필요한 회원·상품·주문 서비스는 함께 갱신합니다.

### 수동 교체 실습

RDS 관리형 비밀번호 회전을 요청한 뒤, Secrets Manager의 버전과 ESO Ready/갱신을 확인하고 DB 사용 Deployment(member-depl/product-depl/ordering-depl)를 순차 재시작하여 새 환경변수를 읽게 합니다. 실제 회전 명령은 먼저 `aws rds modify-db-instance help`의 관리형 자격증명 옵션과 대상 DB를 확인하세요. Secret 갱신만으로 실행 중인 환경변수나 기존 커넥션 풀이 자동 갱신되지는 않습니다. 교체 중 새 연결 실패/복구와 앱 기능을 확인해야 완료입니다.

`manage_db_password=false`는 기존 수동 입력 방식이며 이때만 Terraform이 별도 db-credentials Secret을 쓰기 전용으로 관리합니다. 기본값 전환은 실제 DB 비밀번호 변경을 수반하므로 단순한 무중단 설정 변경으로 설명하지 않습니다.

## 4. 코드 PR과 배포 승인

1. 팀원에게 write 권한을 부여하고 CODEOWNERS를 실제 담당자로 조정합니다. 자신이 작성한 PR은 다른 사람이 승인해야 합니다.
2. `required-ci` 검사가 실제 PR에서 실행된 뒤 `scripts/github/Set-ReviewRules.ps1`로 예정 규칙을 확인합니다. `-Apply`가 있어야 GitHub 설정을 변경합니다. 공개/비공개와 요금제의 브랜치 보호 지원 범위를 확인하세요.
3. main 병합 후 변경 서비스만 테스트/이미지 빌드합니다. Docker save 산출물을 게시 단계에 전달하여 다시 빌드하지 않습니다.
4. ECR 게시 후 태그와 digest를 `deploy/release.json`/Kustomize에 기록하고 release 브랜치 PR을 엽니다. main 직접 push/자동 병합은 하지 않습니다.
5. 다른 팀원이 배포 PR을 승인·병합하면 Argo가 반영합니다. 배포 파일만 변경하면 재빌드가 반복되지 않습니다.
6. 최초 ECR 재구축 또는 이전 게시 실패 후에는 main의 workflow_dispatch에서 full_build=true를 실행하세요. SHA 태그가 이미 존재하면 ECR IMMUTABLE 정책과 기존 이미지 존재를 먼저 확인하세요.

기본 GITHUB_TOKEN을 쓰는 자동 PR의 검사 실행은 GitHub 정책상 추가 승인이 필요할 수 있습니다. 권장 방식은 이 저장소에만 contents/pull_requests write 권한을 가진 GitHub App을 설치하고 `RELEASE_APP_ID` 변수, `RELEASE_APP_PRIVATE_KEY` Secret을 등록하는 것입니다. 장기 AWS 키는 추가하지 않습니다. GitHub Actions의 PR 생성 허용 설정도 필요합니다. main 보호·App·팀원 권한은 파일 push만으로 적용되지 않습니다.

## 5. 배포 후 확인과 롤백

infra 출력 `github_deploy_check_role_arn`을 Actions 변수 `AWS_DEPLOY_CHECK_ROLE_ARN`에 등록합니다. 이 역할은 eks:DescribeCluster와 Kubernetes Deployment/final-apps 조회만 허용하고 Secret·변경 권한은 없습니다.

환경 준비 후 `ENABLE_DEPLOY_CHECKS=true`를 설정합니다. main의 배포 선언 변경 병합 후 deploy-check가 Argo revision·이미지·가용 replica·TLS·HTML·상품 JSON을 검사합니다. API 접근 CIDR이 GitHub hosted runner를 차단하면 VPC 내 전용 runner 등 승인된 네트워크 경로를 먼저 준비하세요. 검사를 위해 무조건 API를 전체 공개하지 않습니다.

```powershell
# 읽기 전용 점검. 실제 배포 commit SHA를 전달합니다.
python scripts/ops/check_release.py --revision <배포-commit-40자리>

# 이전 release.json이 존재하고 5개 서비스 이미지가 기록된 commit을 선택합니다.
# AWS ECR 읽기 권한과 gh 인증이 필요합니다. 작업 트리는 깨끗해야 합니다.
python scripts/ops/rollback_release.py --release-commit <이전-정상-release-commit-40자리>
```

rollback 스크립트는 이전 이미지 존재를 확인하고 **현재 main의 다른 설정은 유지한 채** 이미지 선언을 바꾸는 별도 PR을 만듭니다. 사람이 DB 호환성을 검토하고 승인·병합합니다. 자동 rollback, DB 복원, Terraform 되돌리기는 하지 않습니다. 완료 후 같은 검사를 다시 실행하세요.

## 6. 적용 순서 요약

로컬 검사→test2 리뷰 PR→main 반영→GitHub 팀/규칙/App 설정→infra plan/apply→SES 인증→kubeconfig→Prepare-Secrets→k8s 도구/ESO apply(sync off)→Secret Ready→최초 전체 이미지 빌드·배포 PR 승인→앱 sync→관리 ingress/DNS→배포 검증 활성화→주문/메일/실패/교체/롤백 실습.

원격 state bucket과 기존 Route53 zone은 보존 자원입니다. init/migrate로 예전 state를 덮어쓰지 않습니다. 현재 test2 코드만 작업하려면 AWS apply와 Argo의 github_revision 변경을 하지 마세요.

## 7. 검증 구분과 한계

### 이번 브랜치의 로컬 검증 결과

| 검사 | 결과 |
| --- | --- |
| Java 회귀 검사 | 회원 11개·상품 6개·주문 11개·게이트웨이 6개 통과 |
| 프런트엔드 | Node 테스트 7개 통과 |
| 소비자·CI·운영 스크립트 | Python 테스트 18개 통과 |
| 인프라 코드 | Terraform 3개 루트 validate, k8s mock test 1개, Helm 차트·워크플로 문법 검사 통과 |
| 실제 MySQL 8.4.11 | 주문·상품 테스트 및 회원/상품/주문 서비스 간 HTTP 연동 확인 |
| 기존 DB 업그레이드 | 기존 ENUM 상태를 VARCHAR로 변환하고 기존 주문 데이터 유지 확인 |

로컬 HTTP 연동에서는 중복 요청의 주문 번호 유지·재고 한 번 차감·Outbox 한 건 생성·다른 회원의 주문 조회 차단·내부 API 무단 호출 차단을 확인했습니다. 회원 서비스 중단 시 주문 FAILED와 재고 원복도 확인했습니다. 이 검사는 로컬 MySQL과 실제 앱 프로세스를 사용했으며 AWS SNS/SES 발송은 비활성화했습니다.

- 로컬: Java 주문/재고/보상/Outbox·권한 테스트, Node 장바구니·대시보드, Python 소비자/배포·운영 테스트, Terraform validate·mock plan, Kustomize 렌더링.
- 별도 AWS 검증 필요: 실제 RDS/Secrets Manager 회전·ESO 갱신, SES 인증/메일 수신, SQS DLQ/redrive, IAM 실제 거부, Argo 배포·GitHub 규칙 강제·배포 PR·실제 롤백.
- H2의 테스트 결과를 MySQL 실환경의 enum 변경/락/DDL/다중 파드 전체 검증과 동일하게 보지 않습니다.
- 자동 복구는 DB/서비스가 다시 사용 가능하고 lease/recovery worker가 실행되는 조건입니다. 장기 미복구 주문·FAILED Outbox에 대한 운영 개입이 필요할 수 있습니다.
- 앱 롤백 전 API/DB 호환성을 검토해야 합니다. 특히 구버전 주문 API와 내부 토큰 도입 전 이미지를 섞어 배포하지 마세요.

이 문서는 실제 apply 성공 보고서가 아닙니다. 이번 브랜치의 코드는 main 병합·환경 설정·실환경 검증 전입니다.
