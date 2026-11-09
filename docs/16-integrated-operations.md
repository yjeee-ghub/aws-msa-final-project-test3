> **2026-11-04 보충** · 이 문서의 10월 21일 검증 설명은 당시 기록입니다. 이후 전체 실행·재개 및 11월 HA 배포·장애 시험은 [최신 검증 정리](21-current-validation.md)에 추가했습니다. 이전 구성의 보존·복원 성공을 새 HA 구성의 모든 복구 시험으로 확대하지 않습니다.

> **NAT 통합 추가:** 이제 보존 종료에서는 NAT 검사 EC2·SSM Endpoint도 남아 비용이 발생하며 제어기는 정지합니다. 복원 시 예약·동시 실행을 복구하고 최신 통신 관찰을 확인합니다. 전체 삭제에는 새 자원도 포함합니다. [상세](22-nat-autofailover.md)

# 통합 운영 보완 — 설치, 내부 검증, 보존·복원, 전체 삭제

기존 test2를 유지하면서 네 가지를 보완한다. 새 AWS 서비스는 CodeBuild이고, 함께 필요한 비공개 소스 S3·IAM·보안 그룹·로그가 추가된다. AWS Backup이나 새로운 검증용 EKS 러너는 설치하지 않는다.

## 1. 배포 확인 경로

`CI 통과 → main에 이미지 digest 기록 → Argo CD 반영 → CodeBuild → EKS 읽기 조회 + HTTPS 기능 확인`

- GitHub OIDC 역할은 소스 ZIP 업로드와 CodeBuild 시작·조회만 담당한다. 직접 Kubernetes API에 접속하지 않는다.
- CodeBuild는 기존 Private Subnet에서 실행한다. EKS 접근은 해당 보안 그룹의 443만 허용하고, Kubernetes 권한은 앱 Deployment 조회 및 `final-apps` 조회로 제한한다. Secret 조회·배포 변경 권한은 없다.
- 소스는 지정한 Git SHA의 `git archive`로 만든다. `.lab`, 로컬 비밀번호, tfvars, state는 업로드하지 않는다.
- 검증 실패는 성공으로 처리하지 않는다. 제한 시간을 넘기거나 취소되면 해당 빌드를 중지한다. 앱/DB 자동 롤백은 하지 않는다.
- 최초 설치는 CI가 main에 기록한 배포 SHA에 고정한다. 초기 검증이 끝나면 `-PromoteMain`으로 main 추적을 켠다.

## 2. 실행 명령

저장소 루트 PowerShell에서 실행한다. `-Execute`가 없으면 미리보기만 한다. 실제 실행에는 AWS 과금과 서비스 중단이 따른다. `-ApprovePlans`는 사람이 확인한 범위 안에서 plan 질문을 생략할 때만 사용한다.

```powershell
.\Install-Lab.ps1 -Execute
.\Verify-Lab.ps1 -Mode Basic

# 상품·주문 ID, 재고, 이미지와 Grafana 저장 대시보드를 먼저 기록한다.
.\Preserve-Lab.ps1 -Execute
.\Resume-Lab.ps1 -Execute

# 원래 계정 로그인, 같은 상품·주문·이미지·대시보드가 유지되는지 비교한다.
# 더 이상 복원이 필요 없을 때만 전체 폐기한다.
.\Remove-Lab.ps1 -Execute -DiscardData
```

### 보존 중지에서 지키는 것

1. 현재 클러스터·VPC·PVC→EBS 관계와 필요한 Secret을 확인한다. Secret은 **현재 PC의 Windows 사용자 DPAPI**로 암호화하고 복호화 왕복 검사까지 끝낸다.
2. GitHub 자동 게시와 검증을 멈춘다. DNS·메일 소비자를 끄고 Application을 제거해 앱 쓰기를 중지한다.
3. 모니터링 쓰기도 중지하고 RDS 및 EBS 3개 스냅샷 완료를 기다린다.
4. Controller·CSI가 살아 있을 때 ALB와 원래 EBS를 정리한다. Kubernetes 도구를 제거한 뒤, 검토한 대상 한정 destroy로 EKS·RDS와 그 의존 리소스를 제거한다.
5. **VPC·NAT, 상품 S3, ECR, 메시징, state와 스냅샷은 유지한다. 중지 중에도 비용이 발생한다.** 완전 무과금 중지 기능이 아니다.

### 복원에서 지키는 것

- 보존한 RDS 스냅샷으로 DB를 생성한다. 새 RDS 관리 비밀번호는 ESO가 가져온다. 이전 DB 비밀번호를 억지로 재사용하지 않는다.
- EBS 스냅샷으로 새 볼륨을 만들고 원래 AZ·PVC 이름에 연결한 뒤 Helm을 설치한다. Grafana DB와 로그인 Secret도 함께 복원한다.
- 앱 JWT·내부 토큰·관리자 입력값을 유지하고 DB 주소만 새 환경 값으로 구성한다.
- **보존 당시 Git SHA로 복구한다.** 중지 중 변경된 main을 바로 반영해 DB 스키마가 섞이는 상황을 피한다. 이후 main 전환은 별도 검토한다.
- 기본 서비스 검사와 CodeBuild 검사가 성공해도 데이터 복원이 전부 증명되지는 않는다. 보존 전에 기록한 상품·주문·이미지·대시보드를 실제로 비교해야 한다.

