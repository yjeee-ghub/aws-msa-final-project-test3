> **과거 기록의 적용 범위** · 아래는 당시 코드·계정·브랜치·준비 상태를 보존한 원문입니다. 현재 main의 실행 안내는 [README](../README.md), 실제 완료 범위는 [최신 검증 정리](21-current-validation.md)를 사용하세요. “미실행/예정”은 작성 당시 기준입니다.

# 계정 전환 후 AWS 실제 실행 검증

2026-10-19 서울 리전에서 기존 test2 앱을 새 계정 환경으로 구축했다. 계정·도메인·GitHub 연결값을 전환했고, 추가로 승인받은 변경은 Lambda 예약 동시 실행 해제와 테스트 두 개의 입력 샘플 분리다. 앱 기능은 추가하지 않았다.

## 검증 결과

| 항목 | 결과 |
| --- | --- |
| 기존 Python 테스트 | 18/18 통과 |
| 5개 서비스 검사·패키징·이미지 빌드 | GitHub CI 통과 |
| 최초 이미지 게시 | ECR 5개 게시, 선언의 digest/source와 실제 이미지 비교 일치 |
| Terraform | state 준비 6개, infra 119개 생성; Kubernetes 도구와 공개 설정 적용 완료 |
| 앱 | 5개 Deployment 준비, Argo CD Synced/Healthy 및 실제 이미지 확인 |
| HTTPS | 웹 루트·상품 API, Grafana health, Argo CD health 정상 |
| 로그인 | 관리자·일반 회원 로그인, 인증된 관리자 HTML 접근 통과 |
| 주문 | 검증 상품 1개/주문 1건 생성, ORDERED 확인 |
| 중복 주문 요청 | 동일 Idempotency-Key 재전송 시 같은 주문 번호, 재고 3→2로 한 번만 차감 |
| 메일 | SNS/SQS/Lambda/SES 처리 후 DynamoDB SENT 1건 확인; DLQ 메시지 0 |

검증용 상품 `ARIA-DEPLOY-VALIDATION-20261019`, 회원 `aria-smoke-20261019`, 주문 #1은 검증 데이터로 남아 있다. 테스트는 기존 데이터를 초기화하거나 삭제하지 않았다. 메일의 SENT는 SES 발송 요청이 수락되고 처리 기록이 저장됐다는 뜻이며 받은편지함 수신을 직접 확인했다는 뜻은 아니다.

## 실행 증거

- 최초 이미지 빌드/게시 성공: https://github.com/yobi84-sy/aws-msa-final-test2/actions/runs/39215115059
- 최초 배포 설정 테스트 실패: https://github.com/yobi84-sy/aws-msa-final-test2/actions/runs/39215953425
- 테스트 입력 수정 후 전체 CI 성공: https://github.com/yobi84-sy/aws-msa-final-test2/actions/runs/39218010024
- 배포 PR: https://github.com/yobi84-sy/aws-msa-final-test2/pull/1
- 실패 원인과 수정 범위: [테스트 입력 데이터 설명](12-first-release-test-fixtures.md)

원본 `scripts/ops/check_release.py`로 커밋/Argo 상태/실제 이미지/가용 파드/TLS/HTML/상품 API 검사를 수행했다. 검증 PC에 없던 PyYAML은 CI와 동일한 6.0.3을 프로젝트 외부 도구 디렉터리에 설치했으며 앱 의존성은 바꾸지 않았다.

## 접속 및 운영상 남는 조건

- 웹: https://server.sy84.store
- Argo CD: https://argocd.sy84.store
- Grafana: https://grafana.sy84.store
- SES는 sandbox 상태다. 인증된 발신자·수신자만 발송할 수 있으며 일반 고객 이메일 전체에 발송하는 production 승인까지 확인한 것은 아니다.
- Lambda는 예약 동시 실행 -1로 계정 공용 한도를 사용한다. 검증 당시 실제 계정 한도는 10이었다. 앞서 제출한 한도 상향 요청은 취소 완료하지 못했다. 한도 증가 자체는 실행 용량 사전 구매가 아니다.
- 최초 설치에서 External Secrets와 ALB Controller의 webhook 준비 순서 경합이 있었다. 실패 release를 import하고 재적용해 복구했다. 이 의존성의 원본 코드는 변경하지 않았으므로 새 환경 첫 설치에서 재현될 수 있다.
- 최초 기본 노드는 4대이며 앱 배치 중 Cluster Autoscaler가 5대로 확장했다. 설정된 총 상한은 5대다. 실행 중인 EKS/EC2/RDS/NAT/ALB/EBS 등에는 비용이 발생한다.
- GitHub hosted runner의 EKS API 접근 허용 CIDR 문제 때문에 자동 deploy-check는 활성화하지 않았다. 허용된 검증 PC에서 동일한 검사 스크립트를 실행했다.

이 문서는 위에 기재한 동작의 실제 검증 기록이다. 모든 장애 복구, RDS 비밀번호 회전, 백업 복원, 장기 부하 및 운영 환경 전체가 검증됐다는 의미는 아니다.
