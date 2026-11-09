# 리소스 이름에 사용할 프로젝트 이름
variable "project_name" {
  type = string
}

# 이미지 업로드를 허용할 ECR 저장소 ARN 목록
variable "ecr_repository_arns" {
  type = list(string)
}

variable "github_oidc_subject" {
  type = string
}

variable "existing_oidc_provider_arn" {
  type    = string
  default = ""
}
