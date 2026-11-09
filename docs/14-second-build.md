> **과거 기록의 적용 범위** · 아래는 당시 코드·계정·브랜치·준비 상태를 보존한 원문입니다. 현재 main의 실행 안내는 [README](../README.md), 실제 완료 범위는 [최신 검증 정리](21-current-validation.md)를 사용하세요. “미실행/예정”은 작성 당시 기준입니다.

# 2차 빌드 — 같은 AWS 리소스, 설치·운영·삭제의 빈틈 보완

> 아래 수동 절차와 미확인 목록은 작성 당시 기록입니다. 10월 21일 실제 설치·보존·복원·전체 삭제 결과와 새 재시도 변경의 검증 범위는 [최신 검증 기록](17-validation-20261021.md)을 기준으로 확인하세요.

# 자동 실행 안내

현재 실행 시작점은 [설치·검증·삭제 PS1](15-one-command-lab.md)입니다. 아래는 2차 빌드의 **수동 단계 참고**이며, 새 PS1과 섞어서 동시에 실행하지 않습니다. 최초 설치 커밋 고정, 관리자 주문 알림, state 버킷까지 삭제하는 절차는 새 가이드를 따릅니다.


2026-10-20 준비 코드입니다. **이 변경으로 AWS를 생성하거나 삭제하지 않았습니다.** 아래 명령은 앞으로 학원 PC에서 한 단계씩 실행할 실습 순서예요. 한 명령이 실패하면 다음 명령으로 넘어가지 말고 결과부터 확인합니다.

## 바뀐 범위

| 항목 | 이번 변경 | 실제 구축 후 확인 |
|---|---|---|
| 노드 | 모두 t3.medium. a 최소/시작/최대 1/1/3, c 2/2/3 | 시작 3대, 확장 최대 6대. CA가 바꾼 현재 수는 재apply로 되돌리지 않음 |
| AZ 배치 | 기존 배치 유지. CA·Alertmanager=a, Grafana·Prometheus=c의 서로 다른 노드 | PVC AZ, 노드 라벨, 두 c 노드의 분산 확인 |
| 첫 설치 | LBC 배포·EndpointSlice·서버 dry-run 확인 후 의존 차트 진행. ESO Ready 후 앱 등록 | webhook 지연·IRSA 실패 시 apply 중단과 재개 |
| 이미지 | main의 마지막 push 차이가 아니라 서비스별 마지막 이미지 소스부터 비교 | 이전에 게시 실패한 서비스가 다음 실행에도 포함되는지 |
| DB TLS | 세 서비스 `sslMode=VERIFY_IDENTITY`. 공식 서울 RDS CA를 Java 신뢰 저장소에 포함 | 새 연결 성공 및 실제 DB 세션 암호화 |
| 비밀번호 전달 | 1분 CronJob → 변경 감지 → Member→Product→Ordering 순차 갱신 | ESO→Secret→새 Pod→DB readiness. 실패 시 다음 서비스는 중단 |
| 삭제 | 정확한 PVC/EBS 목록 저장 → 앱/Ingress → 모니터링/PVC → ALB/EBS 없음 확인 → 도구 → AWS | 다른 리소스 제외, 실패 조회를 ‘없음’으로 오판하지 않는지 |
| 협업 | 최초 설치는 승인 없이. 이후 이미지 게시 후 배포 PR 승인→병합→Argo 반영 | 팀원 초대 수락·1명 이상 다른 사람 승인·직접 main push 차단 |

새 AWS 서비스는 추가하지 않았습니다. Terraform `terraform_data`는 AWS 리소스가 아니라 준비 확인 결과를 추적하는 state 항목입니다. Kubernetes CronJob·ConfigMap·최소 RBAC는 기존 노드에서 실행됩니다.

**이전 실행의 한계:** 당시에는 RDS Single-AZ·NAT 1개였습니다. 신규 구축 준비안은 AZ별 NAT와 RDS Multi-AZ로 변경했으며 AWS 실측은 아직입니다([촬영 계획](19-ha-release-evidence.md)). c AZ에 고정된 모니터링 EBS와 t3의 지속 CPU 부하/크레딧 제약은 남습니다. 실제 자원 수와 시간에 따라 비용이 발생합니다.

