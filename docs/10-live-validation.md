> **과거 기록의 적용 범위** · 아래는 당시 코드·계정·브랜치·준비 상태를 보존한 원문입니다. 현재 main의 실행 안내는 [README](../README.md), 실제 완료 범위는 [최신 검증 정리](21-current-validation.md)를 사용하세요. “미실행/예정”은 작성 당시 기준입니다.

# 개선 코드 실제 적용 및 코드 리뷰

검증일: 2026-10-16. test에서 실제 AWS 검증을 마친 뒤 사용자 요청으로 개선본을 main에 반영하고 기존 main을 test에 보관했다. 현재 환경은 `github_revision = "main"`을 사용한다. 전날 기존 환경을 삭제했으므로 **새 환경을 S3 backend로 구축**했으며, 기존 자원이 있는 local state를 옮기는 실습은 이번에 수행하지 않았다.

## 적용 결과

| 항목 | 확인한 내용 |
| --- | --- |
| state 버킷 | 별도 bootstrap 6개 생성. 버전 관리, AES256 암호화, 공개 차단, TLS 정책, 삭제 보호 확인 |
| 원격 state | infra/k8s를 서로 다른 S3 키에 저장. 적용 중 두 번째 plan이 잠금으로 차단됨을 확인 |
| 기본 인프라 | 108개 신규 생성 후 DNS 레코드 3개 추가. 최종 plan `No changes` |
| EKS 내부 구성 | 11개 신규 생성 후 관리 Ingress 2개 추가. URL/sync 설정 갱신 후 plan `No changes` |
| EKS 관리 로그 | api/audit/authenticator 활성화, 로그 스트림 및 실제 감사 이벤트 조회. 보관 기간 14일 |
| 앱 배포 | Argo CD가 test를 읽어 `Synced / Healthy`. 앱 파드 6개 모두 Ready, 재시작 0 |
| 노드 | 처음 4개에서 앱 배치 중 5개로 자동 확장. 확인 시 모두 Ready |
| 서비스별 빌드 | 선택·태그 갱신 회귀 테스트 통과. 로컬 스크립트의 frontend 단독 테스트/빌드/게시 성공 |
| GitHub Actions | 5개 서비스 테스트와 이미지 빌드 성공. test의 publish는 skip. 태그/매니페스트만 변경한 실행에서는 서비스 테스트/빌드도 skip |
| 상태 점검 | Java 4개 서비스의 실제 readiness/liveness가 모두 UP. DB 장애 시 health 분리는 DB 모의 테스트로 확인 |
| 프런트엔드/PDB | 두 파드를 서로 다른 노드에 배치. 첫 축출 허용·두 번째 동시 축출 거부 확인 |
| HTTPS | 웹 화면·공개 상품 API·Grafana health·Argo health가 인증서 검증을 포함해 HTTP 200 |
| 관리자 | 앱 관리자 로그인/HTML/요약 API 정상. 비인증 요약 API 401. Grafana 및 Argo CD 로그인 성공 |
| RDS 복원 | 검증용 임시 테이블의 데이터를 스냅샷에서 별도 비공개 Single-AZ DB로 복원하여 일치 확인 |
| 실습 정리 | 원본의 임시 테이블, 복원 DB, 수동 스냅샷, 임시 MySQL Pod와 Secret 삭제 확인. 본 DB의 주소는 유지 |
| 잔여 점검 | 실제 AWS 조회 시 오류 0건. 보관 대상 state 버킷 구분 확인. 모의 테스트로 AccessDenied와 빈 결과 구분 및 VPC 하위 자원 조회 확인 |

bootstrap도 적용 후 `No changes`였다. bootstrap local state는 별도로 보관하며, 두 프로젝트 루트의 state는 S3를 기준으로 사용한다.

## 발견하여 수정한 부분

### 1. Windows에서 한글 파일을 읽지 못하던 문제

Python이 Windows 기본 인코딩으로 한글 YAML을 읽어 `UnicodeDecodeError`가 발생했다. `changed_services.py`, `update_image_tags.py`, 관련 테스트에서 UTF-8을 명시했다. 이미지 태그를 바꾸면서 한글 주석이 손상되는 것도 방지한다.

### 2. 운영 스크립트 테스트가 Windows에서 생략되던 문제

가짜 AWS CLI가 POSIX 실행 파일만 지원해 Windows에서는 5개 테스트가 skip됐다. Windows용 CMD 래퍼를 추가하여 이번에는 **Python 테스트 9개를 모두 실행해 통과**했다. 실제 AWS에 삭제 명령을 보내는 테스트가 아니다.

### 3. Git Bash 대신 WSL을 실행할 수 있던 문제

`Build-Images.ps1`의 단순 `bash` 호출은 이 PC에서 Windows의 WSL 실행기를 선택했다. Windows에서는 설치된 Git Bash를 우선 사용하고, 그 외에는 PATH의 bash를 사용하도록 수정했다. frontend 한 서비스만 선택해 실제 실행을 확인했다.

### 4. test 코드와 실제 배포 대상이 다르던 문제

