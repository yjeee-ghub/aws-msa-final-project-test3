# 이 모듈에서 사용할 AWS Provider
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# EKS 관리형 애드온으로 EBS CSI Driver 설치
resource "aws_eks_addon" "main" {
  cluster_name = var.cluster_name

  addon_name    = "aws-ebs-csi-driver"
  addon_version = var.addon_version

  # 컨트롤러 ServiceAccount에 전용 IAM 역할 연결
  service_account_role_arn = aws_iam_role.main.arn

  # 기존 설정과 충돌하면 오류로 확인하고 처리
  resolve_conflicts_on_create = "NONE"
  resolve_conflicts_on_update = "NONE"

  # IAM 정책 연결이 끝난 뒤 애드온 설치
  depends_on = [
    aws_iam_role_policy_attachment.main,
  ]
}
