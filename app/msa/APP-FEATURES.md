> **test2 변경:** 주문 요청에 Idempotency-Key가 필요하고 응답은 상태 JSON입니다. DB Secret 분리와 내부 키도 필요합니다. [새 적용 안내](../../docs/11-test2-delivery.md)를 먼저 읽으세요.

# 간단한 스토어 기능 추가

## 4차 배포: 관리자 운영 대시보드

관리자 페이지를 바로가기 모음에서 요약 대시보드로 변경했다. 4차 이미지 배포와 실제 DB·모니터링·Argo CD 조회 연결까지 확인했다. 아래 명령은 이후 변경을 다시 배포할 때 참고한다.

- DB: 전체 회원·상품·상품별 주문 기록·남은 재고 합계. 고객 개인정보와 DB 접속 정보는 반환하지 않는다.
- 모니터링: Grafana health 응답, Prometheus의 Ready 노드·soldesk 파드 수.
- 배포: Argo CD final-apps의 Sync·Health 상태와 반영 커밋.
- 화면: 수동 새로고침과 1분 자동 갱신. 실패한 조회값은 — / 확인 불가로 표시.

추가한 Kubernetes 권한은 member-dashboard ServiceAccount가 argocd 네임스페이스의 final-apps Application 하나를 get하는 것뿐이다. Secret 조회·리소스 수정 권한은 없다. Role과 RoleBinding은 앱의 Kustomize 배포 목록에 포함했다.

Terraform 변경이나 Grafana·Argo CD 비밀번호 등록은 필요하지 않다. Grafana의 상세 화면과 Argo CD의 개별 로그인은 그대로 사용한다. 기존 관리자 비밀번호를 다시 설정할 필요도 없다.

```powershell
Set-Location 'C:\aws-msa-backend-terraform'
git diff -- app/msa
git add app/msa
git commit -m "Add admin operational dashboard"
git push origin main
```

Actions 이미지 빌드와 Argo CD의 새 버전 배포가 끝난 뒤 확인한다.

```powershell
kubectl get applications -n argocd
kubectl get pods -n soldesk
```

관리자로 로그인하고 `/admin.html`을 Ctrl+F5로 새로고침한다. 상품 등록이나 주문 후 새로고침하면 DB 집계가 달라져야 한다. Ready 노드·파드 수는 Prometheus 수집 시점 때문에 kubectl과 잠시 차이가 날 수 있다.

일반 회원은 `/member-service/member/admin/summary`를 호출해도 거부되어야 한다. Argo CD 카드가 확인 불가라면 아래 읽기 권한을 확인한다.

```powershell
kubectl auth can-i get applications.argoproj.io/final-apps -n argocd --as=system:serviceaccount:soldesk:member-dashboard
```

검증: 회원 서비스 Admin 테스트, Gateway 권한 테스트, 프런트엔드 대시보드·장바구니 테스트를 통과했다. 배포 후 실제 DB·Grafana·Prometheus·Kubernetes API 조회와 비인증 요청 차단도 확인했다. 최초 화면 미리보기에는 테스트용 예시값을 사용했다.

---

관리자 페이지·장바구니·운영자 주문 알림은 배포 후 동작을 확인했다. 아래 내용은 환경을 다시 준비하거나 설정을 변경할 때 참고할 절차다.

프로젝트 설명은 [README](../../README.md), 배포 흐름은 [배포 자동화](../../docs/02-deployment.md)를 참고한다.

## 바뀐 기능

- 상품별 수량 선택 → 장바구니 → 여러 상품 주문. 장바구니는 계정별로 현재 브라우저에 저장한다.
- 주문과 실제 재고 금액은 서버에서 계산한다. 상품 재고를 변경할 때 DB 행 잠금을 사용한다.
- 기존 API를 활용해 상품별로 별도 주문한다. 전체 상품을 한 번에 취소하는 거래는 아니다. 성공한 상품만 장바구니에서 제거하고 실패한 상품은 남긴다.
- 상품별 주문 저장 후 기존 운영 SNS로 주문 번호, 상품명, 수량, 금액, 회원 번호를 알린다. 고객별 메일, SES, SQS 소비자는 추가하지 않는다.
- SNS 호출 오류는 로그에 남기고 이미 저장된 주문을 실패 처리하지 않는다. 알림 재전송을 보장하는 구성은 아니다.
- `/admin.html`에 상품 등록, Grafana, Argo CD 링크를 제공한다. Grafana와 Argo CD의 로그인은 각각 유지한다.
- 관리자 HTML과 상품 등록 HTML은 Nginx 인증 요청으로 보호하고, 상품 등록 API도 Gateway에서 ADMIN만 허용한다. 일반 회원의 관리자 메뉴는 숨긴다.
- 클라이언트가 보낸 사용자 ID/권한 헤더는 제거한다. 검증된 JWT의 값만 백엔드에 전달한다.
- 기존 공개 관리자 비밀번호를 제거했다. 관리자 Secret을 설정하지 않으면 관리자 로그인이 차단된다.

## 1. Terraform에 발행 권한 추가

사용자가 만들 파일: `C:\aws-msa-backend-terraform\terraform\order_email.tf`

```hcl
# 주문 서비스가 기존 운영 알림 SNS에만 발행할 수 있도록 허용
resource "aws_iam_role_policy" "order_email_notifications" {
  name = "${var.project_name}-order-email-notifications"
  role = "${var.project_name}-ordering-sns-role"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sns:Publish"]
      Resource = module.monitoring.alerts_topic_arn
    }]
  })

  # IAM 역할을 생성한 뒤 정책 연결
  depends_on = [module.messaging]
}
```

