# 일반 큐의 메시지 처리 지연 감시
resource "aws_cloudwatch_metric_alarm" "order_queue_delay" {
  alarm_name        = "${var.project_name}-order-queue-delay"
  alarm_description = "Order queue oldest message age is too high"

  namespace   = "AWS/SQS"
  metric_name = "ApproximateAgeOfOldestMessage"
  statistic   = "Maximum"

  # 1분 간격 평가에서 3회 연속 조건 충족 시 경보
  period              = 60
  evaluation_periods  = 3
  datapoints_to_alarm = 3

  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 300

  dimensions = {
    QueueName = var.order_queue_name
  }

  # 비활성 큐 등에서 지표가 없으면 경보 조건 미충족으로 처리
  treat_missing_data = "notBreaching"

  # 경보가 ALARM 상태로 전환되면 운영 SNS에 발행
  alarm_actions = [aws_sns_topic.operations_alerts.arn]

  depends_on = [
    aws_sns_topic_policy.operations_alerts
  ]
}

# DLQ에 실패 메시지가 남아 있는지 감시
resource "aws_cloudwatch_metric_alarm" "order_dlq_messages" {
  alarm_name        = "${var.project_name}-order-dlq-messages"
  alarm_description = "Order notification DLQ contains messages"

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"
  statistic   = "Maximum"

  period              = 60
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1

  dimensions = {
    QueueName = var.order_dlq_name
  }

  # 지표 누락만으로 경보를 발생시키지 않음: 서비스 장애 탐지를 대체하지 않음
  treat_missing_data = "notBreaching"

  # 경보가 ALARM 상태로 전환되면 운영 SNS에 발행
  alarm_actions = [aws_sns_topic.operations_alerts.arn]

  depends_on = [
    aws_sns_topic_policy.operations_alerts
  ]
}