## 0. 내려받기와 준비

처음에는 검증된 변경 브랜치/커밋을 확인하고 받습니다. 실제 설치 전 main에 병합된 최종 커밋을 사용할 예정이며, 서로 다른 PC에서 동시에 Terraform을 실행하지 않습니다.

```powershell
git clone https://github.com/yobi84-sy/aws-msa-final-test2.git
Set-Location .\aws-msa-final-test2
git switch main
git pull --ff-only
git rev-parse HEAD
aws --version
terraform version
kubectl version --client
helm version --short
python --version
gh auth status
# 현재 창에서 로컬 스크립트 실행이 Restricted로 막힌 경우에만
Set-ExecutionPolicy -Scope Process RemoteSigned
python -m pip install PyYAML==6.0.3
python scripts/ops/verify_lab.py identity
& .\scripts\ops\New-LabConfig.ps1
```

AWS CLI profile은 `eks-user`, 계정은 `021158485482`, 리전은 서울입니다. 설정 스크립트는 현재 학교 공인 IP와 입력한 IAM ARN·이메일로 **무시 대상 terraform.tfvars만** 만듭니다. 리소스는 만들지 않습니다. 계정·도메인이 다른 과거 문서는 실행 안내로 사용하지 마세요. VPN/공인 IP가 바뀌면 API 허용 CIDR도 검토해야 합니다.

## 1. state → AWS 기반 구성

버킷이 이미 있으면 소유/기존 state를 확인하고 import 여부를 먼저 결정합니다. 기존 bootstrap local state는 안전하게 보관하고, 실제 tfvars·state·토큰은 Git에 올리지 않습니다.

```powershell
terraform -chdir=terraform-state-bootstrap init
terraform -chdir=terraform-state-bootstrap plan -out=bootstrap.tfplan
# 추가/삭제 범위·계정을 직접 확인한 뒤에만 실행 (과금 작업)
terraform -chdir=terraform-state-bootstrap apply bootstrap.tfplan
terraform -chdir=terraform init
terraform -chdir=terraform plan -out=infra.tfplan
# 노드 a=1/c=2, medium, 기존 zone 재사용, 예상하지 않은 삭제 없음 확인
terraform -chdir=terraform apply infra.tfplan
python scripts/ops/verify_lab.py infra --report .lab/infra.json
aws eks update-kubeconfig --name Final-eks --region ap-northeast-2 --profile eks-user
kubectl get nodes -L final-node-pool,node.kubernetes.io/instance-type
```

plan 파일은 민감할 수 있어 공유하지 않습니다. 성공 문구뿐 아니라 실제 API 조회가 PASS여야 다음 단계로 갑니다. 신규 준비안의 infra 검사는 NAT 2개·AZ별 경로와 RDS Multi-AZ의 대기 AZ도 확인합니다.

## 2. 이미지와 도구 준비 → 앱 활성화

처음 infra/ECR 준비 전에는 이미지 게시를 실행하지 않습니다. Actions 기본값은 테스트만 하며, AWS 게시는 명시적으로 켭니다.

```powershell
# infra output이 만든 현재 역할 ARN을 repository variable에 연결
$role = terraform -chdir=terraform output -raw github_actions_role_arn
gh variable set AWS_ROLE_TO_ASSUME --repo yobi84-sy/aws-msa-final-test2 --body $role
# main에 이번 코드가 준비된 뒤 최초 전체 빌드·게시 (실제 ECR 쓰기)
gh workflow run build-push.yml --repo yobi84-sy/aws-msa-final-test2 --ref main -f full_build=true -f publish_images=true
gh run list --workflow build-push.yml --limit 3
```

