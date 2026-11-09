# Windows CurrentUser DPAPI recovery; default is a non-mutating preview.
[CmdletBinding()]
param([switch]$Execute,[switch]$ApprovePlans,[string]$ConfigPath='')
$ErrorActionPreference='Stop'
$previousUtf8=$env:PYTHONUTF8
if ($ConfigPath) { $ConfigPath=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ConfigPath) }
Push-Location $PSScriptRoot
try {
 $env:PYTHONUTF8='1'
 $arguments=@('scripts/ops/lab_recovery.py','preserve')
 if ($Execute) { $arguments+='--execute' }
 if ($ApprovePlans) { $arguments+='--approve-plans' }
 if ($ConfigPath) { $arguments+=@('--config',$ConfigPath) }
 & python @arguments
 if ($LASTEXITCODE -ne 0) { throw 'Recovery stopped. Keep .lab/recovery and inspect its checkpoint before retrying.' }
} finally { $env:PYTHONUTF8=$previousUtf8; Pop-Location }
