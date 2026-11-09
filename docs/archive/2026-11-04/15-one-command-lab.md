> **과거 문서 보존본** · 최신화 전 main `cc040cf` 원문입니다. [현재 문서 목록](../../README.md)을 사용하세요.

> CodeBuild 내부 검증·보존·복원 절차는 [통합 운영 가이드](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/16-integrated-operations.md)를 함께 확인하세요. 기존 전체 삭제는 보존 모드가 아닙니다.

# PS1로 설치·검증·삭제하기

GUI 없이 저장소 루트의 세 파일을 사용합니다. 내부에서 기존 Terraform·Python 도구를 순서대로 실행하므로 **저장소 전체를 Git으로 받아야 합니다.** PS1 한 파일만 복사하거나 ZIP만 풀면 Git 이력·배포 커밋 확인을 할 수 없습니다.

```powershell
git clone https://github.com/yobi84-sy/aws-msa-final-test2.git aws-msa-final-test2-lab
cd aws-msa-final-test2-lab
Set-ExecutionPolicy -Scope Process RemoteSigned
```

| 파일 | 실행 범위 |
|---|---|
| `Install-Lab.ps1` | 설정 입력 → state → AWS 기반 → EKS 도구 → 관리자 → 검증한 이미지 → 앱 → DNS·메일 → 기본 검증 |
| `Verify-Lab.ps1` | 기본은 조회만. 비밀번호 회전·CPU 부하 시험은 별도 옵션과 영향 승인 필요 |
| `Remove-Lab.ps1` | 앱 → ALB·EBS → 도구 → AWS 기반 → 잔여 확인 → state 버킷까지 정리 |

**2026-10-21에 설치·보존·복원·최신 배포·전체 삭제를 실제 실행했습니다.** ALB 상태 확인과 CloudTrail 지연 로그 때문에 재개한 구간이 있고, 빈 SQS 목록 처리 오류를 수정했습니다. 새 자동 재시도 로직은 모의 검증 범위이며 실배포 확인은 별도로 필요합니다. [실제 결과와 증거 구분](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/17-validation-20261021.md)

## 1. 준비

Windows PowerShell 5.1 또는 PowerShell 7을 사용합니다. PS1은 UTF-8 BOM으로 저장했습니다. Python 3.12 이상, AWS CLI v2, Git, GitHub CLI, Terraform 1.x(검증 버전 1.16.2), Helm **3.x**(검증 버전 3.19.0), kubectl **1.35.x**를 PATH에 준비합니다. EKS는 1.35이므로 kubectl 허용 범위는 1.34~1.36입니다. Helm 4와 kubectl 1.37은 사전 확인에서 중단합니다.

```powershell
python -m pip install PyYAML==6.0.3
aws sts get-caller-identity --profile eks-user
gh auth status
```

AWS는 계정 `021158485482`, profile `eks-user`, 서울 리전으로 제한합니다. 다른 계정이면 중단합니다. GitHub는 `yobi84-sy/aws-msa-final-test2` 쓰기 권한이 있어야 합니다. AWS/GitHub 로그인 자체는 각 PC에서 먼저 준비하며, 스크립트가 인증키나 토큰을 입력받아 파일에 저장하지 않습니다.

## 2. 최초 설치: 한 명령으로 이어서 진행

```powershell
.\Install-Lab.ps1            # 단계 미리보기. AWS 조회·변경 없음
.\Install-Lab.ps1 -Execute   # 실제 설치
```

처음에는 운영자 IAM ARN, 장애 알림 메일, SES 발신 메일, 구매자 실습 메일, 관리자 메일을 입력합니다. 공개 설정만 `.lab/lab-config.json`에 보관합니다. 관리자 메일은 **관리자 계정 이메일과 신규 주문 알림 주소에 함께 사용**합니다. 일반 회원은 이메일 중복 금지 때문에 다른 주소로 가입하세요.

인증되지 않은 SES 주소는 인증 요청 후 기다립니다. 해당 메일함에서 AWS 링크를 클릭해야 진행됩니다. 관리자 비밀번호는 도구 설치 후 숨김 입력하며 Kubernetes Secret에만 전달합니다. 기존 관리자 Secret이 같은 주소로 준비돼 있으면 재사용하고 비밀번호를 다시 바꾸지 않습니다.