Argo CD의 배포 대상이 main으로 고정되어 있으면 test의 인프라만 적용해도 앱 개선은 배포되지 않는다. `github_revision` 변수를 추가했으며 **기본은 main**이다. 이번 개인 tfvars에는 test를 명시했고 수동 테스트/이미지 게시 후 검증했다. test의 GitHub Actions AWS 게시 금지는 유지했다.

### 5. 파드 종료 중 접속 실패

첫 축출 시험에서 연속 요청 중 1회 연결 실패가 있었다. PDB는 남겨둘 파드 수를 제어하지만 ALB의 대상 변경 완료까지 기다리는 기능은 아니다. frontend에 종료 전 대기와 종료 유예를 추가했다. 반영 후 ALB의 두 대상이 healthy인지 확인하고 같은 시험을 반복했으며 **60회 모두 HTTP 200**이었다. 모든 네트워크·노드 장애 상황에서 무중단을 보장한다는 뜻은 아니다.

## 코드 리뷰와 확인 범위

- 기본 main 배포와 별도 브랜치 검증을 설정값으로 구분했다. 개선 전 main은 test에 보관했다.
- 새 ECR에는 이미지가 없으므로 최초 5개 전체 빌드가 필요하다. 이후 선택 빌드는 관련 서비스 태그만 갱신한다.
- 특정 브랜치를 Argo에 연결한 뒤에는 해당 매니페스트 push도 실제 배포될 수 있다. 코드만 작업하려면 배포 대상과 다른 작업 브랜치를 사용한다. 현재 test는 이전 버전 보관용이다.
- PDB는 자발적인 축출을 제한한다. 갑작스러운 노드 장애, 직접적인 Pod 삭제, 모든 롤링 업데이트의 가용성을 보장하지 않는다.
- DB 장애 시 liveness가 DB 상태에 의존하지 않는 것은 모의 테스트로 검증했다. 실제 운영 DB를 중단하는 장애 시험은 하지 않았다.
- RDS 복원은 임시 검증 데이터가 복원되는 것까지 확인했다. 실제 주문 데이터 전체에 대한 무손실 복구 시험은 아니다.
- 잔여 점검은 조회 전용 후보 목록이다. 조회 성공만으로 계정의 모든 리전과 모든 서비스의 비용 자원이 없다고 판단하지 않는다. 오늘은 본 환경을 유지했으므로 종료 후 전체 destroy 시험은 다시 하지 않았다.
- 개인 tfvars의 EKS 공개 API 허용 범위는 기존 `0.0.0.0/0` 설정을 유지했다. API 인증은 필요하지만, 장기 운영 시 관리 PC의 공인 IP로 좁히는 것이 좋다.
- 배포 중 초기 IP 할당·지표 미수집·startup probe 경고가 있었으며, 이후 모두 Ready 및 HPA 지표 정상으로 회복했다. 작은 노드의 자원 여유는 계속 관찰해야 한다.

## 확인에 사용한 테스트

- Java 4개 서비스: 기존 선택 테스트와 bootJar 성공. frontend: Node 테스트 5개 성공.
- Python CI/운영 스크립트 테스트 9개 성공, skip 없음.
- Terraform scheduling 모의 테스트 1개 성공, 세 루트 validate 및 최종 plan 확인.
- kubectl Kustomize 렌더링, 변경 PowerShell 구문 검사, Terraform fmt 및 Git diff 검사.
- 실제 GitHub Actions: [5개 서비스 테스트](https://github.com/yonginfra/aws-msa-final-project/actions/runs/38841058872), [태그 변경만 포함한 실행](https://github.com/yonginfra/aws-msa-final-project/actions/runs/38841382700).
- main 승격 후에도 [자동 테스트·OIDC 인증·5개 이미지 게시](https://github.com/yonginfra/aws-msa-final-project/actions/runs/38850396449)가 성공했고 배포 태그가 자동 갱신됐다. Argo 배포 대상을 main으로 바꾼 후 재계획은 No changes였다.

## 비밀번호와 다음 작업

새 환경이므로 앱 관리자 초기 비밀번호도 새로 준비했다. 비밀번호·토큰·state·plan은 Git에 올리지 않았다. 현재 클러스터에 연결한 PowerShell에서 필요한 비밀번호만 조회한다.

```powershell
# 앱 admin
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((kubectl get secret final-admin-config -n soldesk -o json | ConvertFrom-Json).data.'admin-password'))
# Grafana admin
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((kubectl get secret monitoring-grafana -n monitoring -o json | ConvertFrom-Json).data.'admin-password'))
# Argo CD admin
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((kubectl get secret argocd-initial-admin-secret -n argocd -o json | ConvertFrom-Json).data.password))
```

DB 비밀번호는 현재 앱 Secret의 DB_PW에도 동일하게 설정되어 있다. 화면 공유·보고서·Git에는 비밀번호를 복사하지 않는다. 운영 환경과 테스트용 운영 설정의 구분은 [실행 순서](06-monday-runbook.md)를 참고한다. **현재 본 실습 환경은 켜져 있으므로 EKS·EC2·RDS·NAT·ALB 등의 비용이 발생한다.**
