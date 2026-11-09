# 초대는 최초 설치 확인 후 엽이가 실행합니다. 기본은 대상 표시만 합니다.
[CmdletBinding()]
param([switch]$Apply, [switch]$InitialInstallVerified)
$ErrorActionPreference = 'Stop'
$team = Get-Content -Raw (Join-Path $PSScriptRoot 'team.json') | ConvertFrom-Json
if (-not $Apply) { $team | ConvertTo-Json; return }
if (-not $InitialInstallVerified) { throw '최초 설치를 확인한 다음 -Apply -InitialInstallVerified로 실행하세요.' }
foreach ($login in $team.collaborators) {
    & gh api --method PUT "repos/$($team.repository)/collaborators/$login" -f "permission=$($team.permission)" --silent
    if ($LASTEXITCODE -ne 0) { throw "팀원 초대 실패: $login. 수락/권한 상태를 확인하세요." }
    Write-Host "초대/권한 요청 완료: $login (아직 수락 여부는 별도 확인)"
}
