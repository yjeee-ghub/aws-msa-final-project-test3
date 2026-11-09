# AWS 생성 및 kubeconfig 연결 후 실행: Terraform에 전달할 값만 준비
# 파일에 비밀번호를 저장하거나 Terraform apply를 실행하지 않음
[CmdletBinding()]
param([switch]$PrivateRepository)
$ErrorActionPreference = 'Stop'

# JWT 키를 조회할 클러스터가 프로젝트 EKS인지 확인
$context = & kubectl config current-context
if ($LASTEXITCODE -ne 0 -or $context -ne 'arn:aws:eks:ap-northeast-2:683668078297:cluster/sol-test3-eks') {
    throw '먼저 sol-test3-eks의 기본 kubeconfig 컨텍스트를 연결하세요.'
}

# 재실행 시 기존 JWT 키를 재사용하여 로그인 토큰 유지
$existing = $null
$namespaceText = & kubectl get namespace soldesk --ignore-not-found -o name
if ($LASTEXITCODE -ne 0) { throw 'EKS 접속 또는 조회 권한을 확인하세요.' }
if ($namespaceText) {
    $secretText = & kubectl get secret my-app-secrets -n soldesk --ignore-not-found -o json
    if ($LASTEXITCODE -ne 0) { throw '앱 Secret 조회에 실패했습니다.' }
    if ($secretText) { $existing = ($secretText -join "`n") | ConvertFrom-Json }
}

function Read-SecretValue([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if ([string]::IsNullOrWhiteSpace($value)) { throw '빈 값은 사용할 수 없습니다.' }
        return $value
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Set-JwtValue([string]$Key, [string]$EnvironmentName) {
    if ($existing -and $existing.data.$Key) {
        $value = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($existing.data.$Key))
    } else {
        # 같은 PowerShell 창에서 plan/apply를 다시 해도 키 유지
        $value = [Environment]::GetEnvironmentVariable($EnvironmentName, 'Process')
        if (-not $value) {
            $bytes = New-Object byte[] 64
            $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
            try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
            $value = [Convert]::ToBase64String($bytes)
        }
    }
    [Environment]::SetEnvironmentVariable($EnvironmentName, $value, 'Process')
}

# 환경 변수는 현재 PowerShell 창에서 실행하는 Terraform에만 전달
$infraRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../terraform'))
$managed = & terraform "-chdir=$infraRoot" output -raw manage_db_password
if ($LASTEXITCODE -ne 0) { throw 'infra apply 및 manage_db_password 출력을 확인하세요.' }
if ($managed -ne 'true' -and -not $env:TF_VAR_db_password) {
    $env:TF_VAR_db_password = Read-SecretValue 'RDS 생성 시 사용한 DB 비밀번호'
}
$env:TF_VAR_github_repository_public = (-not $PrivateRepository).ToString().ToLowerInvariant()
if ($PrivateRepository -and -not $env:TF_VAR_github_token) {
    $env:TF_VAR_github_token = Read-SecretValue 'GitHub 저장소 읽기 토큰'
}
Set-JwtValue 'JWT_SECRET' 'TF_VAR_jwt_secret'
Set-JwtValue 'JWT_REFRESH_SECRET' 'TF_VAR_jwt_refresh_secret'
Set-JwtValue 'INTERNAL_SERVICE_TOKEN' 'TF_VAR_internal_service_token'

Write-Host '입력값 준비 완료. 같은 PowerShell 창에서 terraform plan/apply를 실행하세요.'
