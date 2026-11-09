# 문서 목록과 적용 범위

## 현재 실행과 설명

- [프로젝트 README](../README.md)
- [현재 아키텍처와 코드 근거](01-architecture.md)
- [이미지 배포와 CodeBuild](02-deployment.md)
- [주문 복구·메시징·모니터링](03-monitoring-and-tests.md)
- [설치·검증·삭제 PS1](15-one-command-lab.md)
- [통합 운영·보존·복원](16-integrated-operations.md)
- [배포 이력](RELEASES.md) · [롤백](ROLLBACK.md)
- [AWS / 로컬 검증 범위](21-current-validation.md)
- [NAT 자동 우회·복귀 통합](22-nat-autofailover.md)
- [아키텍처 이미지와 로고 출처](images/README.md)

## 과거 실습 기록

아래 문서는 당시 구성과 장애를 보존한 기록입니다. 옛 계정·브랜치·태그·수량을 현재 환경에 그대로 적용하지 않습니다. 현재 출발 브랜치는 main입니다. 기록의 원문을 현재 실행 결과로 덮어쓰지 않습니다.

| 문서 | 역할 |
|---|---|
| [04 문제 해결](04-troubleshooting.md) · [05 회고](05-retrospective.md) | 초기 장애·학습 기록 |
| [06 점검 순서](06-monday-runbook.md) · [07 state](07-terraform-state.md) · [08 RDS 복원](08-rds-restore-lab.md) | 당시 수동 실습 절차 |
| [09 로컬 검사](09-local-validation.md) · [10 개선 검증](10-live-validation.md) | 당시 코드·AWS 검증 |
| [11 TEST2 전달](11-test2-delivery.md) · [12 테스트 데이터](12-first-release-test-fixtures.md) | 초기 승인 배포·검사 도입 |
| [13 계정 배포](13-account-deployment-validation.md) · [14 2차 빌드](14-second-build.md) | 계정 설정·개선 기록 |
| [17 10월 21일 검증](17-validation-20261021.md) | 보존·복원·권한·메시징·삭제 실행 기록 |
| [19 HA 촬영 계획](19-ha-release-evidence.md) | 11월 2일 실행 전 계획. 현재 완료 범위는 21번 문서 |
| [20 초기 디자인 시연](20-original-storefront-demo.md) | V1/V2/V3 설계·당시 준비 기록 |

## 최신화 전 원문 스냅샷

2026-11-04에 재작성한 문서의 이전 원문입니다. 상대 링크는 당시 main 커밋의 GitHub 경로로 고정했습니다.

- [README](archive/2026-11-04/root-README.md)
- [아키텍처](archive/2026-11-04/01-architecture.md)
- [배포](archive/2026-11-04/02-deployment.md)
- [모니터링](archive/2026-11-04/03-monitoring-and-tests.md)
- [배포 이력](archive/2026-11-04/RELEASES.md)
- [롤백](archive/2026-11-04/ROLLBACK.md)

- [설치 가이드 이전 원문](archive/2026-11-04/15-one-command-lab.md)
- [통합 운영 이전 원문](archive/2026-11-04/16-integrated-operations.md)