CI 성공 → ECR에 5개 게시 → 생성된 release PR의 digest 확인 → 최초 release 병합 순서입니다. 최초에는 아직 승인 강제 설정을 켜지 않습니다. Actions 저장소 설정에서 **Allow GitHub Actions to create and approve pull requests**가 꺼져 있으면 PR 생성이 실패합니다. PR *생성* 허용이며 봇 자체 승인을 요구하는 정책은 아닙니다. GITHUB_TOKEN이 만든 PR은 PR 이벤트 검사가 자동 시작되지 않을 수 있어, 이번에는 봇 PR 생성 후 `build-push.yml`을 해당 release 브랜치에 명시적으로 dispatch해 required-ci를 실행합니다(AWS 게시=false). GitHub App 토큰이 있으면 기존 PR 이벤트 경로를 사용합니다. dispatch가 거부되면 Actions 권한을 확인하고 `gh workflow run build-push.yml --ref <release-브랜치> -f full_build=false -f publish_images=false`로 다시 검사합니다. [배포 승인 안내](11-test2-delivery.md)도 확인하세요.

```powershell
& .\terraform-k8s\Prepare-Secrets.ps1
Copy-Item .\terraform-k8s\test2.tfvars.example .\terraform-k8s\terraform.tfvars
terraform -chdir=terraform-k8s init
terraform -chdir=terraform-k8s plan -out=tools.tfplan
terraform -chdir=terraform-k8s apply tools.tfplan
python scripts/ops/verify_lab.py tools --report .lab/tools.json
```

Prepare-Secrets는 **같은 PowerShell 창에서** 실행합니다. 별도 `powershell -File` 창에서 실행하면 ephemeral 입력 환경 변수가 현재 창에 남지 않습니다. 창을 바꾸면 다시 준비합니다. JWT/내부 토큰은 기존 Secret이 있으면 재사용합니다. 현재 공개 저장소는 Argo에서 익명으로 읽으므로 GitHub 토큰을 요구하지 않습니다. 나중에 비공개로 바꾸면 `-PrivateRepository`로 실행하고 `github_repository_public=false`를 사용합니다. 이때 토큰은 화면·명령 인수·파일에 쓰지 않고, 읽기 토큰 변경 시 `github_token_revision`도 올립니다.

아직 `enable_app_sync=false`, `enable_management_ingress=false`입니다. LBC/ESO gate가 실패하면 앱을 켜지 말고 원인을 해결한 뒤 같은 단계 plan/apply를 다시 합니다. gate 스크립트는 임시 kubeconfig로 대상 클러스터를 확인하며 기존 kubeconfig를 덮어쓰지 않습니다. **Terraform gate가 이미 성공한 이후의 상태도 아래 조회로 다시 확인**합니다.

```powershell
python scripts/ops/wait_webhook.py --cluster Final-eks --profile eks-user --region ap-northeast-2
python scripts/ops/wait_database_secret.py
& .\app\msa\Prepare-Admin.ps1
```

`Prepare-Admin.ps1`은 관리자 이메일과 비밀번호를 입력받아 Kubernetes Secret에 저장합니다. 이메일은 Git에 저장하지 않습니다. SES 샌드박스에서는 인증된 수신 주소를 사용하세요. 이메일은 회원 간 중복을 허용하지 않으므로 일반 회원 가입에 사용한 주소와 구분해야 합니다. 별도 주소를 쓰면 SES 인증도 확인하세요.

관리자 화면은 `https://server.sy84.store/admin.html`입니다. `admin.sy84.store` 호스트나 이메일 수신용 메일함을 생성하는 구성은 없습니다. 주문 확인 메일은 주문자 계정의 이메일로 발송되며 운영 장애 알림과는 별개입니다.

업데이트된 Member 이미지가 배포된 상태에서는 이 스크립트를 다시 실행한 후 `kubectl rollout restart deployment/member-depl -n soldesk`와 `kubectl rollout status deployment/member-depl -n soldesk --timeout=300s`로 기존 관리자 이메일·비밀번호를 갱신할 수 있습니다. 중복 이메일이면 앱 시작을 중단하므로 먼저 다른 회원과 겹치지 않는 주소를 선택하세요. 기존 주문에 저장된 수신 주소는 변경되지 않습니다.

5개 이미지·ESO Ready·관리자 초기 Secret을 확인한 후 `terraform-k8s/terraform.tfvars`의 두 enable 값을 true로 변경하여 새 plan/apply를 실행합니다. 관리자 bootstrap은 기존 안내의 명령을 그대로 사용하고, 비밀번호를 메신저/로그로 공유하지 않습니다.