각 Terraform 단계는 새 plan을 만들고 생성/변경 대상과 로컬 plan 경로를 보여준 뒤 `yes`를 받습니다. **예상하지 않은 AWS 리소스 삭제·교체가 있으면 자동 중단**합니다. 준비 게이트 교체용 `terraform_data`는 실제 AWS 리소스가 아니므로 예외입니다.

반복 확인 없이 실행하려는 운영자는 `-ApprovePlans`를 명시할 수 있습니다. 이 옵션은 과금/변경을 사전 승인하는 의미입니다. 계정·소유권·삭제 금지 검사는 계속 적용됩니다.

```powershell
.\Install-Lab.ps1 -Execute -ApprovePlans
```

EKS·t3.medium 시작 3대/최대 6대·RDS·NAT·저장소 비용이 발생합니다. AWS 무료 크레딧 여부와는 별개로 과금 리소스가 실제 생성됩니다. 운영 알림 SNS 구독 메일의 확인 링크도 직접 눌러야 합니다.

### 최초 설치와 이후 승인 배포의 차이

이미지를 만들고 ECR에 게시하려면 배포 선언의 새 digest가 필요합니다. 이를 main에 바로 밀어 넣으면 승인 강제와 충돌합니다. 그래서 최초 설치는 다음처럼 진행합니다.

1. 현재 main 코드로 전체 테스트·이미지 빌드·ECR 게시를 수행합니다.
2. 봇이 배포 PR을 만들지만 **스크립트는 PR을 자동 병합하지 않습니다.**
3. **비어 있는 새 클러스터에 한해** 테스트한 배포 PR의 immutable 커밋을 Argo CD 대상으로 지정합니다. 최초 서비스 구동은 동료 승인을 기다리지 않습니다.
4. 초기 배포 PR을 동료가 검토·승인하고 병합한 후, 아래를 한 번 실행합니다.

```powershell
.\Install-Lab.ps1 -Execute -PromoteMain
```

이 명령은 baseline PR 병합과 main 보호 규칙을 확인하고, 이미지가 ECR에 존재하는지 검사한 뒤 Argo CD 대상을 보호된 main으로 전환합니다. **이 전에는 최초 배포 커밋에 고정돼 있어 main 변경을 자동 반영하지 않습니다.** 운영 중인 다른 환경에 최초 설치 예외를 다시 적용하려 하면 중단합니다.

전환 검증 후 `ENABLE_IMAGE_PUBLISH=true`를 설정합니다. 이후 승인된 소스 PR이 main에 병합되면 변경 서비스를 게시하고, 별도의 배포 PR을 생성합니다. 이 PR을 다른 팀원이 승인·병합해야 실제 이미지가 바뀝니다. 인프라/스크립트 자체가 바뀐 경우에는 같은 `-PromoteMain` 명령으로 새 plan을 검토하며 반영할 수 있고, 리소스 삭제·교체가 요구되면 멈춥니다.

### 중단·실패 후 재개

오류를 해결하고 **같은 명령**을 다시 실행합니다. `.lab/install-state.json`에 완료 단계를 기록하며, 완료한 기반 구성을 무조건 다시 만들지 않습니다. 미완료 Terraform 단계는 저장된 옛 plan을 재사용하지 않고 새 plan을 만듭니다. 이전 클러스터와 VPC가 다르거나 코드/입력값이 중간에 바뀌면 섞어 설치하지 않고 중단합니다.

이미지 빌드는 요청 식별자와 실행 번호를 기록합니다. 응답이 늦다는 이유로 새 빌드를 계속 만들지 않습니다. 실패한 Actions 실행을 수정·재실행한 뒤 설치 스크립트를 재개하세요. 메일 인증이나 팀원 승인처럼 사람이 해야 하는 단계는 강제로 건너뛰지 않습니다.

## 3. 검증

```powershell
.\Verify-Lab.ps1
```

현재 EKS의 허용 IP 안에서 조회합니다. 검증 명령이 임의로 API 접근 범위를 넓히지는 않습니다. 다음 항목을 확인하고 `.lab/runtime/verification.json`에 결과를 저장합니다.

- 노드 Ready·medium·AZ별 범위, RDS 비공개·암호화·available
- 모니터링 PVC Bound, ESO Ready
- 공유 ALB 한 개와 모든 대상 그룹의 healthy
- Argo 실제 revision, 다섯 앱 이미지·준비 복제 수
- HTTPS·HTML·상품 API, 최근 DB 비밀번호 전달 Job의 세 서비스 READY/PASS
- SQS 메일 소비자 Enabled, SES 주소 인증, 관리자 Secret과 Lambda 수신 설정 일치

