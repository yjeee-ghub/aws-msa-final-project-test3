# 주문 이벤트 전달 기반과 주문 서비스 발행 권한 구성
module "messaging" {
  source = "./messaging"

  project_name = var.project_name

  # 주문 서비스의 ServiceAccount 기반 AWS 인증에 사용
  oidc_provider_arn = module.eks.oidc_provider_arn
  oidc_issuer_url   = module.eks.oidc_issuer_url
}

# 주문 서비스가 이벤트를 발행할 SNS 토픽 ARN
output "order_events_topic_arn" {
  value = module.messaging.order_events_topic_arn
}

# 주문 알림 소비자가 메시지를 읽을 SQS 큐 URL
output "order_notifications_queue_url" {
  value = module.messaging.order_notifications_queue_url
}

# 주문 서비스 ServiceAccount에 연결할 IAM 역할 ARN
output "ordering_sns_role_arn" {
  value = module.messaging.ordering_sns_role_arn
}
