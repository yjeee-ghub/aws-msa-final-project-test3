> **과거 기록의 적용 범위** · 아래는 당시 코드·계정·브랜치·준비 상태를 보존한 원문입니다. 현재 main의 실행 안내는 [README](../README.md), 실제 완료 범위는 [최신 검증 정리](21-current-validation.md)를 사용하세요. “미실행/예정”은 작성 당시 기준입니다.

> **이전 실행/장애 기록 보관용입니다.** 현재 2차 구축은 [새 실행 가이드](14-second-build.md)를 사용하세요. 여기의 과거 계정·도메인·small 노드 수치는 현재 실행값이 아닙니다.

# 월요일 학원 PC 실행 순서 (PowerShell)

개선 코드는 test에서 실제 검증한 뒤 main으로 승격했다. 현재 test는 개선 전 main의 보관용이며, **기본 실행 코드는 main**이다. 실제 계정 상태·비용·보관할 데이터를 확인한 뒤 필요한 단계만 실행한다. 이미 정상 실행 중이면 재구축·삭제 절차를 반복하지 않는다. 실제 검증 결과는 [적용 기록](10-live-validation.md)을 참고한다.

## 0. 공통 준비와 브랜치 경계

PowerShell 7, Git/Git Bash, Terraform 1.12 이상 2 미만(로컬 확인 버전 1.13.5), AWS CLI v2, kubectl, Helm, JDK 17, Node.js, Python 3, Docker가 필요하다. AWS CLI의 `default` 프로필을 준비한다. 비밀번호·토큰은 콘솔 보안 입력으로만 받고, tfstate·tfplan·개인 tfvars·환경 변수 덤프를 Git에 올리지 않는다.

```powershell
Set-Location 'C:\aws-msa-backend-terraform'
git fetch origin
git switch main
git pull --ff-only origin main
git status --short
$env:AWS_PROFILE = 'default'
$env:AWS_REGION = 'ap-northeast-2'
terraform version
aws sts get-caller-identity --profile default
# Account가 143710973003인지 직접 확인하고 다르면 중단
```

기존 리소스가 있으면 **1번 삭제 절차부터**, 완전히 비어 있으면 **2번 초기 구축부터** 진행한다. 보관할 데이터가 있다면 삭제 전에 별도 백업한다. 기존 state를 유지한 채 전환하려면 삭제 절차 대신 [state 이전 안내](07-terraform-state.md)의 절차를 사용한다. 빈 state로 기존 AWS 리소스 위에 apply하지 않는다.

## 1. 기본 재구축: 기존 환경을 먼저 삭제

삭제는 **기존 state를 실제로 관리하던 코드·폴더·프로필**에서 수행한다. 기존 local state 환경이라면 당시 관리하던 코드와 폴더를 사용한다. 이미 S3로 전환한 현재 환경에서는 해당 backend 설정이 있는 main을 유지한다. Terraform workspace는 default를 사용하며 다른 workspace state는 먼저 별도 확인한다.

```powershell
# 기존 local state를 사용하던 경우에만: 저장소 작업이 깨끗한 상태에서 전환
# git switch main
terraform -chdir=terraform workspace show
terraform -chdir=terraform state list
terraform -chdir=terraform-k8s state list
# 기존 클러스터가 있어야 Prepare-Secrets가 동작한다.
aws eks update-kubeconfig --name Final-eks --region ap-northeast-2 --profile default
. ./terraform-k8s/Prepare-Secrets.ps1
```

먼저 Argo 자동 동기화를 끄고, 앱 리소스의 정리가 끝날 때까지 **ALB Controller와 EKS를 유지**한다. 단순히 EKS부터 삭제하면 ALB·ENI·EBS 등이 남을 수 있다.

