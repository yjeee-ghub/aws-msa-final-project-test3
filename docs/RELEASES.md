# 배포 이력 · 승인된 이미지와 사용자 동작

현재 배포 선언은 [release.json](../deploy/release.json), 실제 실행 이미지 선언은 [kustomization.yaml](../app/msa/kustomization.yaml)입니다. 이력의 배포 성공은 당시 기록이며 현재 사이트가 실행 중임을 뜻하지 않습니다.

## 2026-11-02 · V1 → V2 장애 → 롤백 → V3

인프라는 처음부터 NAT 2개·RDS Multi-AZ로 구축했습니다. 아래 앱 전환은 프런트엔드 이미지 변경이며 회원·상품·주문·Gateway 이미지와 DB를 유지했습니다. V1은 초기 Soldesk 화면을 현재 API·인증에 맞춘 디자인입니다. 초기 앱과 DB 전체를 되돌린 시연이 아닙니다.

| 단계 | 검토·배포 PR | 사용자 관찰과 검증 |
|---|---|---|
| V1 정상 | [소스 #21](https://github.com/yobi84-sy/aws-msa-final-test2/pull/21), [이미지 #22](https://github.com/yobi84-sy/aws-msa-final-test2/pull/22) | 초기 디자인, 상품 상세 정상, 기존/새 파드 준비 상태와 완료 화면 |
| V2 장애 | [소스 #23](https://github.com/yobi84-sy/aws-msa-final-test2/pull/23), [이미지 #24](https://github.com/yobi84-sy/aws-msa-final-test2/pull/24) | test2 디자인으로 변경, 의도적인 상세 URL 파라미터 불일치. Pod Healthy·목록 API 정상이어도 상세 실패 |
| 정상 V1 복구 | [롤백 #25](https://github.com/yobi84-sy/aws-msa-final-test2/pull/25) | 이전 V1 digest 복구, 동일 상품·재고 10·이미지 유지, 상세 동작 PASS |
| V3 수정 | [소스 #26](https://github.com/yobi84-sy/aws-msa-final-test2/pull/26), [이미지 #28](https://github.com/yobi84-sy/aws-msa-final-test2/pull/28) | 파라미터 수정·캐시 구분, 카드→상세 회귀 검사 추가, 실제 상세 정상 |

V1 정상 배포 참조는 `eed1154b290cdcf348f899628a02c11e4f139067`, 롤백 반영은 `58cab23d250141bf41b9e66cbb89632166028aa4`입니다. 최종 V3의 소스는 `0e2263d3be9c14d8bbfd5b121734eeeef58c9a1e`, #28 병합은 `cc040cf5d8f621d19d3851aa1a59ae2229815e53`입니다.

| 버전 | 프런트엔드 이미지 digest |
|---|---|
| V1 | `sha256:b2ee7fc76d872058c7d5b0003798a80a31b5008931d8988411d35f0ec81f4de9` |
| V2 | `sha256:08a5c2988c771511e789d0b3e91b596987b44f0a738b74590c1a3268b0478840` |
| V3 | `sha256:4f83675bb65e21b6938591779c3dc068daabb473556ce2382928ca97757d7a4f` |

[검증 범위](21-current-validation.md) · [디자인 시연의 원래 설명](20-original-storefront-demo.md) · [롤백 절차](ROLLBACK.md)

## 이전 배포 기록

과거 태그·브랜치 기반 실습 내용은 [최신화 전 이력 원문](archive/2026-11-04/RELEASES.md)에 보존했습니다. 현재 digest 승인 배포의 실행 지침으로 사용하지 않습니다.
