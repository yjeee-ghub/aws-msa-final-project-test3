# 기본은 미리보기. -Execute -DiscardData는 데이터/로그/이미지와 state 버킷까지 삭제합니다.
[CmdletBinding()]
param(
    [switch]$Execute,
    [switch]$DiscardData,
    [switch]$KeepStateBucket,
    [switch]$ApprovePlans,
    [string]$ConfigPath = ''
)
$ErrorActionPreference = 'Stop'
$previousUtf8 = $env:PYTHONUTF8
if ($ConfigPath) { $ConfigPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ConfigPath) }
Push-Location $PSScriptRoot
try {
    $env:PYTHONUTF8 = '1'
    $arguments = @('scripts/ops/lab_remove.py')
    if ($Execute) { $arguments += '--execute' }
    if ($DiscardData) { $arguments += '--discard-data' }
    if ($KeepStateBucket) { $arguments += '--keep-state-bucket' }
    if ($ApprovePlans) { $arguments += '--approve-plans' }
    if ($ConfigPath) { $arguments += @('--config', $ConfigPath) }
    & python @arguments
    if ($LASTEXITCODE -ne 0) { throw '삭제가 중단됐습니다. state/캡처 파일을 보존하고 오류 해결 후 같은 명령으로 재개하세요.' }
} finally {
    $env:PYTHONUTF8 = $previousUtf8
    Pop-Location
}
