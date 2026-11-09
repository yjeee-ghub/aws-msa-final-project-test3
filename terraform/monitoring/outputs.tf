# 경보와 노드 이벤트를 전달하는 운영 SNS 토픽 ARN
output "alerts_topic_arn" {
  value = aws_sns_topic.operations_alerts.arn
}

# Alertmanager ServiceAccount에 연결할 IAM 역할 ARN
output "alertmanager_role_arn" {
  description = "Alertmanager의 운영 SNS 발행용 IAM 역할 ARN"
  value       = aws_iam_role.alertmanager.arn
}
