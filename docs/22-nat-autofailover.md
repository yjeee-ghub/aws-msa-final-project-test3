# TEST2 NAT 자동 우회·복귀 통합

2026-11-03 별도 최소 환경에서 시험한 방식을 TEST2 Terraform·설치·검증·보존·삭제에 연결한 코드입니다. **이 통합판은 아직 AWS에 새로 적용하거나 장애를 주입해 검증하지 않았습니다.** 이전 시험의 성공과 통합판의 로컬 검증을 구분합니다. 쇼핑몰 프런트·백엔드·RDS·배포 이미지는 변경하지 않습니다.

## 동작과 근거

```text
EventBridge 1분 예약 → VPC 밖 Lambda → SSM PrivateLink → 경로 검사 EC2
                        ↓                     ├ 앱 서브넷 검사: 현재 라우트 이용
                  DynamoDB 관찰 상태          └ 회복 검사: 원래 NAT에 계속 고정
                        ↓
              실패 2회 → 정상 대체 NAT로 앱 기본 경로 우회
              원래 경로 성공 3회 + 최소 120초 → 원래 NAT로 복귀
```

NAT 두 개만 생성한다고 자동 전환되는 것은 아닙니다. Lambda가 외부 HTTPS IPv4 접속 결과와 실제 NAT EIP를 비교하고 `ReplaceRoute`로 **등록된 앱 라우팅 테이블 두 개의 `0.0.0.0/0` 대상만** 바꿉니다. NAT 장비 교체나 NACL 자동 복구를 수행하지 않습니다. 장애 원인을 사람이 복구하면 원래 NAT의 회복을 확인한 뒤 경로만 자동 복귀합니다.

당시 별도 시험은 AZ-a→NAT-c 우회와 NAT-a 복귀를 확인했습니다. 통합 코드에서는 같은 원리를 양쪽 AZ에 적용했습니다. **AZ-c→NAT-a 방향까지 기존 AWS 시험으로 검증했다고 표현하지 않습니다.**

## 추가 자원과 비용

기존 VPC·AZ별 NAT·앱 라우팅 테이블을 재사용합니다. 기본 `nat_autofailover_enabled=true`이며 다음을 추가합니다.

| 자원 | 수량과 역할 |
|---|---|
| 프라이빗 회복 검사 서브넷·라우트 | AZ별 1개씩. 기본 10.42.31.0/24, 10.42.32.0/24. 원래 NAT에 고정 |
| t3.nano EC2 | 총 4대: 앱 경로 검사 2대 + 원래 경로 회복 검사 2대. 공인 IP·SSH 인바운드 없음 |
| gp3 루트 볼륨 | 8GiB ×4, 암호화·인스턴스 종료 시 삭제 |
| SSM Interface Endpoint | ssm·ssmmessages 두 종류, 각각 양 AZ에 배치. 총 4개 Endpoint ENI |
| EventBridge·Lambda | 1분 예약, Python 3.13, 최대 40초, 예약 동시 실행 1 |
| DynamoDB·CloudWatch Logs | AZ별 관찰·카운터·마지막 경로 / 7일 로그 |
| IAM·보안 그룹 | 전용 검사기 프로파일·Lambda 역할·SSM 443 통신 |

EKS 노드 3대와 검사 EC2 4대는 별개입니다. 검사 인스턴스·볼륨·Endpoint·호출·저장 비용이 추가되며, **보존 종료에서는 네트워크와 함께 이 자원도 남아 비용이 계속 발생합니다.** 전체 폐기에서는 같은 Terraform state로 삭제합니다.

설정은 [루트 통합](../terraform/nat_autofailover.tf), 자원은 [모듈](../terraform/nat-autofailover/main.tf), 판단은 [상태 머신](../lambda/nat_failover/decision.py), 실행은 [제어기](../lambda/nat_failover/controller.py)에 있습니다.

## 잘못된 전환을 막는 경계

- 원래 NAT 전용 검사 경로는 앱의 우회를 따라가지 않습니다. 대체 NAT로 인터넷이 된다는 사실만으로 원래 NAT가 회복됐다고 판단하지 않습니다.
- SSM 실패·타임아웃·잘못된 JSON/IP·예상 밖 EIP는 UNKNOWN/불일치입니다. NAT 장애 횟수를 쌓지 않습니다.
- 서로 다른 예약 관찰 구간만 집계합니다. 중복 이벤트는 재검사·카운터 증가를 하지 않고, 누락 구간은 연속 횟수를 초기화합니다. 오래되거나 다른 예약 출처의 쓰기 요청은 거부합니다.
- 한 Lambda의 예약 동시 실행을 1로 제한합니다. 우회·복귀 직전 경로를 다시 확인하고, 모르는 NAT나 없는 경로는 덮어쓰지 않습니다.
- NAT·검사기·라우팅 테이블의 VPC/배치와 대상 NAT의 available을 확인합니다. 원래 검사 경로가 변경되면 모든 쓰기를 거부합니다.
- 경로 쓰기 응답이나 상태 저장이 유실되면 다음 관찰에서 경로를 재확인하고 최소 유지 시간을 다시 적용합니다.
- 양쪽 경로가 모두 실패한 상황에서는 건강한 대체 경로가 없으므로 무작정 바꾸지 않습니다. 원래 경로가 회복되면 독립 성공 확인 후 복귀할 수 있습니다.
- `ReplaceRoute`에는 원자적 비교 후 쓰기 기능이 없습니다. 운영자가 동시에 경로를 수정하는 경쟁까지 제거하지 못하므로 수동 작업 전에는 제어기를 정지합니다.