### 한계와 주의점

- `.lab/recovery`와 `.lab/recovery-inputs.json`을 보관한다. 비밀번호가 든 파일은 Git에 올리지 않는다. **다른 PC·다른 Windows 사용자로 암호화 파일을 옮기는 복원은 지원하지 않는다.** 팀 공용 재해 복구 체계와는 다르다.
- 한 설치 환경의 보존·복원 한 사이클을 기준으로 한다. 전체 폐기 후 새 환경에서 보존하려면 이전 recovery 폴더를 별도 보관해야 한다. 이전 기록을 자동 덮어쓰지 않는다.
- 보존 중에는 서비스가 중단된다. 라이브 무중단 복제나 Multi-AZ 장애 전환이 아니다.
- 전체 삭제는 이 실행이 기록한 스냅샷 ID·소유 태그를 확인한 뒤 폐기한다. 모르는 디스크·스냅샷은 임의 삭제하지 않고 중단한다.

## 3. 메시징 보완

- SQS 이벤트 소스의 동시 Lambda 실행을 기본 2개로 제한한다. Lambda 예약 동시 실행 한도를 따로 예약하지 않는다.
- 이 설정은 SES 초당 발송량 제한이 아니다. SES 제한/오류는 SQS 재시도와 DLQ로 드러나므로 함께 확인한다.
- 구매자·관리자 발송 결과는 별도로 중복 방지한다. 관리자로 주문하면 같은 주소라도 서로 다른 두 알림을 받을 수 있다.
- `order_email_accepted`, `order_email_duplicate_skipped`, `order_email_failed`에 주문 ID·이벤트 ID·알림 종류를 기록한다. 이메일 주소·본문·토큰은 로그에 쓰지 않는다.
- SES가 접수한 직후 DynamoDB `SENT` 기록이 실패하면 중복 발송 가능성이 남는다. 정확히 한 번 전달을 보장한다고 설명하지 않는다. `accepted`도 받은편지함 도착 보장은 아니다.

## 4. 환경 설정

공개 공통값은 `scripts/ops/environment.json`, 설치 PC의 관리자 ARN·수신 이메일은 `.lab/lab-config.json`, 비밀번호는 입력/Secret으로 나눈다. 통합한 Terraform 도메인·CodeBuild·검증 스크립트는 공통 설정을 참조한다.

Terraform S3 backend에는 locals를 사용할 수 없어 일부 값이 리터럴로 남는다. `check_environment.py`가 backend 계정·버킷·리전·profile 및 앱 Ingress 도메인의 불일치를 먼저 차단한다. 다른 계정·리전으로 완전 자동 이식된다고 가정하지 않는다. 상태 위치 변경은 반드시 별도 검토한다.

## 5. 실배포에서 남겨야 할 증거

| 검사 | 정상 기준 | 실패 시 먼저 볼 곳 |
|---|---|---|
| 최초 설치 | 기본 검사 PASS, Argo SHA와 선언 이미지 일치 | 설치 checkpoint의 실패 단계·plan·Controller 이벤트 |
| CodeBuild | VPC 실행 SUCCEEDED, 잘못된 revision은 FAILED | ENI·NAT·EKS SG·access entry·RBAC·로그 |
| 검증 권한 | Deployment 조회 허용, Secret 조회와 변경 거부 | `final-deploy-readers` Role/Binding |
| 보존 안전성 | 스냅샷 available/completed 후에만 삭제 | recovery checkpoint·원본 PVC/볼륨 매핑 |
| 실제 데이터 복원 | 동일 회원·상품·재고·주문·이미지, 저장한 대시보드 유지 | RDS snapshot ID·PVC binding·복원 AZ·Grafana Secret |
| 메일·중복·실패 | 구매자/관리자 각 도착, 반복 이벤트는 중복 건너뜀, 실패는 재시도/DLQ | Lambda 처리 단계·SES 상태·SQS/DLQ·DynamoDB |
| 마지막 전체 삭제 | 양쪽 state 비움, 기록한 스냅샷·CodeBuild·소스 S3·기존 자원·state S3 부재 | 소유권이 불명확하면 보존하고 조사 |

2026-10-21에 실제 설치·보존·복원·승인 배포·전체 삭제와 데이터 비교를 수행했다. [단계별 실제 결과](17-validation-20261021.md)에 확인 범위와 재개했던 구간을 구분했다. ALB 생성/대상 준비는 설치·복원에서 최대 10분, 기본 검증에서 최대 5분 기다리며 조회/권한 오류는 즉시 실패한다. CloudTrail 재정리는 정확한 단일 로그 버킷 오류와 계정·state·소유권을 확인한 경우에만 최대 2회 추가 시도한다. 새 재시도 로직 자체의 검증은 오프라인이며, 실제 AWS에 이 변경을 재배포해 시험한 결과로 바꿔 쓰지 않는다.

설정 참고: [CodeBuild VPC](https://docs.aws.amazon.com/codebuild/latest/userguide/vpc-support.html), [SQS 소비 동시 실행](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-scaling.html).
