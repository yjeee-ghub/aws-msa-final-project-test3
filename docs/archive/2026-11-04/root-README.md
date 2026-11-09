> **과거 문서 보존본** · 2026-11-04 최신화 전 main `cc040cf`의 원문입니다. 현재 실행 안내가 아닙니다. [현재 README](../../../README.md)와 [검증 범위](../../21-current-validation.md)를 사용하세요.

> **실행 시작점:** GUI 없이 [설치·검증·삭제 PS1 가이드](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/15-one-command-lab.md)를 사용합니다. 2026-10-21에 실제 설치 → 데이터 보존 종료 → 복원 → 승인된 최신 배포 → 전체 삭제를 수행했습니다. 중간 재실행과 수정이 있었으며, 한 번에 무중단 완료한 시험으로 설명하지 않습니다. [검증 결과와 남은 확인 범위](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/17-validation-20261021.md)

> **확인 범위:** 10월 20일에는 HPA·노드 자동 확장/축소와 실제 DB 비밀번호 회전 후 자동 갱신을 확인했습니다. 10월 21일에는 CodeBuild 내부 검증·조회 전용 권한·데이터 복원·구매자/관리자 SES 접수와 중복 건너뜀·state 버킷까지 삭제를 확인했습니다. 이번 ALB·CloudTrail **자동 재시도 변경은 코드/모의 검증 범위**이며 AWS 재배포 시험은 아직 하지 않았습니다.

> **신규 구축 준비안(아직 AWS 미실행):** 이 브랜치는 NAT를 AZ별 2개로, RDS를 Multi-AZ로 생성하도록 변경했습니다. 기존 사진·검증 결과는 이전 구성의 기록입니다. [재배포·롤백 촬영 계획과 준비 상태](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/19-ha-release-evidence.md)를 먼저 확인하세요.

# AWS · EKS 서비스 운영 프로젝트

Terraform으로 AWS 인프라를 구성하고, GitHub Actions와 Argo CD로 앱을 배포한 운영 실습 프로젝트입니다.

앱 기능 자체보다는 **배포 자동화, 모니터링, 자동 확장, 장애 복구**를 직접 확인하는 데 집중했습니다.

![AWS EKS 프로젝트 구성도](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/images/architecture.png)

## 프로젝트 문서

전체 내용을 한 페이지에 넣기보다 주제별로 나눴습니다. 처음 보는 기술도 따라갈 수 있도록 **역할 → 사용한 이유 → 실습 결과** 순서로 설명했습니다.

| 페이지 | 내용 |
| --- | --- |
| [프로젝트 구성](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/01-architecture.md) | 구성도, 주요 서비스, Terraform 폴더 분리 |
| [배포 자동화](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/02-deployment.md) | GitHub Actions → ECR → Argo CD → EKS |
| [모니터링과 실습 결과](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/03-monitoring-and-tests.md) | 지표·이메일 알림, 자동 확장, 메시징 검증 |
| [문제 해결 기록](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/04-troubleshooting.md) | Grafana 503, 관리자 로그인, Terraform 오류 |
| [프로젝트 회고](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/05-retrospective.md) | 배운 점과 실습 범위 |
| [개선 적용·검증](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/10-live-validation.md) | 원격 state, 테스트, 복원, 가용성 개선과 코드 리뷰 |

[배포 이력·이미지 태그](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/RELEASES.md) · [이전 버전으로 롤백](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/ROLLBACK.md)

## 사용 기술

Helm·Kustomize는 [배포 자동화](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/02-deployment.md), EBS는 [프로젝트 구성](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/01-architecture.md), SNS·SQS·CloudWatch·CloudTrail은 [모니터링과 실습 결과](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/03-monitoring-and-tests.md)에서 쉽게 풀어 설명했습니다.

- **인프라:** Terraform · VPC · EKS · IAM · ALB · Route 53 · ACM
- **배포:** Docker · ECR · GitHub Actions · Argo CD · Helm · Kustomize
- **데이터·운영:** RDS · S3 · EBS · Prometheus · Grafana · SNS · SQS · CloudWatch · CloudTrail

## 저장소 구조

