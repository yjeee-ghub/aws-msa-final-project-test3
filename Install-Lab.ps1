# GUI 없이 설치/재개. 기본 실행은 단계 미리보기이며 AWS를 변경하지 않습니다.
[CmdletBinding()]
param(
    [switch]$Execute,
    [switch]$ApprovePlans,
    [switch]$InfrastructureOnly,
    [switch]$PromoteMain,
    [string]$ConfigPath = ''
)
$ErrorActionPreference = 'Stop'
$previousUtf8 = $env:PYTHONUTF8
$previousProgress = $ProgressPreference
if ($ConfigPath) { $ConfigPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ConfigPath) }
Push-Location $PSScriptRoot
try {
    $env:PYTHONUTF8 = '1'
    $ProgressPreference = 'SilentlyContinue'
    $arguments = @('scripts/ops/lab_install.py')
    if ($Execute) { $arguments += '--execute' }
    if ($ApprovePlans) { $arguments += '--approve-plans' }
    if ($InfrastructureOnly) { $arguments += '--infrastructure-only' }
    if ($PromoteMain) { $arguments += '--promote-main' }
    if ($ConfigPath) { $arguments += @('--config', $ConfigPath) }
    & python @arguments
    if ($LASTEXITCODE -ne 0) { throw '설치가 중단됐습니다. 오류를 해결한 뒤 같은 명령으로 재개하세요.' }
} finally {
    $env:PYTHONUTF8 = $previousUtf8
    $ProgressPreference = $previousProgress
    Pop-Location
}
