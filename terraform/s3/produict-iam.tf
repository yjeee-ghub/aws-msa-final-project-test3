# 이 파일에서 재사용할 이름과 인증 조건 값
locals {
  # IAM 신뢰 조건에서는 https://를 제외한 발급자 주소 사용
  oidc_issuer_hostpath = trimprefix(var.oidc_issuer_url, "https://")
}

# 상품 서비스 Pod에서 사용할 IAM 역할
resource "aws_iam_role" "product_s3" {
  name = "${var.project_name}-product-s3-role"

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
            "${local.oidc_issuer_hostpath}:aud" = "sts.amazonaws.com"

            # 지정한 네임스페이스와 ServiceAccount의 토큰만 허용
            "${local.oidc_issuer_hostpath}:sub" = "system:serviceaccount:${var.product_namespace}:${var.product_service_account_name}"
          }
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-product-s3-role"
  }
}

# 상품 이미지 경로에 필요한 권한
resource "aws_iam_policy" "product_s3" {
  name = "${var.project_name}-product-s3-policy"

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "ProductImageAccess"
        Effect = "Allow"

        Action = [
          "s3:PutObject",
          "s3:GetObject"
        ]

        Resource = "${aws_s3_bucket.product_images.arn}/products/*"
      }
    ]
  })
}

# 상품 서비스 역할에 S3 권한 연결
resource "aws_iam_role_policy_attachment" "product_s3" {
  role       = aws_iam_role.product_s3.name
  policy_arn = aws_iam_policy.product_s3.arn
}
