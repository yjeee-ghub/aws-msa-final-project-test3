# IAM 역할과 정책 이름에 사용할 프로젝트 이름
variable "project_name" {
  type = string
}

# CA가 관리할 EKS 클러스터 이름
variable "cluster_name" {
  type = string
}

# ServiceAccount 토큰을 신뢰할 EKS OIDC Provider ARN
variable "oidc_provider_arn" {
  type = string
}

# IAM 신뢰 조건에 사용할 토큰 발급자 URL
variable "oidc_issuer_url" {
  type = string
}
