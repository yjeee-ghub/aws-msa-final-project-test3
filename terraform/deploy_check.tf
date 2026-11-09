# 게시 역할과 분리된 배포 조회 전용 역할. 쓰기/Secret 조회 권한은 부여하지 않습니다.
resource "aws_iam_role" "deploy_check" {
  name = "${var.project_name}-github-deploy-check-role"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Federated = module.github_ci.oidc_provider_arn }, Action = "sts:AssumeRoleWithWebIdentity",
    Condition = { StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com", "token.actions.githubusercontent.com:sub" = local.environment.githubOidcSubject } }
  }] })
}
# GitHub submits builds; only the VPC CodeBuild role has Kubernetes read access.
output "github_deploy_check_role_arn" { value = aws_iam_role.deploy_check.arn }
