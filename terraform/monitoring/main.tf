# 이 모듈에서 사용할 Terraform 및 Provider 요구사항
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# 장애·확장 등 운영 알림용 SNS 토픽
resource "aws_sns_topic" "operations_alerts" {
  name = "${var.project_name}-operations-alerts"

  tags = {
    Name = "${var.project_name}-operations-alerts"
  }
}

# 운영 알림을 이메일로 전달
resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.operations_alerts.arn

  protocol = "email"
  endpoint = var.alert_email
}

moved {
  from = aws_sns_topic_subscription.email
  to   = aws_sns_topic_subscription.email[0]
}
