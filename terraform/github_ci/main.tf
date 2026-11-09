# GitHub Actions가 발급한 인증 정보를 AWS에서 확인
# AWS 액세스 키를 GitHub에 저장하지 않고 연결하는 방식
resource "aws_iam_openid_connect_provider" "github" {
  count = var.existing_oidc_provider_arn == "" ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"

  # AWS STS를 대상으로 발급된 인증 정보만 허용
  client_id_list = ["sts.amazonaws.com"]

  tags = {
    Name = "${var.project_name}-github-oidc"
  }
}

locals {
  oidc_provider_arn = var.existing_oidc_provider_arn != "" ? var.existing_oidc_provider_arn : aws_iam_openid_connect_provider.github[0].arn
}

# GitHub Actions가 임시 AWS 자격 증명을 받을 IAM 역할
resource "aws_iam_role" "github_actions" {
  name = "${var.project_name}-github-actions-ecr-role"

  # 누가 이 역할을 사용할 수 있는지 정하는 신뢰 정책
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = local.oidc_provider_arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"

        Condition = {
          StringEquals = {
            # AWS STS 대상으로 발급된 인증만 허용
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"

            # 지정한 저장소의 main 브랜치만 허용
            "token.actions.githubusercontent.com:sub" = var.github_oidc_subject
          }
        }
      }
    ]
  })
}

# 이 역할로 실행할 수 있는 ECR 작업 정의
resource "aws_iam_policy" "ecr_push" {
  name = "${var.project_name}-github-actions-ecr-push"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EcrLogin"
        Effect = "Allow"

        # Docker가 ECR에 로그인할 인증 토큰 발급
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "PushProjectImages"
        Effect = "Allow"

        # 이미지 레이어 업로드 및 이미지 정보 조회
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]

        # 프로젝트의 ECR 저장소 5개로 권한 범위 제한
        Resource = var.ecr_repository_arns
      }
    ]
  })
}

# ECR 업로드 정책을 GitHub Actions 역할에 연결
resource "aws_iam_role_policy_attachment" "ecr_push" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.ecr_push.arn
}
