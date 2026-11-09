> **과거 기록의 적용 범위** · 아래는 당시 코드·계정·브랜치·준비 상태를 보존한 원문입니다. 현재 main의 실행 안내는 [README](../README.md), 실제 완료 범위는 [최신 검증 정리](21-current-validation.md)를 사용하세요. “미실행/예정”은 작성 당시 기준입니다.

# S3 state: 초기 구축과 기존 state 이전

## 별도 보관 구성

`terraform-state-bootstrap`은 프로젝트의 두 Terraform 루트와 독립적이다. S3 버킷 `final-tfstate-143710973003-ap-northeast-2`에 버전 관리, AES256 서버 측 암호화, 퍼블릭 접근 전체 차단, BucketOwnerEnforced, TLS 필수 정책을 설정한다. `force_destroy=false`, `prevent_destroy=true`이며 다른 루트에서 module로 호출하지 않는다. 프로젝트 destroy는 state 버킷을 지우지 않는다. 관리자가 bootstrap 코드나 state를 강제로 바꾸면 보호를 우회할 수 있으므로 IAM 삭제 권한도 제한한다.

| 루트 | 기본 workspace state 키 | 잠금 객체 |
| --- | --- | --- |
| terraform | final/infra/terraform.tfstate | final/infra/terraform.tfstate.tflock |
| terraform-k8s | final/k8s/terraform.tfstate | final/k8s/terraform.tfstate.tflock |

Terraform 1.12 이상에서 `use_lockfile=true`로 S3의 네이티브 잠금을 사용한다. DynamoDB 테이블은 추가하지 않는다. `terraform-k8s/data.tf`는 S3의 infra 키를 읽는다. 여기에는 인증정보를 넣지 않고 AWS CLI `default` 프로필을 사용한다. 두 backend와 data.tf의 버킷·리전·키는 함께 맞춰야 한다. 다른 workspace는 state 키가 달라지므로 이 실습은 `default` workspace로 제한한다.

state는 비밀번호를 write-only/ephemeral로 처리해도 기타 민감한 인프라 정보를 포함한다. 읽기 권한을 가진 사용자는 output 외의 state 전체에도 접근할 수 있다. 두 루트 모두 프로젝트 운영자만 접근하도록 한다. backend 운영자에게 필요한 기본 권한은 해당 버킷의 `s3:ListBucket`, 두 state 키의 `s3:GetObject`, `s3:PutObject`, 두 `.tflock` 키의 `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`다. 과거 버전 복구에는 별도로 `s3:ListBucketVersions`, `s3:GetObjectVersion` 등이 필요하다. bootstrap 생성·설정 권한은 별도이며 위 state 쓰기 권한만으로 버킷을 생성할 수는 없다.

잠금 충돌은 동시 Terraform 실행 여부를 먼저 확인한다. 실행 중인 작업을 확인하지 않고 lock 객체를 지우거나 `-lock=false`로 우회하지 않는다. 백업 복구 시에도 모든 실행을 중단하고 serial/lineage 및 실제 AWS 자원과 일치하는 버전인지 확인한다.

## 기본: 삭제 후 신규 구축

[월요일 순서](06-monday-runbook.md)를 따른다. 기존 환경은 기존 state로 `terraform-k8s`부터 destroy하고 `terraform`을 destroy한다. state가 비었는지와 AWS 잔여 자원을 확인한 뒤 bootstrap을 준비하고 신규 S3 backend를 init한다. 리소스가 남아 있는 local state를 버리고 `init -reconfigure`하면 중복 생성·이름 충돌 위험이 있다.

bootstrap은 local state를 사용하며 self-hosting 순환을 피한다. 이 state와 `.backup`을 암호화된 개인 보관 위치에 백업하고 Git에는 올리지 않는다. 기존 버킷의 bootstrap state를 잃었다면 다음 예시로 **실제 같은 프로젝트 버킷임을 확인한 뒤** import한다. 임의의 새 bootstrap state로 무작정 apply하지 않는다.

