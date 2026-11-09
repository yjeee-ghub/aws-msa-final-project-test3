# 나중에 CA ServiceAccount에 연결할 IAM 역할 ARN
output "role_arn" {
  description = "Cluster Autoscaler용 IAM 역할 ARN"
  value       = aws_iam_role.main.arn
}
