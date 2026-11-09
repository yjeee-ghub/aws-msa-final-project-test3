# 이 계정의 프로젝트 경보가 운영 SNS에 알림을 보낼 수 있게 허용
resource "aws_sns_topic_policy" "operations_alerts" {
  arn = aws_sns_topic.operations_alerts.arn

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "AllowProjectCloudWatchAlarms"
        Effect = "Allow"

        Principal = {
          Service = "cloudwatch.amazonaws.com"
        }

        Action   = "sns:Publish"
        Resource = aws_sns_topic.operations_alerts.arn

        Condition = {
          StringEquals = {
            "aws:SourceAccount" = var.account_id
          }

          ArnLike = {
            "aws:SourceArn" = "arn:aws:cloudwatch:ap-northeast-2:${var.account_id}:alarm:${var.project_name}-*"
          }
        }
      }
    ]
  })
}