```powershell
terraform -chdir=terraform-state-bootstrap init
terraform -chdir=terraform-state-bootstrap import aws_s3_bucket.state final-tfstate-143710973003-ap-northeast-2
terraform -chdir=terraform-state-bootstrap import aws_s3_bucket_versioning.state final-tfstate-143710973003-ap-northeast-2
terraform -chdir=terraform-state-bootstrap import aws_s3_bucket_server_side_encryption_configuration.state final-tfstate-143710973003-ap-northeast-2
terraform -chdir=terraform-state-bootstrap import aws_s3_bucket_public_access_block.state final-tfstate-143710973003-ap-northeast-2
terraform -chdir=terraform-state-bootstrap import aws_s3_bucket_ownership_controls.state final-tfstate-143710973003-ap-northeast-2
terraform -chdir=terraform-state-bootstrap import aws_s3_bucket_policy.state final-tfstate-143710973003-ap-northeast-2
terraform -chdir=terraform-state-bootstrap plan
```

실제로 존재하지 않는 설정의 import가 실패하면 해당 원인을 확인하고, 나머지 state와 plan을 검토해 추가 설정을 반영한다. 다른 프로젝트 버킷을 import하지 않는다.

## 예외: 자원을 유지하며 기존 local state 이전

1. Terraform/CI 작업을 모두 중단한다. 기존 `.terraform` backend 메타데이터와 local state를 그대로 보존한다. 두 루트의 `state list`가 실제 자원을 가리키는지, 현재 workspace가 default인지 확인한다. 기존 local 설정에서 확인한 뒤 state 파일을 삭제하지 않고 S3 backend가 있는 개선 코드로 전환한다. 현재 개선 코드는 main이다.
2. 두 local state·backup을 저장소 외부의 접근 제한된 디렉터리에 복사한다. 기존 backend가 이미 S3라면 S3 버전 관리 상태와 이전 backend 설정도 보존한다. 이 복사본을 Git·공유 로그에 첨부하지 않는다.
3. bootstrap으로 state 전용 버킷을 먼저 준비한다. AWS 계정·버킷 소유권을 확인한다. 목적지 두 키에 기존 state가 있는지 `aws s3api list-object-versions --bucket <버킷> --prefix final/`로 확인한다. 존재하면 덮어쓰지 말고 lineage/serial과 소유 환경부터 비교한다.
4. 먼저 infra, 다음 k8s 순서로 이전한다. 아래 명령은 backend 저장 위치만 바꾸며 AWS 자원 apply는 하지 않는다. 질문의 원본/목적지와 state 내용을 확인한 뒤 동의한다. `-force-copy`, `-reconfigure`, `-lock=false`로 이전 검사를 생략하지 않는다.

```powershell
terraform -chdir=terraform init -migrate-state
terraform -chdir=terraform state list
terraform -chdir=terraform-k8s init -migrate-state
terraform -chdir=terraform-k8s state list
```

5. S3 두 state 객체와 버전 생성, 양쪽 resource 주소 목록이 이전과 같은지 확인한다. 이후 `Prepare-Secrets.ps1` 실행 시점은 기존 클러스터 kubeconfig 연결 후 k8s plan 전이다. 초기 삭제/생성 없이 plan으로 기존 변경과 이번 개선을 구분한다. S3로 옮겼다는 이유만으로 모든 plan이 No changes여야 하는 것은 아니다(관리 로그·probe 등 이번 변경은 별도 반영 대상).
6. 기존 EKS 로그 그룹이 존재하면 아래 import를 **infra plan/apply 전에** 실행한다. 이미 state에 관리 중이면 다시 import하지 않는다.

```powershell
terraform -chdir=terraform import 'module.eks.aws_cloudwatch_log_group.control_plane' /aws/eks/Final-eks/cluster
```

7. 현재 작업 성공과 백업 보관을 확인할 때까지 local backup은 지우지 않는다. 이후에도 S3 state를 다운로드해서 local backend로 두 개의 독립 관리 경로를 만들지 않는다. 이전 실패 시 어느 backend가 실제 state를 가지는지 확인한 뒤 재시도한다.

잠금의 실제 동시 실행 차단, S3 버전 복구, IAM 접근 거부, CloudWatch 로그 수집은 월요일 AWS에서 확인할 항목이다. 이번 작업은 AWS 연결 없이 코드와 모의 테스트만 확인했다.