## Terraform과 제어기의 소유권

Terraform은 앱 기본 경로를 **생성·삭제**하고 제어기는 실행 중 `nat_gateway_id`를 관리합니다. [기존 라우트](../terraform/network/main.tf)의 `ignore_changes = [nat_gateway_id]`로 재적용이 장애 중의 우회를 되돌리지 않게 했습니다. 따라서 Terraform plan만으로 잘못된 NAT 대상 drift를 복구한다고 기대하면 안 됩니다. 실제 경로와 제어기 관찰을 함께 검증합니다.

신규 설치를 비활성 구성으로 만들려면 최초 적용 전에 `nat_autofailover_enabled=false`를 설정합니다. 이미 실행 중인 제어기를 끌 때는 **정지→양 AZ 원래 경로 복구·통신 확인→모듈 비활성화 plan 검토** 순서가 필요합니다. flag만 끈다고 기본 경로가 자동 원복되지는 않습니다. 원래 NAT가 복구되지 않은 상태에서 원복하지 않습니다.

정적 lifecycle 설정의 특성상 비활성 구성에서도 앱 경로의 NAT 대상 drift는 Terraform이 자동 수정하지 않습니다. 그 경우 기본 검증은 같은 AZ의 원래 경로를 요구하고, 변경된 대상은 명시적으로 검토·복구해야 합니다.

## 설치·조회·보존·삭제

기존 `Install-Lab.ps1 -Execute`가 같은 인프라 단계에서 자원을 생성하고, 신선한 예약 관찰이 준비될 때까지 기다린 후 기본 검증으로 진행합니다. AWS 실행 전 생성 plan과 추가 비용을 승인합니다. 신규 AMI 버전이 공개됐다는 이유로 평상시 apply에서 검사기를 교체하지 않으며, 패치는 별도의 검토된 교체로 관리합니다.

저장소 루트에서 다음은 상태 조회만 수행하며 장애를 주입하지 않습니다.

```powershell
python scripts/ops/nat_failover.py
python scripts/ops/nat_failover.py --wait-ready
```

최신 예약 관찰·실제 앱 라우트·외부 IP가 일치한 우회만 기본 네트워크 검증에 허용합니다. 오래된 상태, 정지된 제어기, 수동 경로 불일치와 실제 통신 실패는 PASS로 숨기지 않습니다.

보존 종료와 전체 삭제는 예약 규칙을 끄고 Lambda 신규 실행을 막은 뒤 최대 실행 시간을 기다립니다. 진행 중인 제어기가 삭제와 경쟁하지 않게 하는 과정입니다. 보존 후 복원은 Terraform이 예약·동시 실행 설정을 복구하고 새 관찰을 확인합니다. 전체 삭제 감사에는 Lambda·예약 규칙·DynamoDB·로그와 기존 VPC 하위 자원·볼륨·IAM을 포함합니다. AccessDenied는 자원 없음으로 처리하지 않습니다.

## 검증과 남은 실험

로컬에서는 우회·복귀, 반대 AZ 방향, 중복/누락 예약, UNKNOWN, 수동 drift, 응답 유실, 두 경로 동시 실패, 정지·상태 조회 경계를 검사합니다. Terraform은 공급자를 모의 처리해 검사기의 사설 배치·원래 경로 고정·SSM·IAM 범위·동시 실행을 검사합니다. 실제 AWS에 연결하지 않습니다.

2026-11-05 로컬 결과는 Python 자동화 검사 **152개 통과**, Terraform validate·포맷 검사 통과, AWS 공급자를 모의 처리한 Terraform 시험 **3개 통과**입니다. 이 수치는 쇼핑몰 전체 Java 테스트나 AWS 통합 시험 수가 아닙니다. [통합판 검증 결과](validation/nat-integration-qa-20261105.json)

통합판의 신규 설치→SSM 준비→양방향 장애 주입→복귀→재적용 중 우회 유지→보존·복원→전체 삭제는 다음 승인된 AWS 시험에서 확인할 범위입니다. 기존 전체 쇼핑몰 복원 성공을 이 통합판의 검증으로 대체하지 않습니다.

기존 촬영용 NACL 전체 차단을 TEST2에 그대로 옮기지 않았습니다. 현재 퍼블릭 서브넷은 ALB도 사용하므로, 전체 차단은 NAT 외의 사용자 접속에도 영향을 줍니다. 실제 장애 주입 방법·영향 범위는 별도로 검토해야 합니다.

이 방식은 수 분의 감지·확인 시간이 필요하고 기존 NAT 연결 세션을 이전하지 못합니다. 모든 외부 목적지의 장애나 전체 AZ 중단을 감지하는 구성도 아닙니다. 애플리케이션의 재연결·재시도는 계속 필요합니다.

참고: [AWS SSM PrivateLink와 Endpoint](https://docs.aws.amazon.com/systems-manager/latest/userguide/setup-create-vpc.html), [EC2 ReplaceRoute](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_ReplaceRoute.html), [EC2 IAM 권한의 route-table 범위](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html), [Terraform ignore_changes](https://developer.hashicorp.com/terraform/language/meta-arguments/lifecycle#ignore_changes).