```powershell
# 사용하던 tfvars 및 관리 ingress 설정을 유지하며, 앱 자동 동기화만 끈다.
terraform -chdir=terraform-k8s plan -var='enable_app_sync=false'
terraform -chdir=terraform-k8s apply -var='enable_app_sync=false'
# Terraform이 만든 Application의 finalizer로 GitOps 앱 자원을 정리한다.
kubectl delete application final-apps -n argocd --wait=true --timeout=10m
kubectl get ingress -A
kubectl get pods -n soldesk
# 컨트롤러가 살아 있는 동안 앱 Ingress의 ALB 대상 등이 정리됐는지 확인한다.
terraform -chdir=terraform-k8s plan -destroy -var='enable_app_sync=false'
terraform -chdir=terraform-k8s destroy -var='enable_app_sync=false'
# 공유 ALB 삭제 완료 확인: 조회 오류는 원인을 확인하고, 무조건 '없음'으로 보지 않는다.
aws elbv2 describe-load-balancers --region ap-northeast-2 --profile default
```

`terraform-k8s`가 끝난 다음 `terraform`을 삭제한다. DNS가 ALB를 조회하는 구성이므로, ALB가 없어졌다면 아래 두 플래그를 false로 넘겨 기존 data 조회를 막는다. 해당 DNS 레코드들은 destroy에서 제거된다. ECR은 `force_delete=false`, 상품·CloudTrail S3는 `force_destroy=false`여서 내용이 있으면 삭제가 거부된다.

```powershell
# DB 비밀번호가 같은 창에 남아 있어야 한다. 필요하면 아래 3번의 보안 입력을 사용한다.
terraform -chdir=terraform plan -destroy -var='enable_website_dns=false' -var='enable_management_dns=false'
terraform -chdir=terraform destroy -var='enable_website_dns=false' -var='enable_management_dns=false'
./scripts/ops/Get-ProjectResidue.ps1
```

내용 때문에 destroy가 실패하면 **해당 오류의 프로젝트 자원만** 확인하고 정리한 뒤 동일 destroy를 다시 실행한다. 예시는 다음과 같다. 아래 삭제는 데이터가 필요 없다는 판단 후에만 수동 실행한다.

```powershell
# 상품 객체 확인 → 필요 시 별도 백업 → 상품 버킷만 비우기
aws s3 ls s3://final-product-images-143710973003-ap-northeast-2/ --recursive
# aws s3 rm s3://final-product-images-143710973003-ap-northeast-2/ --recursive
# CloudTrail이 남아 있다면 로그 생성 중지 후 보관할 로그 백업, 버킷 내용 확인
# aws cloudtrail stop-logging --name Final-management-trail --region ap-northeast-2
aws s3 ls s3://final-cloudtrail-143710973003-ap-northeast-2/ --recursive
# aws s3 rm s3://final-cloudtrail-143710973003-ap-northeast-2/ --recursive
# ECR은 각 저장소의 imageIds를 먼저 보고 필요한 이미지 보관 후 batch-delete-image로 명시적 선택 삭제
aws ecr list-images --repository-name member-service --region ap-northeast-2
# aws ecr batch-delete-image --repository-name member-service --image-ids imageDigest=sha256:<확인한-digest> --region ap-northeast-2
```

나머지 4개 ECR도 동일하게 점검한다. S3 버전 관리가 별도로 켜진 환경에서는 `s3 rm`만으로 과거 버전·delete marker가 없어지지 않는다. S3 콘솔의 버전 목록에서 대상 버킷을 확인해 별도 정리한다. **state 버킷에는 이 명령을 사용하지 않는다.** 잔여 PVC/EBS, RDS 실습 DB·수동 스냅샷이 있으면 네트워크 삭제 전에 정리 여부를 결정한다. state는 모든 destroy와 잔여 확인이 끝날 때까지 보존한다.

```powershell
# 기존 state에 관리 리소스가 남지 않았는지 양쪽 확인
terraform -chdir=terraform-k8s state list
terraform -chdir=terraform state list
# 두 state가 비었고 실제 자원 정리도 끝난 뒤 개선 코드로 이동
git switch main
```

## 2. state 전용 버킷 (최초 한 번만)