**기본 PASS가 실제 구매·메일함 도착·모든 네트워크 경로·무중단 운영까지 증명하지는 않습니다.** 웹에서 구매자 주문 확인 메일과 관리자 신규 주문 알림을 각각 확인하고, 회원/상품/주문 데이터 유지도 별도 실습합니다. GitHub 호스트 러너는 현재 EKS의 PC IP 제한에 막힐 수 있어 원격 deploy-check를 임의로 켜지 않습니다. 설치 과정의 기본 검증은 실행 PC에서 자동 수행합니다.

### 영향 있는 선택 시험

```powershell
.\Verify-Lab.ps1 -Mode Rotation -AllowImpact
.\Verify-Lab.ps1 -Mode Scaling -AllowImpact
```

- **Rotation:** 실제 RDS 관리 비밀번호 회전 → 새 AWSCURRENT → ESO/Job → 세 앱 자동 교체 → 서비스 검증. DB 연결이 잠시 실패할 수 있습니다. 비밀번호 값은 조회하지 않으며, 중단 후 같은 명령은 기존 회전 상태를 관찰합니다. 요청 결과가 불명확하면 중복 회전을 시키지 않고 멈춥니다.
- **Scaling:** 기존 Member Pod에 최대 180초의 합성 CPU 부하 → 실제 준비 Pod 확장 → 부하 해소 후 축소를 확인합니다. 실사용자 트래픽 시험과는 구분합니다. 노드가 늘면 비용이 증가합니다. 노드 수가 그대로여도 HPA는 정상일 수 있으며, CA 증설 원인은 별도 이벤트·로그로 확인합니다.

## 4. 전체 삭제

```powershell
.\Remove-Lab.ps1                          # 미리보기만
.\Remove-Lab.ps1 -Execute -DiscardData    # state 버킷까지 전체 정리
```

실제 삭제 전에 데이터 폐기 확인과 단계별 destroy plan을 확인합니다. `-ApprovePlans`는 이 확인을 미리 승인할 때만 사용합니다. state 버킷을 보존하려면 `-KeepStateBucket`을 추가합니다.

1. GitHub 자동 이미지 게시·원격 배포 검사를 끕니다. main 작업이 아직 실행 중이면 삭제 전에 멈춰 기다리거나 해당 작업을 취소하도록 안내합니다. 이어서 VPC와 실제 모니터링 PVC→EBS ID를 캡처합니다.
2. 앱 자동 동기화를 끄고 Application·Ingress를 삭제합니다.
3. 모니터링 CR → Helm → PVC를 정리하고 ALB/EBS가 사라질 때까지 기다립니다.
4. CloudTrail을 정지하고 **상품 이미지·감사 로그·CodeBuild 검증 소스 버킷과 다섯 ECR만** 비웁니다.
5. EKS 도구 → AWS 인프라를 destroy합니다. DNS 조회 플래그는 자동으로 false가 됩니다.
6. AWS API 조회로 주요 잔여 리소스와 두 Terraform state의 비어 있음을 확인합니다.
7. 빈 최종 state를 로컬에 저장한 뒤, state 버킷의 과거 버전·삭제 마커까지 제거하고 버킷을 지웁니다. bootstrap local state도 이미 없어진 버킷을 계속 추적하지 않도록 정리합니다.

**회원·상품·주문·이미지·모니터링 기록·감사 로그는 복구할 수 없게 삭제됩니다.** 도메인 호스팅 영역, 기존 SES 인증, AWS/GitHub 계정, 무관한 OIDC는 보존합니다. 종료된 EC2나 삭제된 NAT가 AWS 목록에 잠시 표시되는 것은 활성 리소스와 구분합니다.

현재 PC가 다른 경우 삭제 시작 전에 그 PC의 IPv4 한 개만 EKS 허용 목록에 임시 추가할 수 있습니다. 전체 공개(`0.0.0.0/0`)로 넓히지 않습니다. EKS가 함께 삭제되면 임시 허용도 없어집니다.

실패하면 state 버킷이나 `.lab/removal`을 임의 삭제하지 마세요. 같은 명령으로 재개합니다. CloudTrail의 정확한 로그 버킷에 대한 단일 `BucketNotEmpty` 진단만 자동 재시도합니다. 현재 계정·캡처·남은 state의 버킷 ID·실제 버킷 소유자와 리전을 재확인하고, 기록 중인 동일 trail이 있으면 정지 여부까지 확인합니다. 그 로그 버킷만 다시 비운 뒤 **새 destroy plan**을 검토하며, destroy는 최초 포함 최대 3회(재시도 대기 10초·20초)입니다. 권한 오류·다른 버킷·복수 오류·다른 관리 자원이 남은 state는 자동 정리하지 않고 중단합니다. 캡처하지 않은 EBS·다른 LB·다른 state 파일도 성공으로 간주하지 않습니다.

