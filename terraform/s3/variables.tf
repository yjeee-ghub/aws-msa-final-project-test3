# 상품 이미지를 저장할 S3 버킷 이름
variable "bucket_name" {
  type = string
}

# IAM 역할 이름에 사용할 프로젝트 이름
variable "project_name" {
  type = string
}

# Pod의 IAM 인증을 신뢰할 EKS OIDC Provider ARN
variable "oidc_provider_arn" {
  type = string
}

# ServiceAccount 토큰 발급자 URL
variable "oidc_issuer_url" {
  type = string
}

# 역할을 사용할 Kubernetes 네임스페이스
variable "product_namespace" {
  type    = string
  default = "soldesk"
}

# 역할을 사용할 ServiceAccount 이름
variable "product_service_account_name" {
  type    = string
  default = "product-service-account"
}
