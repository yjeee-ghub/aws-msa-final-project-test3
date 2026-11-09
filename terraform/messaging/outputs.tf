# 주문 서비스에서 이벤트를 발행할 대상
output "order_events_topic_arn" {
  value = aws_sns_topic.order_events.arn
}

# 소비자가 메시지를 읽을 큐 URL
output "order_notifications_queue_url" {
  value = aws_sqs_queue.order_notifications.url
}

# 소비자 IAM 정책에 사용할 큐 ARN
output "order_notifications_queue_arn" {
  value = aws_sqs_queue.order_notifications.arn
}

# 이후 모니터링에서 사용할 큐 이름
output "order_notifications_queue_name" {
  value = aws_sqs_queue.order_notifications.name
}

# 처리 실패 메시지를 감시할 DLQ 이름
output "order_notifications_dlq_name" {
  value = aws_sqs_queue.order_notifications_dlq.name
}

# 주문 서비스 ServiceAccount에 연결할 IAM 역할 ARN
output "ordering_sns_role_arn" {
  description = "주문 이벤트 SNS 발행용 IAM 역할 ARN"
  value       = aws_iam_role.ordering_sns.arn
}
