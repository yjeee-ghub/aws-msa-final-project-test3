# EBS CSI Driver가 사용하는 IAM 역할 ARN
output "role_arn" {
  description = "EBS CSI Driver용 IAM 역할 ARN"
  value       = aws_iam_role.main.arn
}

# 설치 대상으로 설정한 애드온 버전
output "addon_version" {
  description = "EBS CSI Driver 애드온 버전"
  value       = aws_eks_addon.main.addon_version
}