이미 보관 버킷과 bootstrap local state가 있다면 init/plan으로 확인하고 재사용한다. 같은 이름 버킷이 있지만 bootstrap state를 잃었다면 새로 생성하지 말고 [import 안내](07-terraform-state.md)를 따른다.

```powershell
terraform -chdir=terraform-state-bootstrap init
terraform -chdir=terraform-state-bootstrap validate
terraform -chdir=terraform-state-bootstrap plan
terraform -chdir=terraform-state-bootstrap apply
```

이 폴더는 다른 두 루트에서 참조하는 module이 아니다. 프로젝트 destroy에 포함되지 않으며 버킷 자체에 `prevent_destroy`도 있다. bootstrap의 local state는 접근 제한된 백업에 별도 보관한다. 비어 있는 기존 local state 파일은 백업 후 활성 경로 밖으로 옮기고 초기화한다. **리소스가 남은 state는 옮기지 말고 이전 안내를 따른다.**

## 3. AWS 기본 인프라 먼저 (`terraform`)

개인 `terraform/terraform.tfvars`에는 EKS 관리 IP `/32`, IAM principal ARN, 운영 이메일 등 기존 필수 값을 준비한다. 비밀번호는 넣지 않는다. 초기에는 `enable_website_dns=false`, `enable_management_dns=false`, `keep_legacy_node_group=false`로 둔다. 아래 환경 변수는 현재 창에서만 사용한다.

```powershell
$pw = Read-Host '새 RDS 관리자 비밀번호 (8~41자)' -AsSecureString
$env:TF_VAR_db_password = [Net.NetworkCredential]::new('', $pw).Password
Remove-Variable pw
# 신규 빈 환경에만 -reconfigure 사용. 기존 자원이 있는 local state는 -migrate-state 절차 사용.
terraform -chdir=terraform init -reconfigure
terraform -chdir=terraform validate
terraform -chdir=terraform plan -var='enable_website_dns=false' -var='enable_management_dns=false'
terraform -chdir=terraform apply -var='enable_website_dns=false' -var='enable_management_dns=false'
aws eks update-kubeconfig --name Final-eks --region ap-northeast-2 --profile default
kubectl get nodes -o wide
```

프로젝트는 기존 Route53 공개 hosted zone `Z01939771EBX5SBI3T3FU`를 조회한다. 이는 삭제·재생성하지 않는다. ACM DNS 검증, EKS API 허용 IP, 실습 계정 권한과 서울 리전의 EKS/RDS 버전 지원 여부를 실제 환경에서 확인한다.

## 4. Secret 준비 후 EKS 내부 구성 (`terraform-k8s`)

**앞 단계 AWS apply 및 kubeconfig 연결 후, 이 단계 plan/apply 전에** `Prepare-Secrets.ps1`을 실행한다. 아직 namespace가 없어도 동작하며, 기존 Secret이 있으면 JWT 키를 재사용한다. 같은 PowerShell 창을 유지한다. RDS 비밀번호는 앞 단계의 값을 재사용한다. GitHub 저장소 읽기 토큰은 보안 입력한다.

```powershell
. ./terraform-k8s/Prepare-Secrets.ps1
terraform -chdir=terraform-k8s init -reconfigure
terraform -chdir=terraform-k8s validate
terraform -chdir=terraform-k8s plan -var='enable_app_sync=false' -var='enable_management_ingress=false'
terraform -chdir=terraform-k8s apply -var='enable_app_sync=false' -var='enable_management_ingress=false'
kubectl get pods -A
```

apply는 namespace·앱 Secret·Argo CD·ALB Controller·모니터링 등을 준비한다. 아직 앱 자동 배포는 꺼져 있다. 클러스터가 없는 시점에 이 루트부터 apply하지 않는다. 기본 state 순서는 항상 **terraform → terraform-k8s**, 삭제 순서는 **terraform-k8s → terraform**이다. state bootstrap은 프로젝트 생명주기 밖에 남긴다.

## 5. 앱 이미지와 GitOps 배포 (별도 승인 후)

