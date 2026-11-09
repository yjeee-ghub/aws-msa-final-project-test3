# 주문 복구·메시징·관측과 장애 대응

구현 설명과 실제 실행 결과를 분리합니다. 현재 코드 기준은 main `cc040cf`이며 [날짜별 검증 범위](21-current-validation.md)를 함께 읽습니다.

## 주문 상태와 Outbox

[OrderingService와 트랜잭션 코드](../app/msa/ordering/src/main/java/com/example/ordersystem/ordering/service)는 Idempotency-Key로 중복 주문을 제어합니다. 같은 회원·키의 다른 요청은 충돌로 거부하고, 처리 중 상태와 lease를 DB에 저장합니다. 재고 예약 ID도 요청에서 결정적으로 만들어 재시도 때 같은 예약을 참조합니다.

상품 예약과 수신자 조회 준비에 실패하면 보상 상태를 남기고 예약을 해제합니다. 확정 응답 유실 등은 CONFIRMING에서 재개하며 확정된 재고를 임의로 되돌리지 않습니다. 복구 작업이 PENDING·CONFIRMING·COMPENSATING 상태를 재조회합니다. 외부 호출을 DB 트랜잭션 하나에 가두는 구조가 아닙니다.

최종 ORDERED 변경과 Outbox 이벤트 생성은 같은 DB 트랜잭션입니다. [OrderNotification](../app/msa/ordering/src/main/java/com/example/ordersystem/ordering/service/OrderNotification.java)은 발행 대상을 claim하고 SNS 접수 후 SENT를 기록하며 실패 시 backoff로 재시도합니다. 접수 뒤 상태 기록 실패 구간에는 이벤트가 중복될 수 있습니다. 로컬 주문·예약 검사 결과를 모든 AWS 네트워크 장애에서 복구 완료한 증거로 확대하지 않습니다.

## 주문 메일 처리

```text
Ordering Outbox → 주문 SNS → SQS → Lambda → SES → 구매자 / 관리자
                              ├→ 반복 실패 → DLQ
                              └→ DynamoDB 이벤트별 중복 제어
```

[customer_email.tf](../terraform/customer_email.tf)와 [Lambda 코드](../lambda/order_email/handler.py)는 SQS partial batch failure, 가시성 120초·최대 수신 5회·DLQ 14일 보관, 소비 동시 처리 기본 상한 2를 구성합니다. DynamoDB는 lease와 SENT 상태, TTL 30일로 이벤트를 관리합니다. 구매자·관리자 발송의 중복 키를 구분하며 관리자가 구매한 경우도 두 알림의 목적은 다릅니다.

발신자 설정이 있어야 메일 자원을 만들고 소비자는 기본 비활성입니다. SES 리전·발신자 인증 및 sandbox 수신자 제한을 확인한 뒤 활성화합니다. 동시 처리 상한은 SES 초당 발송률 보장값이 아닙니다. 실제 발송 뒤 SENT 기록이 실패하는 구간까지 정확히 한 번 전달을 보장하지 않습니다.

로그는 단계·orderId·eventId·오류 코드·SES 접수 ID로 추적하고 이메일 본문·주소·토큰을 남기지 않도록 합니다. SES MessageId는 발송 접수 근거이며 받은편지함 도착은 별도 확인입니다. 11월 2일 구매자·관리자 수신은 사용자 확인이 있는 기록입니다.

DLQ는 곧바로 비우지 않습니다. 오류 원인과 수신자·eventId를 확인하고 수정 후 재처리하거나 승인받은 테스트 메시지만 폐기합니다. 기존 큐 메시지의 수신 주소는 관리자 설정 변경만으로 자동 수정되지 않습니다.

## 지표·로그·운영 알림

- **Prometheus → Grafana:** ServiceMonitor가 앱 `/actuator/prometheus`를 수집하고 Grafana가 조회합니다. 대시보드 ConfigMap과 sidecar를 사용합니다.
- **Prometheus → Alertmanager → 운영 SNS:** 앱·클러스터 경보를 이메일 구독으로 전달합니다. Grafana가 모든 알림의 중계자인 구조가 아닙니다.
- **CloudWatch:** RDS·SQS 지표와 Lambda·CodeBuild·EKS 로그를 확인합니다. 주문 큐의 오래된 메시지와 DLQ 적재를 경보로 보냅니다. ASG 확장/축소/실패도 운영 SNS로 알립니다.
- **CloudTrail → 전용 S3:** AWS 관리 작업의 감사 로그입니다. 앱의 주문 처리 로그와 구분합니다.
- **EBS:** Prometheus·Grafana·Alertmanager의 영속 데이터이며 스냅샷 보존·PVC 복원 흐름에 포함됩니다.

근거: [Helm·모니터링 설정](../terraform-k8s), [AWS 경보](../terraform), [운영 자동화](../scripts/ops).

## 자동 확장과 DB 비밀번호 갱신

metrics-server의 지표로 Member HPA가 CPU 요청량 대비 60%를 목표로 1~3개 파드를 조절합니다. Cluster Autoscaler는 배치할 용량이 없는 Pending 파드를 근거로 관리형 노드 그룹을 늘립니다. CPU 부하만으로 노드를 직접 늘리는 것과 구분합니다. 10월에는 실제 확장·축소를 확인했으나 모든 백엔드 HPA가 활성화된 것은 아닙니다.

RDS 비밀번호는 Secrets Manager→ESO(1분)→Secret→CronJob(1분)→세 앱 순차 교체로 전달합니다. Job의 READY/PASS는 DB 연결 준비까지 확인한 결과입니다. 초기 ApiError 실패 기록과 이후 성공을 구분하며, HTTP 409 재시도 코드·로컬 테스트가 실제 최초 오류 원인을 모두 확정한 것은 아닙니다.

## 장애 시험의 정확한 의미

| 시험 | 관찰 | 주장하지 않는 범위 |
|---|---|---|
| V2 상세 오류·롤백·V3 | Pod 정상이어도 사용자 기능 실패, 이전 digest 복구 후 수정 배포 | DB 스키마 롤백·전체 서비스 무중단 |
| RDS 강제 장애 조치 | AWS 이벤트와 endpoint IP의 실제 AZ c→a 변경, 일시 실패 후 상품 API 복구 | AZ 전체를 실제 중단, 연결 중단 0초 |
| 11/2 NAT 경로 분리 | AZ-a 경로 차단 중 a 외부 통신 실패·c 유지, 경로 원복 | 다른 NAT로 자동 전환 |
| 11/3 NAT 별도 컨트롤러 | 장애 주입 후 예약 검사 기반 NAT-c 우회·회복 확인 후 복귀 | 새 양방향 통합판의 AWS 검증 |

현재 변경은 이 원리를 [NAT 통합 코드](22-nat-autofailover.md)로 연결했습니다. 양방향 상태 머신·중복 이벤트·경로 소유권·제어기 정지·잔여 검사에 로컬 검사를 추가했으며 AWS 재시험은 별도입니다.

보존·복원은 10월 실행 기록, HA 배포·장애 시험은 11월 실행 기록입니다. 서로 다른 날의 사진과 결과를 한 번의 연속 무오류 실행으로 소개하지 않습니다. [근거와 한계](21-current-validation.md)