```powershell
terraform -chdir=terraform-k8s plan -out=apps.tfplan
terraform -chdir=terraform-k8s apply apps.tfplan
kubectl get application final-apps -n argocd
kubectl get pods -n soldesk
python scripts/ops/verify_lab.py load-balancers --report .lab/lb.json
```

추가 LB가 보이면 중단해 태그·Ingress·LoadBalancer Service와 매칭합니다. 코드상 공유 ALB 하나라는 이유로 두 번째 LB를 임의 삭제하지 않습니다. ALB/대상 그룹 healthy 뒤 `terraform/terraform.tfvars`에서 website/management DNS를 true로 바꾸고 새 plan/apply를 실행합니다. ACM CNAME은 인증용, 서비스 A Alias는 ALB 연결용입니다.

```powershell
terraform -chdir=terraform plan -out=dns.tfplan
terraform -chdir=terraform apply dns.tfplan
$revision = git rev-parse origin/main
python scripts/ops/check_release.py --revision $revision
```

이 검사는 정확한 Argo revision·5개 이미지·준비 복제 수·HTTPS·HTML·상품 API를 봅니다. 로컬 checkout도 해당 revision의 배포 선언과 같아야 해요. 예전 digest는 **삭제된 ECR에 남아 있지 않습니다.** 새 전체 게시·release 병합 전에는 앱을 켜지 않습니다.

## 3. DB 비밀번호 자동 전달과 TLS

### Windows에서 readiness 경로 오류가 났던 경우

2026-10-20 학교 PC 첫 실행에서 `cmd /C`를 경유한 local-exec가 상대 경로의 따옴표를 잘못 전달했습니다. 이제 Python을 직접 interpreter로 실행하고 절대 경로·인수를 환경 변수로 전달합니다. 두 gate를 같은 방식으로 수정했으며 Windows/Python 3.12 CI와 provider 없는 실제 local-exec 테스트로 검사합니다.

이 오류로 멈췄다면 인프라를 삭제하거나 기존 `tools.tfplan`을 다시 적용하지 마세요. 같은 PowerShell 창에서 `git pull --ff-only origin main` 후 `terraform "-chdir=terraform-k8s" plan "-out=tools-resume.tfplan"`으로 **새 계획**을 확인합니다. 실패한 `terraform_data`는 재생성으로 나올 수 있지만 AWS 리소스 삭제와는 다릅니다. 교체 대상 주소를 확인한 후 새 plan으로 재개합니다. 설치된 리소스를 초기화하거나 state를 지울 필요는 없습니다.

공식 CA 원본: https://truststore.pki.rds.amazonaws.com/ap-northeast-2/ap-northeast-2-bundle.pem

2026-10-20 포함한 공개 인증서 번들의 SHA256: `913fb5b814f17af79d4c1622584a8d0ceddf5b0d76fe353d0c7d1186cdd6b229`. 세 서비스 Dockerfile에서 개별 인증서를 Java 기본 cacerts에 등록합니다. `changeit`은 공개 CA 신뢰 저장소의 기본 비밀번호이며 DB 비밀번호가 아닙니다. 향후 RDS CA 교체 시 번들 출처·체크섬을 재확인해 이미지도 갱신해야 합니다.

```text
RDS 관리 비밀번호 변경 → Secrets Manager AWSCURRENT
→ ESO(1분) → db-credentials Secret
→ CronJob(1분, 중복 실행 금지)
→ 값 fingerprint 비교 → Member 새 Pod/DB Ready
→ Product 새 Pod/DB Ready → Ordering 새 Pod/DB Ready
```

Secret resourceVersion만 바뀌면 재시작하지 않습니다. annotation이 없는 첫 실행에서는 기준을 만들며 한 번 순차 롤아웃합니다. Argo는 이 annotation만 제외하고 image 등 나머지는 계속 관리합니다. Worker 권한은 해당 Secret get과 해당 3개 Deployment get/patch로 제한합니다. 비밀번호·fingerprint·토큰을 출력하지 않습니다.