현재 게시·배포 대상은 main이다. 아래 별도 검증 경로는 운영과 다른 환경에서 시험할 때 사용한다. 기존 test는 보관용이므로 검증 브랜치로 재사용하지 않는다.

### main을 유지하며 별도 브랜치를 검증하는 경우

새 ECR에 이미지가 없으면 저장소 루트에서 아래 스크립트로 테스트·전체 빌드·게시를 수행한다. Docker와 Git Bash가 필요하다. 테스트 또는 빌드가 실패하면 태그 반영 단계로 넘어가지 않는다.

```powershell
git switch -c infra-lab main
$imageTag = (git rev-parse HEAD).Trim()
./app/msa/scripts/Build-Images.ps1 -ImageTag $imageTag -Push
git add app/msa/kustomization.yaml
git commit -m "Deploy rehearsal images"
git push -u origin infra-lab
```

별도 환경의 개인 tfvars에 `github_revision = "infra-lab"`을 지정한다. 이후 sync/ingress 활성화, DNS 연결, 접속 확인 순서는 동일하다. 이미 자동 동기화를 켠 환경에서는 해당 브랜치의 매니페스트 변경도 배포된다. 코드만 작업하려면 자동 sync를 끄거나 별도 실습 환경을 사용한다. main 배포로 전환할 때는 이미지 게시와 main 반영을 확인하고 `github_revision = "main"`으로 되돌린다. 이 저장소의 이름·도메인·backend 키를 그대로 쓰면 환경이 분리되지 않으므로, 같은 AWS 자원 위에 별도 state로 중복 구축하지 않는다.

### 기본 main 배포

사용자가 main 반영을 완료한 뒤 Actions 화면에서 `Build and publish changed services`를 **main / full_build=true**로 실행한다. 새 ECR은 비어 있으므로 첫 구축은 5개 전체 빌드가 필요하다. 저장소 Actions 변수 `AWS_ROLE_TO_ASSUME`에 `terraform output github_actions_role_arn` 값을 등록하고, GitHub Actions의 contents write 허용 여부를 확인한다. 테스트 실패 시 게시·태그 갱신은 중단된다. Actions가 만든 Kustomize 태그 커밋까지 확인한다.

```powershell
# main 반영이 끝난 뒤 읽기 전용으로 최신 커밋을 가져온다 (자동 병합 명령 없음).
git fetch origin
# 사용자 검토 후 앱 자동 sync 활성화
terraform -chdir=terraform-k8s plan -var='enable_app_sync=true' -var='enable_management_ingress=true'
terraform -chdir=terraform-k8s apply -var='enable_app_sync=true' -var='enable_management_ingress=true'
kubectl get application final-apps -n argocd -o yaml
kubectl get pods -n soldesk -o wide
```

Actions 성공은 **이미지 게시와 Git 태그 커밋 완료**다. Argo CD의 `Synced` + `Healthy`, `status.sync.revision`이 원하는 Git 커밋인지 별도로 확인한다. 이전 커밋의 Healthy만 보지 않는다. 앱 관련 revision은 이미지 원본 커밋과 태그 갱신 봇 커밋이 다를 수 있다.

```powershell
kubectl wait --for=jsonpath='{.status.sync.status}'=Synced application/final-apps -n argocd --timeout=600s
kubectl wait --for=jsonpath='{.status.health.status}'=Healthy application/final-apps -n argocd --timeout=600s
kubectl get application final-apps -n argocd -o jsonpath='{.status.sync.revision}'
kubectl rollout status deployment/frontend-depl -n soldesk --timeout=300s
kubectl get pods -n soldesk -l app=frontend -o wide
kubectl get pdb frontend-pdb -n soldesk
kubectl get ingress -A
aws elbv2 describe-load-balancers --names final-shared-alb --region ap-northeast-2
```

ALB이 실제로 준비된 후 DNS를 연결한다. `enable_management_dns=true`는 `enable_website_dns=true`와 함께 사용한다.

```powershell
terraform -chdir=terraform plan -var='enable_website_dns=true' -var='enable_management_dns=true'
terraform -chdir=terraform apply -var='enable_website_dns=true' -var='enable_management_dns=true'
./scripts/ops/Test-DeploymentHttps.ps1
```