```text
.
├── terraform-state-bootstrap/ # 따로 보관하는 state용 S3 버킷
├── terraform/          # AWS 인프라
├── terraform-k8s/      # EKS 내부 운영 도구
├── app/msa/            # 앱 코드와 배포 매니페스트
├── .github/workflows/  # 변경 서비스 테스트·이미지 빌드·태그 갱신
├── scripts/            # 빌드 대상 선택·잔여 자원·복원·접속 점검
└── docs/               # 구성·실습·문제 해결 기록
```

## 확인한 결과

- GitHub 코드 변경부터 실제 홈페이지 반영까지 배포 흐름 확인
- 파드 재생성·재배치와 파드·노드 수 변화 확인
- 운영 경보와 주문 알림 이메일 수신
- SNS → SQS → DLQ 전달 및 CloudWatch 경보 확인
- CloudTrail 작업 이력과 S3 로그 확인
- S3 원격 state 저장과 동시 작업 잠금 확인
- EKS 관리 로그 수집과 별도 RDS 복원 데이터 확인
- 프런트엔드 2개·PDB·종료 대기 설정 후 파드 교체 중 접속 확인
- Terraform 세 구성의 validate 성공과 plan에서 No changes 확인

웹사이트·Grafana·Argo CD는 공유 ALB와 개별 도메인으로 연결했습니다. 실습 인프라를 삭제한 동안에는 접속되지 않습니다.

프런트엔드는 두 파드로 구성했고, 일부 백엔드·운영 도구는 단일 파드입니다. 이번 준비안은 RDS Multi-AZ와 AZ별 NAT를 사용하지만 실제 신규 구축은 아직 검증하지 않았습니다. 모든 장애에서 무중단을 보장하는 구조는 아닙니다.

## 이번에 개선한 내용

| 개선 | 사용한 이유 |
| --- | --- |
| S3 원격 state·잠금 | Terraform이 관리하는 자원 정보를 함께 사용하고 동시 수정을 방지 |
| 변경 서비스만 테스트·빌드 | 관련 없는 이미지까지 다시 만드는 작업 감소 |
| EKS 관리 로그 | Kubernetes API 요청과 인증·감사 기록 확인 |
| 상태 점검 분리 | 시작 대기·트래픽 수신 준비·프로세스 이상을 구분 |
| 프런트엔드 2개·PDB | 노드 점검 중 최소 한 파드를 유지하도록 구성 |
| RDS 복원·운영 스크립트 | 백업 데이터 복원, 잔여 자원 조회, HTTPS 접속을 직접 확인 |

테스트 실패 시 이미지 게시를 중단하며, 배포 후에는 Actions 성공과 별도로 Argo CD 상태와 실제 접속을 확인합니다.

## 실행 안내

```powershell
.\Install-Lab.ps1 -Execute
.\Verify-Lab.ps1
.\Remove-Lab.ps1 -Execute -DiscardData
```

세 명령은 각각 설치·조회 검증·실제 전체 삭제입니다. 한꺼번에 붙여 넣어 설치 직후 삭제하지 마세요. 입력·승인·재개·최초 배포 커밋 고정과 이후 main 전환은 [실행 가이드](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/15-one-command-lab.md)를 확인하세요.

[수동 단계 참고](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/14-second-build.md) · [state 설명](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/07-terraform-state.md) · [RDS 복원 실습](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/08-rds-restore-lab.md)

state 버킷을 먼저 준비하고 **AWS 인프라 → EKS 내부 구성 → 앱 배포 → DNS 연결** 순서로 진행합니다. 새 삭제 PS1은 앱·ALB·EBS를 먼저 정리하고, 잔여 확인 후 state 버킷도 마지막에 삭제합니다. `-KeepStateBucket`으로 보존할 수 있습니다.

GitHub Actions의 이미지 게시 대상은 main입니다. 최초 자동 설치는 테스트한 배포 커밋에 고정하고, 초기 배포 PR 승인·병합 후 `Install-Lab.ps1 -Execute -PromoteMain`으로 보호된 main 추적을 켭니다. 소스 공개와 실제 배포 승인, CI 실행 허가는 구분합니다.

**브랜치:** main은 검증한 개선 버전, test는 개선 전 main 보관용입니다. 새 수정은 최신 main에서 작업 브랜치를 만들어 진행합니다. 이전 test 코드를 현재 S3 state 환경에 그대로 적용하지 않습니다.