실패하면 다음 서비스를 멈추고 다음 CronJob에서 재시도합니다. 최근 실패 Job은 기존 Prometheus→Alertmanager→SNS 경로로 경보를 보냅니다. 이 경로 자체가 중단되면 경보도 전달되지 않으므로 Job 직접 조회도 필요합니다.

**무중단 회전을 보장하는 구조는 아닙니다.** 단일 DB 사용자 비밀번호가 먼저 바뀌므로 기존 Pod의 새 연결이 갱신 전 실패할 수 있습니다. ESO/일정 대기와 순차 시작 시간도 걸립니다. 별도 사용자를 번갈아 쓰는 방식은 이번 범위에 없습니다. 영향 있는 회전 시험은 별도 합의 후 진행합니다.

Member 기존 관리자 요약 API에 `database.tlsEncrypted`를 추가했습니다. 로그인 후 관리자 요약에서 true인지 봅니다. 단순 HTTPS 성공이 아니라 **Member의 실제 MySQL 세션**을 조회한 값입니다. Product·Ordering은 각각 새 Pod의 DB readiness와 VERIFY_IDENTITY 연결 성공을 추가 확인합니다. 모든 서비스의 개별 세션 증명을 동일하게 수집한 것은 아닙니다.

## 4. 팀 승인 — 최초 설치 검증 이후

```powershell
# 미리보기만 (초대나 보호 설정을 바꾸지 않음)
& .\scripts\github\Invite-Team.ps1
& .\scripts\github\Set-ReviewRules.ps1
# 실제 설치 완료 후, 팀과 함께 실행
& .\scripts\github\Invite-Team.ps1 -Apply -InitialInstallVerified
# 팀원 수락·write 권한 및 required-ci 실행 확인 후
& .\scripts\github\Set-ReviewRules.ps1 -Apply -InitialInstallVerified
gh variable set ENABLE_IMAGE_PUBLISH --repo yobi84-sy/aws-msa-final-test2 --body true
```

대상: yunjun1208, yonginfra, yjeee-ghub / 소유자 yobi84-sy. 이메일 대신 GitHub 로그인 ID를 사용합니다. 준비한 보호 규칙은 **다른 사람 1명 승인**, 새 push 시 승인 재검토, required-ci 성공, 관리자 포함 직접 push·강제 push 차단입니다. 초대 수락과 실제 차단은 배포 후 확인합니다. 아직 이 설정은 적용하지 않았습니다.

이후: 작업 브랜치 → 소스 PR → 테스트·검토·병합 → 이미지 ECR 게시 → **배포 선언 PR** → 다른 팀원 승인·병합 → Argo 실제 서비스 반영입니다. ECR에 게시했다는 이유만으로 live 이미지가 바뀌지 않습니다. 배포 YAML·인프라 변경 역시 main 보호를 받지만, 인프라 apply는 별도 로컬 절차입니다.

GitHub hosted runner는 학교 IP만 허용한 EKS API에 접근할 수 없습니다. 기존 `deploy-check`의 ENABLE_DEPLOY_CHECKS는 접근 경로가 준비되기 전 켜지 않습니다. 지금은 허용된 학교 PC에서 check_release/verify_lab을 실행합니다. 기존 PC를 runner로 쓰는 방식은 별도 보안 검토 후 선택할 수 있고 이번에 자동 설치하지 않았습니다.

## 5. 2차 실습 체크리스트

`[ ]`는 아직 실제 2차 AWS 검증 전입니다. 일반 조회 → 쓰기 → 영향 시험 순서로 진행하고, 각 결과·시간·커밋을 `.lab/` 또는 공유용 비밀 제거 보고서에 남깁니다.

