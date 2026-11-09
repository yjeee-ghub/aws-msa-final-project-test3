# 리소스 이름에 사용할 프로젝트 이름
variable "project_name" {
  type = string
}

# 정책 범위와 버킷 이름에 사용할 AWS 계정 ID
variable "account_id" {
  type = string
}

# 리소스와 ARN에 사용할 AWS 리전
variable "region" {
  type = string
}