같은 PowerShell 창에서 입력값 준비 후 실행한다.

```powershell
Set-Location 'C:\aws-msa-backend-terraform\terraform-k8s'
.\Prepare-Secrets.ps1
Set-Location 'C:\aws-msa-backend-terraform\terraform'
terraform fmt order_email.tf
terraform validate
terraform plan "-out=order-email.tfplan"
# 위 정책 하나만 추가되는지 검토한 뒤 실행. 다른 변경이 있으면 먼저 확인.
terraform apply "order-email.tfplan"
```

기존 `Final-order-events` 토픽 → SQS 연결은 그대로다. 이번 운영자 주문 메일은 SQS에 메시지를 쌓지 않도록 `Final-operations-alerts` 토픽으로 직접 발행한다. 이미 승인한 운영 알림 이메일 구독을 사용한다.

## 2. 관리자 비밀번호 준비

파일: `C:\aws-msa-backend-terraform\app\msa\Prepare-Admin.ps1`

```powershell
Set-Location 'C:\aws-msa-backend-terraform\app\msa'
.\Prepare-Admin.ps1
```

직접 실행을 막는 PowerShell 실행 정책 오류가 나오면 현재 창에만 적용한다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\Prepare-Admin.ps1
```

이 스크립트는 Secret만 설정하고 앱을 재시작하지 않는다. 이후 새 앱 배포 때 회원 서비스가 비밀번호를 적용한다. 아이디는 `admin`이다. 비밀번호는 Git, 파일, 명령줄 인수에 저장하지 않는다. 클러스터를 삭제하고 다시 만들면 Secret도 다시 준비해야 한다. 기존 admin의 이메일은 유지하고, 계정이 없을 때만 `admin@syong.store`를 사용한다. 이 주소로 메일은 발송하지 않는다.

## 3. 앱 배포

```powershell
Set-Location 'C:\aws-msa-backend-terraform'
git diff -- app
git add app/msa
git commit -m "Add simple cart, admin access and order notifications"
git push origin main
```

GitHub Actions 빌드와 이미지 태그 업데이트 후 Argo CD가 배포한다. 이미지 태그를 수동으로 바꾸지 않는다. 이번 변경 때문에 `terraform-k8s apply`를 할 필요는 없다.

## 4. 확인

1. `kubectl get applications -n argocd`에서 Synced / Healthy, `kubectl get pods -n soldesk`에서 전부 Ready 확인.
2. 기존 로그인은 로그아웃 후 다시 로그인. 관리자 쿠키는 HTTPS에서만 사용하며 한 시간 후 재로그인이 필요하다.
3. 일반 회원: 관리자 메뉴가 없어야 한다. `/admin.html`, `/product-create.html` 직접 접근도 로그인 또는 권한 안내 화면으로 이동해야 한다. 상품 등록 API는 403이어야 한다.
4. 관리자: `admin`과 새 비밀번호로 로그인. 관리자 화면에서 상품 등록 및 두 운영 도구 링크를 확인한다. 운영 도구 자체는 각 계정으로 로그인한다.
5. 서로 다른 상품 두 개를 각각 여러 수량으로 담아 주문한다. 성공 안내, 재고 감소, 상품별 운영자 SNS 메일을 확인한다.
6. 장바구니 수량을 실제 재고보다 크게 설정하면 해당 상품만 실패하고 장바구니에 남아야 한다.

알림 오류 확인:

```powershell
kubectl logs deployment/ordering-depl -n soldesk --since=10m
```

## 실습 범위

- 결제, 배송, 주문 이력 화면, 고객별 이메일은 포함하지 않는다.
- 장바구니 가격은 표시용이며 실제 주문 알림 금액은 서버가 조회한 가격을 사용한다.
- 주문 서비스와 상품 서비스의 DB 작업은 서로 별도 트랜잭션이다. 분산 트랜잭션이나 자동 보상 처리는 추가하지 않았다.
- 응답을 받기 전에 네트워크가 끊겼다면 주문이 저장되었을 수 있다. 다시 주문하기 전에 로그/DB를 확인한다. 중복 주문 방지 키는 이번 실습 범위에 포함하지 않는다.
- Grafana/Argo CD 도메인을 아는 사용자는 각 로그인 화면에 접속할 수 있다. 스토어 관리자 페이지 보호와 운영 도구 자체의 인증은 별개다.

## 로컬 검증

DB/AWS 접속 없이 새 기능의 테스트만 실행한다. 기존 전체 SpringBootTest는 실제 DB 설정이 필요하므로 이 검증에 포함하지 않았다.

```powershell
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17'
Set-Location 'C:\aws-msa-backend-terraform\app\msa\apigateway'
.\gradlew.bat test --tests '*JwtAuthFilterTest'
Set-Location 'C:\aws-msa-backend-terraform\app\msa\member'
.\gradlew.bat test --tests '*AdminAccessTest'
Set-Location 'C:\aws-msa-backend-terraform\app\msa\ordering'
.\gradlew.bat test --tests '*OrderFeaturesTest'
Set-Location 'C:\aws-msa-backend-terraform\app\msa\product'
.\gradlew.bat test --tests '*StockConcurrencyTest'
Set-Location 'C:\aws-msa-backend-terraform\app\msa\frontend'
node --test tests/cart.test.cjs
```

재고 동시성은 H2에서 검증하며 운영 MySQL 검증을 대체하지 않는다. Nginx 이미지 빌드, 설정 검사, 인증 하위 요청을 이용한 게스트/일반 회원 차단과 관리자 허용은 로컬 Docker에서 확인했다. 이후 실제 배포와 운영자 주문 메일 수신도 실습으로 확인했다.
