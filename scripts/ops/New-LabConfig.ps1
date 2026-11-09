# 현재 PC의 비밀이 아닌 실행값만 준비합니다. AWS 리소스 변경과 apply는 하지 않습니다.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$target = Join-Path $root 'terraform/terraform.tfvars'
if (Test-Path -LiteralPath $target) { throw 'terraform.tfvars가 이미 있습니다. 기존 값을 검토하고 보존하세요.' }
$arn = Read-Host 'EKS 관리자 IAM user/role ARN (sts assumed-role ARN 아님)'
if ($arn -notmatch '^arn:aws:iam::683668078297:(user|role)/[A-Za-z0-9+=,.@_/-]+$') { throw '계정 683668078297의 IAM ARN이 필요합니다.' }
$address = (Invoke-RestMethod 'https://checkip.amazonaws.com').Trim()
$ip = [Net.IPAddress]::Parse($address)
if ($ip.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { throw '이 가이드에는 IPv4 공인 주소가 필요합니다.' }
$email = Read-Host '운영 장애 알림을 받을 이메일'
$sender = Read-Host '서울 SES에서 인증한 발신 이메일'
$recipient = Read-Host 'SES 샌드박스에서 인증한 실습 수신 이메일'
foreach ($value in @($email, $sender, $recipient)) {
    if ($value -notmatch '^[A-Za-z0-9.!#$%&*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$') { throw '이메일 형식을 확인하세요.' }
}
# JSON 문자열 인코딩은 HCL 문자열로도 안전하며 따옴표/개행 주입을 방지합니다.
function Quote-Hcl([string]$Value) { ConvertTo-Json -InputObject $Value -Compress }
$text = @"
eks_admin_principal_arn = $(Quote-Hcl $arn)
eks_public_access_cidrs = ["$address/32"]
eks_node_instance_types = ["t3.medium"]
keep_legacy_node_group = false
alert_email = $(Quote-Hcl $email)
manage_db_password = true
customer_email_sender = $(Quote-Hcl $sender)
customer_email_test_recipients = [$(Quote-Hcl $recipient)]
manage_ses_identities = false
customer_email_enabled = false
enable_website_dns = false
enable_management_dns = false
"@
[IO.File]::WriteAllText($target, $text, (New-Object Text.UTF8Encoding($false)))
Write-Host "준비 완료: 현재 PC 공인 IP $address/32. 이메일 구독·SES 인증은 별도로 확인하세요."
Write-Host '아직 AWS 변경 없음. 다음은 docs/14-second-build.md의 state/infra plan 검토 단계입니다.'
