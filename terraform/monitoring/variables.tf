# 리소스 이름에 사용할 프로젝트 이름
variable "project_name" {
  type = string
}

# 운영 SNS 알림을 수신할 이메일 주소
variable "alert_email" {
  type = string
}

# CloudWatch 알림 발행을 허용할 AWS 계정
variable "account_id" {
  type = string
}

# 감시할 일반 큐 이름
variable "order_queue_name" {
  type = string
}

# 감시할 DLQ 이름
variable "order_dlq_name" {
  type = string
}

# 감시할 RDS 인스턴스 식별자
variable "db_instance_identifier" {
  type = string
}

# 노드 풀 이름을 키로 사용하여 그룹별 알림의 상태 주소를 유지
variable "node_group_asgs" {
  type = map(string)
}

# Alertmanager의 ServiceAccount 토큰을 신뢰할 OIDC Provider
variable "oidc_provider_arn" {
  type = string
}

# IAM 신뢰 조건에 사용할 토큰 발급자 URL
variable "oidc_issuer_url" {
  type = string
}
