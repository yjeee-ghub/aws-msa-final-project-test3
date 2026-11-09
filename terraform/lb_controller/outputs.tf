# 컨트롤러 ServiceAccount에서 사용할 IAM 역할 ARN
output "role_arn" {
  description = "AWS Load Balancer Controller용 IAM 역할 ARN"
  value       = aws_iam_role.controller.arn
}
