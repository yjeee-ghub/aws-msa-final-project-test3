# IAM 역할 이름에 사용할 프로젝트 이름
variable "project_name" {
  type = string
}

# 애드온을 설치할 EKS 클러스터 이름
variable "cluster_name" {
  type = string
}

# ServiceAccount 토큰을 신뢰할 OIDC Provider ARN
variable "oidc_provider_arn" {
  type = string
}

# IAM 신뢰 조건에 사용할 토큰 발급자 URL
variable "oidc_issuer_url" {
  type = string
}

# 서울 리전과 Kubernetes 1.35에서 지원되는 버전으로 고정
variable "addon_version" {
  type    = string
  default = "v1.66.1-eksbuild.1"
}
