> **과거 기록의 적용 범위** · 아래는 당시 코드·계정·브랜치·준비 상태를 보존한 원문입니다. 현재 main의 실행 안내는 [README](../README.md), 실제 완료 범위는 [최신 검증 정리](21-current-validation.md)를 사용하세요. “미실행/예정”은 작성 당시 기준입니다.

# NAT 2개 · RDS Multi-AZ 신규 구축과 실제 재배포 촬영

## 현재 상태와 발표에서 사용할 표현

이 변경은 **로컬 준비 단계**다. AWS 생성·장애 재현·배포·롤백·삭제는 아직 수행하지 않았다.
이전 Single-AZ/NAT 1개 검증을 새 구성에서 수행한 것으로 표현하지 않는다.
이번 실행은 처음부터 **AZ별 NAT 2개와 RDS Multi-AZ DB 인스턴스**로 생성한다.
RDS 대기 DB는 읽기 분산용이 아니다. Multi-AZ 설정 확인과 실제 장애 전환 검증은 다르다.
이번 필수 범위에는 RDS 강제 장애 전환·DB 스키마 변경이 없다.

V1은 **초기 디자인을 참고한 기본 화면 시연 버전**이다. 강사님 초기 소스 전체를 그대로
재현했다고 표현하지 않는다. 회원·상품·주문 백엔드, 인증, DB는 현재 test2를 유지한다.
V2의 상품 상세 연결 오류는 **격리된 실습 환경에서 의도적으로 재현**한다.

## 시작 조건

1. AWS 로그인·콘솔 캡처 가능 여부·PowerShell 창 확인. Billing의 실제 크레딧 잔액,
   유효 기간, 적용 서비스와 미청구 사용액을 확인하고 예상 총비용에 여유가 있을 때 시작한다.
   잔액이 있다는 사실만으로 개인 결제 0원을 보장하지 않는다.
2. `git fetch origin main` 후 준비 브랜치/커밋을 확인한다. main 직접 push·보호 규칙 우회는 하지 않는다.
3. 소스 변경 PR과 이미지 배포 PR에 기존 검사·동료 승인을 유지한다. 팀원에게 승인 가능한 시간을 확인한다.
   각 버전의 소스·이미지 PR이 따로 필요할 수 있으므로 승인 대기도 전체 시간에 포함한다.
4. 프로젝트 VPC/EKS/RDS/state 잔여 여부를 먼저 조회한다. 기존 자원이 있다면
   ‘처음부터 생성’ 사진을 찍기 위해 임의 삭제하지 말고 별도로 범위·계획을 확인한다.
5. 비밀번호·토큰·Secret 값·state 내용은 촬영하지 않는다. 캡처 저장 위치와 디스크 여유 확인.

## 촬영 순서와 진행 조건

실행은 기존 `Install-Lab.ps1` / `Verify-Lab.ps1` / `Remove-Lab.ps1` 절차를 따른다.
모든 명령은 저장소 루트에서 실행한다. 관찰 스크립트는 읽기 전용이다.
**PowerShell 관찰 창과 브라우저 촬영 준비를 먼저 완료하고, 그다음 변경을 시작한다.**

| 번호 | 실제 작업 | PowerShell 증거 | AWS·웹 증거 | 다음 단계 조건 |
| --- | --- | --- | --- | --- |
| A | 계정·크레딧·초기 자원 확인 | 계정·커밋·기존 자원 조회 | Billing 확인(공유본 민감정보 가림) | 계정·비용·촬영 확인 |
| B | 신규 infra 생성 | plan의 NAT 2개·RDS multi_az=true, apply 진행·완료 | 각 AZ NAT available, 라우팅, RDS Multi-AZ·주/대기 AZ | `verify_lab.py infra` PASS |
| C | V1 기본 화면 최초 배포 | CI/ECR·Argo revision·이미지 digest·Ready | 기본 화면·상품 상세 정상·같은 시험 상품 ID | 정상 V1 release commit/digest 기록 |
| D | V2 디자인 개선 + 의도적 링크 오류 배포 | 기존/새 Pod, RS, Ready·이미지·revision 변화 | 승인 PR·Argo 과정·개선 메인·상세 오류 | 이미지 일치 + 실제 오류 확인 |
| E | V1 정상 이미지로 롤백 | rollback PR/승인·교체 관찰·V1 digest | 같은 상품 상세 정상 복귀 | 정상 기능·기존 데이터 확인 |
| F | 수정 완료 V3 재배포 | navigation 회귀 검사·CI·승인·교체·검증 | 최종 test2 디자인·같은 상품 상세 정상 | 모든 사진·정상 최종 버전 확인 |
| G | 전체 삭제 | Controller 유지 중 ALB/EBS 정리 → infra → state 정리 | NAT/RDS/EKS·저장소 잔여 재조회 | 승인된 범위 잔여 0 확인 |

AWS에서 **RDS 인스턴스 행은 Multi-AZ여도 1개**로 보일 수 있다. 설정의 Multi-AZ,
주 AZ와 보조 AZ를 촬영한다. 대기 인스턴스를 독립적인 읽기 복제본 1행으로 기대하지 않는다.
NAT를 AZ별로 두는 것은 서로 다른 AZ의 외부 통신 경로를 분리하는 것이다.
NAT 두 개 사이의 자동 우회가 구성되는 것은 아니다.

