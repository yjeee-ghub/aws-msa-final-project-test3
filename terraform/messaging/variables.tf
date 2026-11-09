# 리소스 이름에 사용할 프로젝트 이름
variable "project_name" {
  type = string
}

# 주문 서비스의 ServiceAccount 토큰을 신뢰할 OIDC Provider
variable "oidc_provider_arn" {
  type = string
}

# IAM 신뢰 조건에 사용할 토큰 발급자 URL
variable "oidc_issuer_url" {
  type = string
}
