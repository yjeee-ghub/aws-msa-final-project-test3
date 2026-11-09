# 다음 단계에서 GitHub Actions용 IAM 역할에 연결
output "oidc_provider_arn" {
  value       = local.oidc_provider_arn
  description = "GitHub Actions 인증용 OIDC Provider ARN"
}

# AWS 생성 후 GitHub Actions 변수에 등록할 역할 ARN
output "github_actions_role_arn" {
  value       = aws_iam_role.github_actions.arn
  description = "GitHub Actions의 ECR 업로드용 IAM 역할 ARN"
}
