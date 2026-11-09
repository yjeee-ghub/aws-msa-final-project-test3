# EKS 생성 후 실행: 비밀번호를 파일/명령 인수에 저장하지 않고 Secret 생성
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$DbHost
)
$ErrorActionPreference = 'Stop'
$context = & kubectl config current-context
if ($LASTEXITCODE -ne 0 -or $context -notmatch ':cluster/sol-test3-eks$') {
    throw '먼저 sol-test3-eks의 kubeconfig를 연결하세요.'
}
$existingText = & kubectl get secret my-app-secrets -n soldesk --ignore-not-found -o json
if ($LASTEXITCODE -ne 0) { throw 'soldesk 네임스페이스와 클러스터 연결을 확인하세요.' }
$existing = $null
if ($existingText) { $existing = ($existingText -join "`n") | ConvertFrom-Json }
function New-JwtKey {
    $bytes = New-Object byte[] 64
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($bytes)
}
function Get-JwtKey([string]$Name) {
    # 재실행 시 기존 서명 키를 유지하여 로그인 토큰이 갑자기 무효화되지 않게 함
    if ($existing -and $existing.data.$Name) {
        return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($existing.data.$Name))
    }
    return New-JwtKey
}
$password = Read-Host 'Terraform에 사용한 RDS 비밀번호' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
try {
    $secret = @{
        apiVersion = 'v1'
        kind = 'Secret'
        metadata = @{ name = 'my-app-secrets'; namespace = 'soldesk' }
        type = 'Opaque'
        stringData = @{
            DB_HOST = $DbHost
            DB_PW = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
            JWT_SECRET = Get-JwtKey 'JWT_SECRET'
            JWT_REFRESH_SECRET = Get-JwtKey 'JWT_REFRESH_SECRET'
        }
    }
    $secret | ConvertTo-Json -Depth 8 | & kubectl apply -f -
    if ($LASTEXITCODE -ne 0) { throw 'Secret 생성에 실패했습니다.' }
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $secret = $null
    $password = $null
}
Write-Host 'Secret 준비 완료. 기존 파드는 Secret 변경 후 재시작해야 새 값을 사용합니다.'

