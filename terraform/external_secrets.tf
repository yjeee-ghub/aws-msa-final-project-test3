resource "aws_iam_role" "secret_reader" {
  count = var.manage_db_password ? 1 : 0
  name  = "${var.project_name}-database-secret-reader"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Federated = module.eks.oidc_provider_arn }, Action = "sts:AssumeRoleWithWebIdentity",
    Condition = { StringEquals = {
      "${trimprefix(module.eks.oidc_issuer_url, "https://")}:aud" = "sts.amazonaws.com",
      "${trimprefix(module.eks.oidc_issuer_url, "https://")}:sub" = "system:serviceaccount:soldesk:database-secret-reader"
    } }
  }] })
}
resource "aws_iam_role_policy" "secret_reader" {
  count  = var.manage_db_password ? 1 : 0
  role   = aws_iam_role.secret_reader[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"], Resource = module.rds.master_secret_arn }] })
}
output "database_secret_arn" { value = module.rds.master_secret_arn }
output "database_secret_reader_role_arn" { value = try(aws_iam_role.secret_reader[0].arn, null) }
output "manage_db_password" { value = var.manage_db_password }
