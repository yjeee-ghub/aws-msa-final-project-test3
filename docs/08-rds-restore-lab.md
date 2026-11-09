> **과거 기록의 적용 범위** · 아래는 당시 코드·계정·브랜치·준비 상태를 보존한 원문입니다. 현재 main의 실행 안내는 [README](../README.md), 실제 완료 범위는 [최신 검증 정리](21-current-validation.md)를 사용하세요. “미실행/예정”은 작성 당시 기준입니다.

# RDS를 별도 DB로 복원하는 실습

원본 `final-ordermsa-db`를 덮어쓰거나 삭제하지 않는다. `Invoke-RdsRestoreLab.ps1`은 기본 `Inspect`(조회)이며, 스냅샷 생성·복원·정리는 별도 모드와 확인 질문이 필요하다. 2026-10-16 실제 복원·데이터 확인·실습 자원 정리 결과는 [검증 기록](10-live-validation.md)에 남겼다. 실습 DB와 수동 스냅샷은 추가 비용이 들며 Terraform state 밖에 생성하므로 프로젝트 destroy 전에 별도 정리한다.

## 1. 기준 데이터 확인

EKS와 RDS가 정상인 상태에서 수행한다. 원본 데이터의 기준 시점과 테이블별 행 수, 확인할 상품/주문 번호 등을 기록한다. 개인정보를 보고서에 복사하지 않는다. 접속은 기존 EKS 보안그룹에서 허용된 클러스터 내부 임시 MySQL 클라이언트를 이용한다. RDS를 공인으로 전환하거나 SG를 0.0.0.0/0으로 열지 않는다.

```powershell
Set-Location 'C:\aws-msa-backend-terraform'
./scripts/ops/Invoke-RdsRestoreLab.ps1 -Mode Inspect
kubectl run rds-lab-client -n soldesk --image=mysql:8.4 --restart=Never --command -- sleep 3600
kubectl wait pod/rds-lab-client -n soldesk --for=condition=Ready --timeout=120s
# 원본 Endpoint는 Inspect 결과에서 확인한다. -p 다음에 비밀번호를 쓰지 않는다.
kubectl exec -it rds-lab-client -n soldesk -- mysql -h <원본-Endpoint> -u admin -p ordermsa
```

MySQL에서 읽기 전용 확인을 한다. 테이블 이름은 `SHOW TABLES` 결과와 기존 JPA 매핑으로 확인한다. 추정한 이름으로 삭제나 DDL을 실행하지 않는다.

```sql
SELECT @@hostname, DATABASE(), CURRENT_TIMESTAMP;
SHOW TABLES;
-- SHOW TABLES에서 확인한 실제 테이블 이름으로 반복
-- SELECT COUNT(*) FROM 실제_테이블;
-- SELECT id, name, stock_quantity FROM product ORDER BY id LIMIT 5;
exit
```

## 2. 스냅샷 생성 후 별도 DB 복원

공유 DB에서 쓰기가 계속되면 기준 조회와 스냅샷 사이 데이터가 달라질 수 있다. 실습 시 앱 쓰기를 잠시 멈추거나 변경 시점을 기록해 예상 행 수를 비교한다. RDS 스냅샷은 장기적인 앱 무손실 복구를 자동 보장하는 기능과 다르다.

```powershell
$suffix = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = "final-rehearsal-$suffix"
$restored = "final-restore-$suffix"
# 실행 전에 변경 대상 확인 (-WhatIf도 계정/원본의 읽기 조회는 수행)
./scripts/ops/Invoke-RdsRestoreLab.ps1 -Mode Snapshot -SnapshotId $snapshot -WhatIf
./scripts/ops/Invoke-RdsRestoreLab.ps1 -Mode Snapshot -SnapshotId $snapshot
./scripts/ops/Invoke-RdsRestoreLab.ps1 -Mode Restore -SnapshotId $snapshot -RestoreDbId $restored -WhatIf
./scripts/ops/Invoke-RdsRestoreLab.ps1 -Mode Restore -SnapshotId $snapshot -RestoreDbId $restored
```

복원은 원본의 DB 클래스·서브넷 그룹·SG를 명시하며 `--no-publicly-accessible`, `--no-multi-az`를 사용한다. 원본과 같은 이름 또는 이미 존재하는 대상이면 거부한다. waiter가 시간 초과돼도 DB가 생성 중일 수 있으므로 동일 생성 명령을 반복하지 말고 Inspect/콘솔로 상태를 확인한다. 사용자가 프로세스를 중단했어도 AWS 생성이 취소되는 것은 아니다. 복원 DB는 스냅샷 시점의 원본 관리자 비밀번호를 사용한다.

## 3. 복원된 데이터 확인

스크립트가 출력한 **별도 복원 Endpoint**로 접속한다. 기존 Kubernetes Secret의 DB_HOST와 앱 설정은 바꾸지 않는다. 복원한 DB에 운영 앱을 연결하면 JPA의 ddl-auto/update나 주문 처리로 데이터가 바뀔 수 있으므로 이 실습은 클라이언트 조회로 한정한다.

```powershell
kubectl exec -it rds-lab-client -n soldesk -- mysql -h <복원-Endpoint> -u admin -p ordermsa
```

1번의 SELECT·SHOW TABLES와 테이블별 COUNT를 반복한다. 원본/복원 호스트명이 서로 다른지, 스키마·기준 데이터·스냅샷 시점의 행 수가 예상과 일치하는지 기록한다. 복원 후 원본 앱에서 상품 목록이 정상인지도 확인한다. 스냅샷 완료 시간, 복원 요청 시간, DB available 시간, 실제 데이터 조회 성공 시간을 적으면 실습 복구 소요 시간을 비교할 수 있다.

## 4. 실습 자원만 정리

스크립트는 `final-restore-*`/`final-rehearsal-*` 이름과 `Purpose=RestoreRehearsal` 태그를 확인한다. DB 삭제와 스냅샷 삭제는 별도다. 확인 질문의 식별자를 다시 읽는다.

```powershell
./scripts/ops/Invoke-RdsRestoreLab.ps1 -Mode CleanupDb -RestoreDbId $restored -WhatIf
./scripts/ops/Invoke-RdsRestoreLab.ps1 -Mode CleanupDb -RestoreDbId $restored
# DB 삭제가 완료된 뒤 수동 스냅샷 보관 여부를 결정
./scripts/ops/Invoke-RdsRestoreLab.ps1 -Mode CleanupSnapshot -SnapshotId $snapshot -WhatIf
./scripts/ops/Invoke-RdsRestoreLab.ps1 -Mode CleanupSnapshot -SnapshotId $snapshot
kubectl delete pod rds-lab-client -n soldesk --wait=true
./scripts/ops/Get-ProjectResidue.ps1
```

원본 DB를 삭제하는 명령은 이 스크립트에 없다. 실습 DB가 남으면 기존 SG/서브넷 그룹을 사용하므로 Terraform의 네트워크 destroy가 실패할 수 있다. 먼저 실습 DB를 정리한다.