설치·복원은 ALB와 대상 준비를 최대 10분, 기본 검증/승인 main 전환 뒤 검증은 최대 5분 기다립니다. `verify_lab.py`가 방금 작성한 보고서에서 ALB 생성 대기·대상 미준비를 명시한 경우에만 최대 15초 간격으로 재확인합니다. 권한/조회 오류·추가 LB·실패한 ALB·이전 보고서는 재시도 근거로 쓰지 않습니다. 제한 시간이 지나도 준비되지 않으면 실패로 남기고 중단합니다. 이 대기 시간은 ALB 검사 구간 기준이며 전체 설치 제한 시간이 아닙니다.

설치가 중간에 실패해 PVC가 아직 Bound가 아니면 원인을 확인하도록 멈출 수 있습니다. 자료가 유실된 경우까지 추측해서 강제 삭제하는 도구는 아닙니다.

## 5. 관리자 주문 알림과 DB 충돌 대응

구매자에게는 `주문 완료 안내 #번호`, 관리자에게는 `신규 주문 알림 #번호`를 각각 보냅니다. 관리자 알림에는 주문번호·상품·수량·금액·주문 시각만 넣고 구매자의 메일·이름·주소는 넣지 않습니다. 같은 이메일을 구매자/관리자가 쓰면 목적이 다른 두 메일이 올 수 있습니다. 두 발송을 처리할 수 있도록 기존 Lambda 제한 시간을 60초로 조정하고 SDK 자체 재시도는 끄며, 실패 재시도는 SQS에 맡깁니다.

기존 DynamoDB 테이블 안에서 구매자와 관리자 발송 기록을 구분합니다. 한쪽 실패로 SQS가 재시도해도 이미 SENT인 다른 쪽은 다시 보내지 않습니다. 다만 **SES가 접수한 뒤 SENT 기록 저장이 실패하면 중복 가능성은 남으므로 exactly-once라고 표현하지 않습니다.** 발송 실패는 수신자 종류·단계·AWS 오류 코드만 로그에 남깁니다.

DB 전달 worker는 각 Deployment를 수정하기 직전에 최신 resourceVersion을 읽습니다. HTTP 409 충돌만 최대 세 번 시도하고, 권한 오류 등은 즉시 실패합니다. 재시도 중 Secret이 또 바뀌면 멈추며, 이전 비밀번호로 계속 갱신하지 않습니다. 로그에는 HTTP 코드·메서드·서비스 이름만 기록하고 비밀번호·토큰·fingerprint는 출력하지 않습니다.

초기 실패 Job의 당시 HTTP 코드가 없었으므로 원인을 단정할 수는 없습니다. 다만 기존 코드의 오래된 resourceVersion 충돌은 로컬에서 같은 흐름으로 재현했고, 수정 후 해당 재현 시험을 통과하도록 보완했습니다.

## 6. PR 승인

main은 `required-ci`와 `release-approval`, 다른 사람의 리뷰 1개, 마지막 push 승인, 오래된 승인 취소, 대화 해결을 요구하고 관리자 우회·강제 push·브랜치 삭제를 막는 설정을 적용합니다. 팀원은 초대를 수락해 **실제 write 권한**을 가져야 합니다. [GitHub의 필수 리뷰 조건](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)

봇이 작성한 배포 PR에는 별도 검사가 있습니다. GitHub API의 이미지 빌드 실행자를 확인하고 그 사람과 다른 팀원의, 현재 PR 커밋에 대한 승인을 요구합니다. `Approve and run`은 CI 실행 허가이고 `Review changes → Approve → Submit review`는 동료 리뷰라 서로 다릅니다.

초대 수락 후 검사를 다시 계산해야 하면:

```powershell
gh workflow run review-policy.yml --repo yobi84-sy/aws-msa-final-test2 --ref main -f pr_number=PR번호
```

PS1·Python·Terraform·워크플로·사용법은 함께 버전 관리합니다. `.lab`, tfvars, state, plan, 비밀번호, 토큰은 Git에 올리지 않습니다.
