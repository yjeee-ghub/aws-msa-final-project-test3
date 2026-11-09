# 기본은 로컬 빌드만 수행. AWS 생성 후 -Push를 지정할 때 ECR 업로드
[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$')][string]$ImageTag = 'lab-v1',
    [switch]$Push,
    [ValidateSet('member','product','ordering','apigateway','frontend')][string[]]$Services = @('member','product','ordering','apigateway','frontend')
)
$ErrorActionPreference = 'Stop'
$appRoot = Split-Path $PSScriptRoot -Parent
$registry = '683668078297.dkr.ecr.ap-northeast-2.amazonaws.com'
$imageNames = [ordered]@{
    member = 'member-service'
    product = 'product-service'
    ordering = 'ordering-service'
    apigateway = 'apigateway'
    frontend = 'frontend-service'
}
# Git for Windows의 bash, JDK 17, Python 3, Node.js가 필요합니다.
# Windows의 WSL 실행기보다 Git Bash를 우선하여 WSL 설치 여부에 의존하지 않습니다.
$gitBash = if ($env:OS -eq 'Windows_NT') {
    Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'Git/bin/bash.exe'
} else { $null }
$bashCommand = if ($gitBash -and (Test-Path -LiteralPath $gitBash)) {
    $gitBash
} else {
    (Get-Command bash -ErrorAction Stop).Source
}
# 모든 선택 서비스의 테스트를 AWS 인증과 이미지 게시보다 먼저 완료합니다.
$repoRoot = (Resolve-Path (Join-Path $appRoot '../..')).Path
Push-Location $repoRoot
try {
    foreach ($service in $Services) {
        & $bashCommand scripts/ci/test-service.sh $service
        if ($LASTEXITCODE -ne 0) { throw "$service 테스트 실패: 게시 중단" }
    }
} finally { Pop-Location }
if ($Push) {
    $account = & aws sts get-caller-identity --query Account --output text
    if ($LASTEXITCODE -ne 0 -or $account.Trim() -ne '683668078297') { throw 'AWS 계정이 프로젝트와 다릅니다.' }
    $token = & aws ecr get-login-password --region ap-northeast-2
    if ($LASTEXITCODE -ne 0) { throw 'ECR 로그인 토큰을 가져오지 못했습니다.' }
    $token | & docker login --username AWS --password-stdin $registry
    $token = $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker ECR 로그인 실패' }
}
# 빌드가 모두 성공한 뒤에만 게시 루프를 시작합니다.
foreach ($service in $Services) {
    $localImage = "$($imageNames[$service]):$ImageTag"
    & docker build --platform linux/amd64 -t $localImage (Join-Path $appRoot $service)
    if ($LASTEXITCODE -ne 0) { throw "$localImage 빌드 실패" }
}
if ($Push) {
    foreach ($service in $Services) {
        $localImage = "$($imageNames[$service]):$ImageTag"
        $remoteImage = "$registry/$localImage"
        & docker tag $localImage $remoteImage
        if ($LASTEXITCODE -ne 0) { throw '이미지 태그 실패' }
        & docker push $remoteImage
        if ($LASTEXITCODE -ne 0) { throw "$remoteImage 업로드 실패" }
    }
    # 모든 게시가 성공한 뒤 선택한 서비스의 배포 태그만 변경합니다.
    Push-Location $repoRoot
    try {
        & python scripts/ci/update_image_tags.py --tag $ImageTag @Services
        if ($LASTEXITCODE -ne 0) { throw 'Kustomize 이미지 태그 변경 실패' }
    } finally { Pop-Location }
    Write-Host '선택한 이미지 게시와 태그 변경 완료. Git 반영은 별도 진행하세요.'
}