| 구분 | 검사 / 명령 또는 방법 | 정상 기준 | 실패 시 먼저 확인 |
|---|---|---|---|
| 조회 [ ] | verify_lab identity / infra | 계정 일치, EKS·RDS available, 노드그룹 min/max 일치 | profile, ARN, region, state |
| 조회 [ ] | `aws ec2 describe-subnets --filters Name=vpc-id,Values=<VPC> --profile eks-user`; 동일 VPC route-tables/security-groups 조회 | public→IGW, private→NAT, DB 비공개. DB3306은 앱 경로만 | 라우트 association·SG source·NACL |
| 조회 [ ] | verify_lab tools; `kubectl get pods -A -o wide`; `kubectl get pv` | 노드 Ready, PVC Bound, c 모니터링 별도 호스트, a 고정 준수 | Pending events·EBS AZ·requests·IP 슬롯 |
| 조회 [ ] | verify_lab load-balancers; `kubectl get ingress,svc -A` | 공유 ALB/모든 대상 healthy, 추가 LB 소유 파악 | controller events, tags, SG, health path |
| 조회 [ ] | `Resolve-DnsName server.sy84.store`; argocd/grafana도 조회, HTTPS 직접 접속 | 서비스 A Alias가 해당 ALB, 인증서 호스트·체인·만료 정상 | authoritative NS, Alias, listener ACM, TTL |
| 조회 [ ] | check_release.py, `kubectl get hpa -n soldesk`, `kubectl top nodes` | 정확한 revision/digest, Ready, metrics 숫자 표시 | Argo sync/이미지 pull/readiness/metrics-server |
| 조회 [ ] | `kubectl get cronjob,job -n soldesk`; 최신 Job log | 최근 성공, 비밀 없는 로그. 3서비스 전달 완료 | RBAC, Secret key, Deployment progress |
| 쓰기 [ ] | 회원·상품·주문을 구분되는 실습 ID로 생성→조회, 관리자 DB 집계 전후 확인 | DB 행/재고 일치, 주문 중복 요청 재고 중복 차감 없음 | API 오류·DB 연결·transaction·outbox |
| 쓰기 [ ] | 상품 이미지 업로드→새로고침·S3 키 확인 | product IRSA로 저장, 정상 URL | IRSA 신뢰·버킷 prefix/정책 |
| 쓰기 [ ] | 실습 주문→Outbox→SNS/SQS→Lambda/SES→메일 | 주문 ID 일치, 중복 방지, DLQ 0 | SES sender/recipient 인증·Sandbox·SQS age·Lambda log |
| 영향 [ ] | `kubectl rollout restart deployment/member-depl -n soldesk`; rollout status | 기존 회원/주문 유지, 새 Pod에서 DB 재접속 | RDS 외 로컬 저장 여부·Secret·DB readiness |
| 영향 [ ] | 실제 읽기 부하 → HPA watch → Pending events → CA log/노드 watch | CPU 목표에 따라 Pod 증가, 용량 부족 시 올바른 AZ 증설, 중단 후 축소 | HPA max3, 그룹 각 max3, requests, EBS/분산 제한 |
| 영향 [ ] | RDS 관리 비밀번호 **별도 승인 후** 회전 → ESO/Job/3앱 관찰 | 값 노출 없이 갱신·순차 Ready·TLS 확인 | AWSCURRENT/ESO/IRSA·Job timeout·DB TLS |
| 영향 [ ] | 합의한 Pod 장애·잘못된 이미지 PR·이전 정상 release PR 복구 | 오류 탐지·잘못된 성공 없음·승인 후 이전 digest 회복 | Git/실제 이미지 차이, rollout, DB schema 호환 |
| 영향 [ ] | SNS 구독 확인 후 장애 규칙 발동·복구 | Alertmanager 및 이메일에 firing/resolved | Prometheus rule, route Final.*, IAM/SNS 구독 |
| 협업 [ ] | 팀원 PR 작성→실패 CI/미승인 병합 시도→다른 사람 승인 | 미승인·실패 시 차단, 승인 후 배포 PR만 live image 변경 | collaborator 수락·보호 규칙·봇 PR 검사 실행 |
| 삭제 [ ] | 아래 staged destroy + Get-ProjectResidue | 관리 대상 없음/의도적 보관 목록 별도 | finalizers·CloudTrail 지연 객체·권한/조회 실패 |

