# 리소스 이름에 사용할 프로젝트 이름
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

