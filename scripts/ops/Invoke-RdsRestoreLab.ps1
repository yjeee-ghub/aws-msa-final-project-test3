# 기본 Inspect는 조회만 합니다. 변경 단계는 모드와 확인을 명시해야 실행됩니다.
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [ValidateSet('Inspect','Snapshot','Restore','CleanupDb','CleanupSnapshot')][string]$Mode = 'Inspect',
    [ValidatePattern('^sol-test3-rehearsal-[a-z0-9-]+$')][string]$SnapshotId,
    [ValidatePattern('^sol-test3-restore-[a-z0-9-]+$')][string]$RestoreDbId,
    [string]$Profile = '512-team01',
    [string]$Region = 'ap-northeast-2'
)
$ErrorActionPreference = 'Stop'
$env:AWS_PAGER = ''
$sourceId = 'sol-test3-ordermsa-db'
function Invoke-AwsJson([string[]]$Arguments) {
    $result = & aws @Arguments --profile $Profile --region $Region --output json --no-cli-pager 2>&1
    if ($LASTEXITCODE -ne 0) { throw "AWS 명령 실패: $($result -join ' ')" }
    if ($result) { return (($result -join "`n") | ConvertFrom-Json) }
}
function Require-LabTag($Tags) {
    if (-not ($Tags | Where-Object { $_.Key -eq 'Purpose' -and $_.Value -eq 'RestoreRehearsal' })) {
        throw '복원 실습 태그가 없어 정리를 거부합니다.'
    }
}
$identity = Invoke-AwsJson @('sts','get-caller-identity')
if ($identity.Account -ne '683668078297') { throw '프로젝트 AWS 계정과 다릅니다.' }
if ($Mode -eq 'Inspect') {
    $data = Invoke-AwsJson @('rds','describe-db-instances')
    $data.DBInstances | Where-Object { $_.DBInstanceIdentifier -eq $sourceId -or $_.DBInstanceIdentifier.StartsWith('sol-test3-restore-') } |
        Select-Object DBInstanceIdentifier, DBInstanceStatus, PubliclyAccessible, Endpoint
    return
}
if (-not $SnapshotId -and $Mode -ne 'CleanupDb') { throw 'SnapshotId를 명시하세요.' }
if ($Mode -in @('Restore','CleanupDb') -and -not $RestoreDbId) { throw '본 DB와 다른 sol-test3-restore-* 이름을 명시하세요.' }
if ($RestoreDbId -eq $sourceId) { throw '원본 DB는 변경할 수 없습니다.' }
switch ($Mode) {
    'Snapshot' {
        $null = Invoke-AwsJson @('rds','describe-db-instances','--db-instance-identifier',$sourceId)
        if ($PSCmdlet.ShouldProcess($sourceId, "수동 스냅샷 $SnapshotId 생성")) {
            $null = Invoke-AwsJson @('rds','create-db-snapshot','--db-instance-identifier',$sourceId,'--db-snapshot-identifier',$SnapshotId,'--tags','Key=Project,Value=sol-test3','Key=Purpose,Value=RestoreRehearsal')
            $null = Invoke-AwsJson @('rds','wait','db-snapshot-available','--db-snapshot-identifier',$SnapshotId)
            Write-Host "스냅샷 준비 완료: $SnapshotId"
        }
    }
    'Restore' {
        $snapshot = (Invoke-AwsJson @('rds','describe-db-snapshots','--db-snapshot-identifier',$SnapshotId)).DBSnapshots[0]
        if ($snapshot.DBInstanceIdentifier -ne $sourceId -or $snapshot.Status -ne 'available') { throw '원본 DB의 available 스냅샷이 아닙니다.' }
        $source = (Invoke-AwsJson @('rds','describe-db-instances','--db-instance-identifier',$sourceId)).DBInstances[0]
        # 전체 목록을 정상 조회한 뒤 중복 확인: AccessDenied를 '없는 DB'로 오인하지 않습니다.
        $dbs = (Invoke-AwsJson @('rds','describe-db-instances')).DBInstances
        if ($dbs | Where-Object { $_.DBInstanceIdentifier -eq $RestoreDbId }) { throw '복원 대상 이름이 이미 존재합니다. 새 이름을 사용하세요.' }
        $securityGroups = @($source.VpcSecurityGroups | ForEach-Object { $_.VpcSecurityGroupId })
        if ($PSCmdlet.ShouldProcess($RestoreDbId, "$SnapshotId 스냅샷을 별도 비공개 Single-AZ DB로 복원")) {
            $arguments = @('rds','restore-db-instance-from-db-snapshot',
                '--db-instance-identifier',$RestoreDbId,'--db-snapshot-identifier',$SnapshotId,
                '--db-instance-class',$source.DBInstanceClass,'--db-subnet-group-name',$source.DBSubnetGroup.DBSubnetGroupName,
                '--vpc-security-group-ids') + $securityGroups + @('--no-publicly-accessible','--no-multi-az',
                '--tags','Key=Project,Value=sol-test3','Key=Purpose,Value=RestoreRehearsal')
            $null = Invoke-AwsJson $arguments
            $null = Invoke-AwsJson @('rds','wait','db-instance-available','--db-instance-identifier',$RestoreDbId)
            $restored = (Invoke-AwsJson @('rds','describe-db-instances','--db-instance-identifier',$RestoreDbId)).DBInstances[0]
            Write-Host "복원 완료: $RestoreDbId / $($restored.Endpoint.Address) (기존 앱 DB_HOST는 변경하지 마세요.)"
        }
    }
    'CleanupDb' {
        $db = (Invoke-AwsJson @('rds','describe-db-instances','--db-instance-identifier',$RestoreDbId)).DBInstances[0]
        Require-LabTag (Invoke-AwsJson @('rds','list-tags-for-resource','--resource-name',$db.DBInstanceArn)).TagList
        if ($PSCmdlet.ShouldProcess($RestoreDbId, '실습 DB만 삭제 (추가 최종 스냅샷 없음)')) {
            $null = Invoke-AwsJson @('rds','delete-db-instance','--db-instance-identifier',$RestoreDbId,'--skip-final-snapshot','--delete-automated-backups')
            $null = Invoke-AwsJson @('rds','wait','db-instance-deleted','--db-instance-identifier',$RestoreDbId)
            Write-Host '실습 DB 삭제 완료. 수동 스냅샷은 아직 보관됩니다.'
        }
    }
    'CleanupSnapshot' {
        $snapshot = (Invoke-AwsJson @('rds','describe-db-snapshots','--db-snapshot-identifier',$SnapshotId)).DBSnapshots[0]
        if ($snapshot.DBInstanceIdentifier -ne $sourceId) { throw '프로젝트 원본 DB의 스냅샷이 아닙니다.' }
        Require-LabTag (Invoke-AwsJson @('rds','list-tags-for-resource','--resource-name',$snapshot.DBSnapshotArn)).TagList
        if ($PSCmdlet.ShouldProcess($SnapshotId, '실습 수동 스냅샷 삭제')) {
            $null = Invoke-AwsJson @('rds','delete-db-snapshot','--db-snapshot-identifier',$SnapshotId)
            Write-Host '실습 스냅샷 삭제 요청 완료.'
        }
    }
}
