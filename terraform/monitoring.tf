# 운영 알림과 CloudWatch 경보 구성
module "monitoring" {
  source = "./monitoring"

  project_name = var.project_name
  alert_email  = var.alert_email

  account_id = data.aws_caller_identity.current.account_id

  order_queue_name = module.messaging.order_notifications_queue_name
  order_dlq_name   = module.messaging.order_notifications_dlq_name

  db_instance_identifier = module.rds.db_instance_identifier
  # 노드 풀별 ASG를 전달하여 생성·종료 알림을 각각 관리
  node_group_asgs = module.eks.notification_node_groups

  # Alertmanager의 ServiceAccount 기반 AWS 인증에 사용
  oidc_provider_arn = module.eks.oidc_provider_arn
  oidc_issuer_url   = module.eks.oidc_issuer_url
}

# 운영 알림용 SNS 토픽 ARN
output "operations_alerts_topic_arn" {
  value = module.monitoring.alerts_topic_arn
}

# Alertmanager 설치 시 사용할 역할 ARN 확인
output "alertmanager_role_arn" {
  value = module.monitoring.alertmanager_role_arn
}
