# 실제 GitHub 주소를 입력하여 연결 파일 생성: 클러스터에 적용하지 않음
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$')][string]$RepoUrl,
    [ValidatePattern('^[A-Za-z0-9_./-]+$')][string]$Branch = 'main',
    [ValidatePattern('^[A-Za-z0-9_./-]+$')][string]$GitPath = 'app/msa'
)
$ErrorActionPreference = 'Stop'
$appRoot = Split-Path $PSScriptRoot -Parent
$templatePath = Join-Path $appRoot 'k8s/k8s-argocd/application.yml.template'
$outputPath = Join-Path $appRoot 'k8s/k8s-argocd/application.generated.yml'
# 따옴표로 값 경계를 고정하며 YAML에 실제 문자열 입력
$text = [IO.File]::ReadAllText($templatePath)
$text = $text.Replace('__REPO_URL__', "'$RepoUrl'").Replace('__BRANCH__', "'$Branch'").Replace('__GIT_PATH__', "'$GitPath'")
[IO.File]::WriteAllText($outputPath, $text, (New-Object Text.UTF8Encoding($false)))
Write-Host "생성 완료: $outputPath"

