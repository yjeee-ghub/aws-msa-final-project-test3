# 기본 검증은 조회 전용입니다. 비밀번호 회전/부하는 명시적으로 승인해야 합니다.
[CmdletBinding()]
param(
    [ValidateSet('Basic', 'Rotation', 'Scaling')][string]$Mode = 'Basic',
    [switch]$AllowImpact,
    [string]$Revision = '',
    [string]$ConfigPath = ''
)
$ErrorActionPreference = 'Stop'
$previousUtf8 = $env:PYTHONUTF8
if ($ConfigPath) { $ConfigPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ConfigPath) }
Push-Location $PSScriptRoot
try {
    $env:PYTHONUTF8 = '1'
    $arguments = @('scripts/ops/lab_verify.py', '--mode', $Mode.ToLowerInvariant())
    if ($AllowImpact) { $arguments += '--allow-impact' }
    if ($Revision) { $arguments += @('--revision', $Revision, '--manifest-ref', $Revision) }
    if ($ConfigPath) { $arguments += @('--config', $ConfigPath) }
    & python @arguments
    if ($LASTEXITCODE -ne 0) { throw '검증 실패: 출력과 .lab의 검증 결과를 확인하세요.' }
} finally {
    $env:PYTHONUTF8 = $previousUtf8
    Pop-Location
}
