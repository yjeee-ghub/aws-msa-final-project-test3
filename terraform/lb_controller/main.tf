# 이 모듈에서 사용할 Terraform 및 Provider 요구사항
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# 이 파일에서 재사용할 이름과 인증 조건 값
locals {
  oidc_provider_host = trimprefix(var.oidc_issuer_url, "https://")
}

# 컨트롤러의 ServiceAccount만 사용할 수 있는 IAM 역할
resource "aws_iam_role" "controller" {
  name = "${var.project_name}-load-balancer-controller-role"

  # 이 역할을 사용할 수 있는 주체를 정의하는 신뢰 정책
  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          # EKS OIDC Provider가 발급한 ServiceAccount 토큰을 신뢰
          Federated = var.oidc_provider_arn
        }

        Action = "sts:AssumeRoleWithWebIdentity"

        Condition = {
          StringEquals = {
            # 토큰의 사용 대상이 AWS STS인지 확인
            "${local.oidc_provider_host}:aud" = "sts.amazonaws.com"
            # 지정한 네임스페이스와 ServiceAccount의 토큰만 허용
            "${local.oidc_provider_host}:sub" = "system:serviceaccount:kube-system:aws-load-balancer-controller"
          }
        }
      }
    ]
  })
}

# 다운로드한 공식 정책 파일 사용
resource "aws_iam_policy" "controller" {
  name = "${var.project_name}-load-balancer-controller-policy"

  policy = file("${path.module}/iam_policy.json")
}

# 역할에 정책 연결
resource "aws_iam_role_policy_attachment" "controller" {
  role       = aws_iam_role.controller.name
  policy_arn = aws_iam_policy.controller.arn
}
