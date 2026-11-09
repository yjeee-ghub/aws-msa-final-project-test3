locals {
  # IAM 조건 키에서는 https://를 제외한 주소 사용
  oidc_provider_host = trimprefix(var.oidc_issuer_url, "https://")
}

# EBS CSI 컨트롤러 Pod가 사용할 전용 IAM 역할
resource "aws_iam_role" "main" {
  name = "${var.project_name}-ebs-csi-role"

  # EBS CSI 컨트롤러의 ServiceAccount만 역할 사용 허용
  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Federated = var.oidc_provider_arn
        }

        Action = "sts:AssumeRoleWithWebIdentity"

        Condition = {
          StringEquals = {
            # AWS STS를 대상으로 발급된 토큰인지 확인
            "${local.oidc_provider_host}:aud" = "sts.amazonaws.com"

            # 지정한 네임스페이스와 ServiceAccount만 허용
            "${local.oidc_provider_host}:sub" = "system:serviceaccount:kube-system:ebs-csi-controller-sa"
          }
        }
      }
    ]
  })
}

# EBS 생성·연결·삭제 등에 필요한 AWS 관리 정책 연결
resource "aws_iam_role_policy_attachment" "main" {
  role = aws_iam_role.main.name

  policy_arn = "arn:aws:iam::aws:policy/AmazonEBSCSIDriverPolicyV2"
}