### PowerShell 관찰 명령

아래 창을 먼저 켜두고 관찰이 성공한 뒤 아리아가 배포를 시작한다.
관찰은 최대 15분 후 종료하며 Ctrl+C는 관찰만 멈춘다. 필요하면 다시 켠다.

```powershell
& (Join-Path $PWD 'scripts/demo/Watch-LabEvidence.ps1') -Mode Deployment -Label V2-rollout
```

HA 생성 완료 결과는 다음으로 촬영한다.

```powershell
& (Join-Path $PWD 'scripts/demo/Watch-LabEvidence.ps1') -Mode HA -Label initial-HA -Once
python scripts/ops/verify_lab.py infra --report .lab/release-demo/evidence/infra.json
```

조회 로그는 `.lab/release-demo/evidence/`에 시각·라벨별 JSONL/텍스트로 저장된다.
조회 실패를 정상/자원 없음으로 바꾸지 않는다. 저장된 과거 기록을 나중에 표시할 경우
‘실시간’이 아니라 **당시 관측 기록**으로 표시한다. 로그는 원본 화면 캡처를 대체하지 않는다.

## 앱 버전 준비 도구 (로컬 수정만)

`python scripts/demo/prepare_frontend.py baseline --write`는 기본 메인 디자인,
`fault --write`는 현재 디자인 + 상세 링크 오류,
`final --write`는 정상 test2 + 상품 링크 회귀 테스트를 준비한다.
이 명령은 Docker·AWS·push·PR·배포를 실행하지 않는다.
최초 백업은 `.lab/release-demo/source`에 보관하므로 시연 완료 전 지우지 않는다.
단계 전환 사이에 프런트를 직접 수정하면 덮어쓰지 않고 중단한다.

진행 시 baseline → fault → final 순서로 소스 PR·CI·이미지 PR·승인 절차를 밟는다.
실제 서비스 롤백은 소스를 수동 편집하지 않고 **기록한 V1 release commit의 정상 이미지 digest**를
기존 `scripts/ops/rollback_release.py --release-commit <40자리 SHA>`로 제안해 승인 후 반영한다.
이 도구는 다섯 서비스 이미지를 해당 배포로 되돌리므로, 시연 중 백엔드의 별도 변경이 없고
백엔드 digest가 동일한지 반드시 비교한다. DB·Terraform은 롤백하지 않는다.
작업 전에는 커밋되지 않은 변경이 없어야 하며 PR 생성은 실제 실행 시 진행한다.

### 오류와 검사 범위

V2는 `/product-detail.html?id=7` 대신 `?productId=7` 링크를 생성하지만 상세 화면은
계속 `id`를 읽는다. 따라서 메인·상품 목록 API는 정상이어도 상세 화면에
**‘상품 정보가 없습니다.’**가 표시된다. 주문 API·재고는 건드리지 않는다.

현재 CI의 장바구니·관리자 테스트와 `check_release.py`의 홈페이지/상품 API 검사는
이 링크 연결을 검사하지 않는다. 검사·승인 기능을 끄거나 결과를 조작하지 않는다.
실제 실행 시 검사 범위가 변경돼 오류를 차단하면 그 차단 결과를 존중하고 시나리오를 재검토한다.
V3에 새로 추가하는 navigation 테스트는 링크 생성과 카드 렌더링을 검사한다.
브라우저에서 클릭해 상세 내용이 표시되는 실제 확인은 별도로 수행한다.

## 자료 정리와 PPT 반영

원본 / 필요한 부분을 연결하고 표시한 편집본 / PPT용 이미지로 구분한다.
사진에는 실제 버전·시각·PR/commit·관찰 지점을 적되 비밀번호 등은 가린다.
같은 상품·이미지 digest·revision을 비교해 V1→V2→rollback→V3를 한 배포 이야기로 연결한다.
검증 성공을 합성하거나 실제로 하지 않은 시험 사진을 만들지 않는다.

5번 구성도, 리소스 수량표, NAT/Single-AZ 한계 설명은 새 실측 구성으로 수정한다.
기존 운영 시험 사진은 이전 구성에서 수행한 증거로 보존한다.
전체 앱·DB를 개선 배포한 것으로 설명하지 않고 **프런트엔드 변경 배포·복구 시연**으로 설명한다.
이번 핵심 사진을 확인한 뒤, 기존 승인 범위 내 전체 삭제를 진행하고 최종 잔여를 조회한다.

## 준비 상태와 미검증 범위

- 로컬: Terraform 형식·validate, HA 경로 검사, 프런트 단계별 정상/오류/정상 계약 검사.
- 아직 안 함: 실제 신규 AWS plan/apply, NAT 외부 통신, RDS Multi-AZ 생성, 실제 앱 배포·롤백,
  콘솔 촬영, 크레딧 적용 확인, 전체 삭제. 집에서 실제 실행으로 확인한다.
- 강제 RDS failover, AZ 장애, 모든 장애에서 무중단 보장은 이번 증거 범위가 아니다.
