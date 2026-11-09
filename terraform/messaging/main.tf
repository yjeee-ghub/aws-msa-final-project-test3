# 이 모듈에서 사용할 Terraform 및 Provider 요구사항
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# 주문 완료 이벤트를 발행할 SNS 토픽
resource "aws_sns_topic" "order_events" {
  name = "${var.project_name}-order-events"

  tags = {
    Name = "${var.project_name}-order-events"
  }
}

# 반복 처리에 실패한 메시지를 보관할 큐
resource "aws_sqs_queue" "order_notifications_dlq" {
  name = "${var.project_name}-order-notifications-dlq"

  # 실패 메시지를 14일 보관
  message_retention_seconds = 1209600

  # SQS 관리형 저장 암호화
  sqs_managed_sse_enabled = true

  tags = {
    Name = "${var.project_name}-order-notifications-dlq"
  }
}

# 주문 알림 이벤트를 처리할 일반 큐
resource "aws_sqs_queue" "order_notifications" {
  name = "${var.project_name}-order-notifications"

  # 소비자가 받은 메시지를 다른 소비자에게 잠시 숨김
  visibility_timeout_seconds = 120

  # 일반 메시지를 4일 보관
  message_retention_seconds = 345600

  # 메시지가 없으면 최대 20초 기다리는 Long Polling
  receive_wait_time_seconds = 20

  sqs_managed_sse_enabled = true

  # 반복 수신 후에도 처리되지 않은 메시지는 DLQ로 이동
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.order_notifications_dlq.arn
    maxReceiveCount     = 5
  })

  tags = {
    Name = "${var.project_name}-order-notifications"
  }
}

# 이 알림 큐만 해당 DLQ를 사용하도록 제한
resource "aws_sqs_queue_redrive_allow_policy" "order_notifications" {
  queue_url = aws_sqs_queue.order_notifications_dlq.url

  # 지정한 원본 큐만 이 DLQ를 사용하도록 제한
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"

    sourceQueueArns = [
      aws_sqs_queue.order_notifications.arn
    ]
  })
}

# 지정한 SNS 토픽에서 이 큐로 메시지 전송 허용
resource "aws_sqs_queue_policy" "order_notifications" {
  queue_url = aws_sqs_queue.order_notifications.url

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "AllowOrderEventsFromSNS"
        Effect = "Allow"

        Principal = {
          Service = "sns.amazonaws.com"
        }

        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.order_notifications.arn

        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_sns_topic.order_events.arn
          }
        }
      }
    ]
  })
}

# SNS 주문 이벤트를 SQS 알림 큐로 전달
resource "aws_sns_topic_subscription" "order_notifications" {
  topic_arn = aws_sns_topic.order_events.arn

  protocol = "sqs"
  endpoint = aws_sqs_queue.order_notifications.arn

  # SNS의 추가 포장 없이 발행한 메시지 본문 전달
  raw_message_delivery = true

  # 큐의 전송 허용 정책이 준비된 뒤 구독 연결
  depends_on = [
    aws_sqs_queue_policy.order_notifications
  ]
}