부하·노드 확장에는 추가 비용이 발생할 수 있고 Pod 교체·회전·장애 시험은 서비스에 영향을 줍니다. 자동 실행되지 않습니다. 다음 대화에서 한 항목씩 실행·확인할 예정입니다. RDS 복원/노드 종료 같은 더 큰 시험도 별도 승인 대상으로 남깁니다.

## 6. 삭제 — 컨트롤러가 자기 리소스를 정리할 시간을 주기

**데이터를 버릴지/백업할지 먼저 결정합니다.** 아래 discard-data는 실습 데이터·이미지·모니터링 기록·감사 로그 삭제를 선택한 경우에만 사용합니다. 보존을 선택하면 여기서 멈추고 백업/보존 범위를 먼저 정합니다. state 버킷·기존 Route53 zone·기존 SES ID는 이 helper가 삭제하지 않습니다.

```powershell
# 먼저 새 코드/Secret 준비가 끝난 동일 PowerShell 창인지 확인
python scripts/ops/destroy_lab.py capture
python scripts/ops/destroy_lab.py workloads  # 미리보기
# 아래부터는 실제 삭제. 원본 capture 파일은 덮어쓰지 않음
python scripts/ops/destroy_lab.py workloads --execute --discard-data
python scripts/ops/destroy_lab.py monitoring --execute --discard-data
python scripts/ops/destroy_lab.py wait
# ALB/EBS 잔존 시 중단. controller/CSI를 먼저 없애지 않음
python scripts/ops/destroy_lab.py storage --execute --discard-data
terraform -chdir=terraform-k8s plan -destroy -out=destroy-tools.tfplan
terraform -chdir=terraform-k8s apply destroy-tools.tfplan
# 없어진 ALB 주소를 data source가 찾지 않도록 두 DNS 플래그를 false로 덮어씀
terraform -chdir=terraform plan -destroy -var=enable_website_dns=false -var=enable_management_dns=false -out=destroy-infra.tfplan
terraform -chdir=terraform apply destroy-infra.tfplan
& .\scripts\ops\Get-ProjectResidue.ps1
```

각 명령이 성공한 다음에만 다음 줄을 실행합니다. monitoring 제거 후 **다시 일반 k8s apply를 실행하면 재설치될 수 있으므로 destroy 흐름만 계속**합니다. helper는 다른 LB, 다른 PVC, 불명확한 소유 대상을 임의 삭제하지 않고 멈춥니다. PV reclaim=Delete인지 먼저 확인하고 정확히 캡처한 EBS만 ‘사라졌는지’ 조회합니다. EBS 직접 강제 삭제는 하지 않습니다.

storage 단계는 정확한 두 데이터 버킷과 5개 ECR만 비웁니다. CloudTrail을 먼저 정지하고 객체별 오류도 검사합니다. 늦게 도착한 로그 때문에 BucketNotEmpty가 나오면 같은 storage 단계를 다시 실행한 뒤 **새 destroy plan**을 확인합니다. 이미 삭제된 bucket/repo/trail은 성공한 목록 조회로 구분합니다. AccessDenied는 정리 완료가 아닙니다. RDS가 이 단계에서 없어지므로 회복 불가능한 데이터 삭제 여부를 반드시 먼저 결정합니다.

state는 마지막 검증이 끝날 때까지 보관합니다. bootstrap은 별도 local state와 prevent_destroy를 사용합니다. 버킷만 콘솔에서 지워버리면 이후 Terraform 추적/복구가 어려워져요. 완전 초기화는 두 root state가 비었고 잔여 점검이 끝난 뒤 별도 절차로 다룹니다.

## 실행 증거를 남기는 기준

- **코드/오프라인 확인:** Terraform validate/mock plan, manifest render, worker 실패·재시도 회귀, 서비스 테스트/이미지 빌드.
- **1차 실제 결과:** docs/13-account-deployment-validation.md의 기록. 현재 변경의 성공 증거로 재사용하지 않습니다.
- **2차 미확인:** AWS 새 plan 범위, 실제 webhook/ESO gate, TLS 세션, rotation, ALB 개수/태그, scaling·메일·삭제 전 과정. 위 체크가 통과한 뒤에만 실제 검증 완료로 바꿉니다.
