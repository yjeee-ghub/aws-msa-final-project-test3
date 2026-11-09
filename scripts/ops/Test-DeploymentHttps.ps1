# Argo CD 배포 완료를 확인한 뒤 실행하는 읽기 전용 HTTPS 점검입니다.
[CmdletBinding()]
param(
    [uri]$BaseUrl = 'https://server.aws-yjeee.com',
    [ValidateRange(1,100)][int]$Attempts = 12,
    [ValidateRange(1,60)][int]$TimeoutSeconds = 10,
    [ValidateRange(0,60)][int]$RetryDelaySeconds = 10
)
$ErrorActionPreference = 'Stop'
if ($BaseUrl.Scheme -ne 'https' -or $BaseUrl.UserInfo -or $BaseUrl.Query -or $BaseUrl.Fragment) { throw '인증정보 없는 HTTPS 기본 주소가 필요합니다.' }
# 실제 화면과 DB를 사용하는 공개 상품 API를 모두 검사합니다.
$checks = @(@{ Path='/'; Kind='html' }, @{ Path='/product-service/product/list'; Kind='json' })
foreach ($check in $checks) {
    $url = [uri]::new($BaseUrl, $check.Path)
    $passed = $false
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            # 리다이렉트를 성공으로 숨기거나 인증서 검증을 생략하지 않습니다.
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $TimeoutSeconds -MaximumRedirection 0
            if ($response.StatusCode -ne 200) { throw "HTTP $($response.StatusCode)" }
            if ($check.Kind -eq 'html' -and $response.Content -notmatch '(?i)<html') { throw 'HTML 화면이 아닙니다.' }
            if ($check.Kind -eq 'json') {
                if ($response.Headers['Content-Type'] -notmatch 'application/json') { throw 'JSON API 응답이 아닙니다.' }
                $null = $response.Content | ConvertFrom-Json
            }
            Write-Host "성공: $url HTTP 200 ($attempt/$Attempts)"
            $passed = $true
            break
        } catch {
            Write-Warning "실패: $url ($attempt/$Attempts) $($_.Exception.Message)"
            if ($attempt -lt $Attempts) { Start-Sleep -Seconds $RetryDelaySeconds }
        }
    }
    if (-not $passed) { throw "HTTPS 점검 실패: $url" }
}
Write-Host 'HTTPS 응답 확인 완료. 이 결과만으로 주문·메일·관리자 기능 전체를 보장하지 않습니다.'
