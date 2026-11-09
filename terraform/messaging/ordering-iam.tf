locals {
  # IAM 조건 키에서는 https://를 제외한 발급자 주소 사용
  oidc_provider_host = trimprefix(var.oidc_issuer_url, "https://")
}

# 주문 서비스 Pod가 사용할 전용 IAM 역할
resource "aws_iam_role" "ordering_sns" {
  name = "${var.project_name}-ordering-sns-role"

  # 지정한 주문 서비스 ServiceAccount만 역할 사용 허용
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

            # soldesk의 주문 서비스 전용 ServiceAccount만 허용
            "${local.oidc_provider_host}:sub" = "system:serviceaccount:soldesk:ordering-service-account"
          }
        }
      }
    ]
  })
}

# 주문 이벤트 발행에 필요한 최소 권한
resource "aws_iam_policy" "ordering_sns" {
  name = "${var.project_name}-ordering-sns-policy"

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "PublishOrderEvents"
        Effect = "Allow"

        # 메시지 발행만 허용
        Action = "sns:Publish"

        # 이번 프로젝트의 주문 이벤트 토픽으로 범위 제한
        Resource = aws_sns_topic.order_events.arn
      }
    ]
  })
}

# 주문 서비스 역할에 SNS 발행 정책 연결
resource "aws_iam_role_policy_attachment" "ordering_sns" {
  role       = aws_iam_role.ordering_sns.name
  policy_arn = aws_iam_policy.ordering_sns.arn
}
