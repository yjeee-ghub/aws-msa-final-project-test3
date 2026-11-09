locals {
  # IAM 조건 키에서는 https://를 제외한 발급자 주소 사용
  oidc_provider_host = trimprefix(var.oidc_issuer_url, "https://")
}

# Alertmanager Pod가 사용할 전용 IAM 역할
resource "aws_iam_role" "alertmanager" {
  name = "${var.project_name}-alertmanager-sns-role"

  # 지정한 Alertmanager ServiceAccount만 역할 사용 허용
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

            # monitoring 네임스페이스의 alertmanager만 허용
            "${local.oidc_provider_host}:sub" = "system:serviceaccount:monitoring:alertmanager"
          }
        }
      }
    ]
  })
}

# 운영 경보 발행에 필요한 최소 권한
resource "aws_iam_policy" "alertmanager" {
  name = "${var.project_name}-alertmanager-sns-policy"

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "PublishOperationsAlerts"
        Effect = "Allow"

        # 운영 SNS로 메시지 발행만 허용
        Action = "sns:Publish"

        # 주문 이벤트 토픽과 구분해 운영 토픽으로 제한
        Resource = aws_sns_topic.operations_alerts.arn
      }
    ]
  })
}

# Alertmanager 역할에 운영 SNS 발행 정책 연결
resource "aws_iam_role_policy_attachment" "alertmanager" {
  role       = aws_iam_role.alertmanager.name
  policy_arn = aws_iam_policy.alertmanager.arn
}