HTTPS 스크립트는 화면과 공개 상품 조회 API의 200 응답·내용 형식을 확인한다. 기본 최대 HTTP 시도 시간은 경로당 12×10초 + 재시도 대기 11×10초이며 DNS 지연은 OS의 영향을 받는다. 로그인·상품 등록·주문·이메일·관리자 기능은 별도 확인한다. 저장소의 GitOps 흐름은 유지하며 CI에서 kubectl apply를 실행하지 않는다.

## 6. 상태 점검·로그·복원 실습

- `startupProbe`는 Java의 liveness를 10초 간격 18회(약 3분) 기다린다. Spring 초기화 자체가 DB 연결 실패로 종료되는 상황까지 방지하는 설정은 아니다.
- DB를 사용하는 서비스의 readiness는 `readinessState,db`, liveness는 `livenessState`다. **시작 후 DB 장애** 때 Ready만 false가 되고 DB 장애만으로 재시작하지 않아야 한다. Gateway는 DB를 직접 쓰지 않으므로 readinessState만 사용한다.
- 기존 `/health` 경로는 호환성을 위해 남겼지만 probe는 `/actuator/health/readiness`, `/actuator/health/liveness`를 사용한다. Gateway ALB health 경로도 readiness로 맞췄다.
- 실제 DB 장애·복구 실습에서 `kubectl get pods -w`의 Ready와 restartCount를 함께 기록한다. readiness 실패 시 서비스가 트래픽을 중단하는지 확인한다. 로그에 DB 비밀번호나 토큰을 출력하지 않는다.
- EKS의 `api`, `audit`, `authenticator`는 CloudWatch `/aws/eks/Final-eks/cluster`에 14일 보관한다. audit 로그는 민감한 요청 정보를 담을 수 있으므로 로그 조회 권한을 제한한다. 기존 로그 그룹이 있다면 state 이전 안내의 import를 먼저 수행한다.

```powershell
aws eks describe-cluster --name Final-eks --region ap-northeast-2 --query 'cluster.logging'
aws logs describe-log-groups --log-group-name-prefix /aws/eks/Final-eks/cluster --region ap-northeast-2
# 이하 별도 문서의 스냅샷/복원/데이터 확인/정리 순서를 따라 실행
./scripts/ops/Invoke-RdsRestoreLab.ps1 -Mode Inspect
```

[RDS 별도 DB 복원 실습](08-rds-restore-lab.md) · [state와 잠금·이전](07-terraform-state.md)

## 7. 실습 종료 후 정리

먼저 복원 실습 DB·임시 MySQL Pod를 정리하고 스냅샷 보관 여부를 결정한다. 이후 1번의 역순 삭제 절차를 따른다. 조회 전용 `Get-ProjectResidue.ps1`은 실패 건수가 있으면 종료 코드 1을 반환한다. `조회 성공: 해당 자원 없음`과 `조회 실패`를 구분해 기록한다. 태그·이름·서울 리전 기준 후보 조회이므로 모든 비용 자원 부재의 증명은 아니다. OIDC·IAM 후보는 다른 실습과 공유될 수 있어 ARN을 대조한다.

state 버킷, bootstrap local state, 기존 Route53 hosted zone, 사용자가 보관하기로 한 수동 DB 스냅샷은 별도 보관 목록이다. state 버킷에는 과거 버전이 계속 남아 저장 비용이 들 수 있다. 보관 여부는 프로젝트 destroy와 별도로 결정한다.

```powershell
./scripts/ops/Get-ProjectResidue.ps1 -Profile default -Region ap-northeast-2
# 보안 입력값은 작업 종료 시 현재 창에서도 제거
'TF_VAR_db_password','TF_VAR_github_token','TF_VAR_jwt_secret','TF_VAR_jwt_refresh_secret' |
    ForEach-Object { Remove-Item "Env:$_" -ErrorAction SilentlyContinue }
git status --short
```
