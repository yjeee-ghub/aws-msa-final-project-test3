# AWS 서울 리전
variable "aws_region" {
  type    = string
  default = "ap-northeast-2"
}

# 기존 Terraform과 동일한 AWS CLI 프로필
variable "aws_profile" {
  type    = string
  default = "512-team01"
}

# 내부 도구를 설치할 EKS 클러스터 이름
variable "cluster_name" {
  type    = string
  default = "sol-test3-eks"
}

# Argo CD가 읽을 GitHub 저장소
variable "github_repo_url" {
  type    = string
  default = "https://github.com/yjeee-ghub/aws-msa-final-project-test3.git"
}

# 저장소 읽기 토큰을 발급한 GitHub 사용자
variable "github_revision" {
  description = "Argo CD가 배포할 Git 브랜치 또는 커밋. 기본은 main, 별도 검증은 test 사용."
  type        = string
  default     = "main"
}

# 저장소 읽기 토큰을 발급한 GitHub 사용자
variable "github_username" {
  type    = string
  default = "yjeee-ghub"
}

# 실행할 때만 전달하고 Terraform 상태 파일에는 저장하지 않음
variable "github_token" {
  default   = ""
  type      = string
  sensitive = true
  ephemeral = true
}

# 현재 저장소는 public입니다. private으로 전환할 때만 읽기 토큰 Secret을 만듭니다.
variable "github_repository_public" {
  type    = bool
  default = true
}

# RDS 생성 시 사용한 비밀번호를 앱에도 동일하게 전달
variable "db_password" {
  default   = null
  type      = string
  sensitive = true
  ephemeral = true
}

# 회원 서비스와 API Gateway가 공유하는 JWT 서명 키
variable "jwt_secret" {
  type      = string
  sensitive = true
  ephemeral = true

  validation {
    condition     = length(var.jwt_secret) >= 88 && can(regex("^([A-Za-z0-9+/]{4})*([A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$", var.jwt_secret))
    error_message = "JWT 서명 키는 64바이트 이상의 값을 Base64로 인코딩하세요. Prepare-Secrets.ps1로 생성할 수 있습니다."
  }
}

# 회원 서비스의 Refresh Token 서명 키
variable "jwt_refresh_secret" {
  type      = string
  sensitive = true
  ephemeral = true

  validation {
    condition     = length(var.jwt_refresh_secret) >= 88 && can(regex("^([A-Za-z0-9+/]{4})*([A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$", var.jwt_refresh_secret))
    error_message = "Refresh Token 서명 키는 64바이트 이상의 값을 Base64로 인코딩하세요. Prepare-Secrets.ps1로 생성할 수 있습니다."
  }
}

# 비밀번호나 JWT 키를 변경할 때 이 번호도 증가
variable "app_secret_revision" {
  type    = number
  default = 2

  validation {
    condition     = var.app_secret_revision >= 1 && floor(var.app_secret_revision) == var.app_secret_revision
    error_message = "Secret 변경 번호는 1 이상의 정수여야 합니다."
  }
}

# 이미지 업로드와 Secret 준비를 마친 뒤 true로 변경
variable "enable_app_sync" {
  type    = bool
  default = false
}

# 관리 화면 인증서 발급을 완료한 뒤 true로 설정
variable "enable_management_ingress" {
  type    = bool
  default = false
}

# 서비스 내부 재고/회원 API 전용 키. Prepare-Secrets.ps1에서 생성/재사용합니다.
variable "internal_service_token" {
  type      = string
  sensitive = true
  ephemeral = true
  validation {
    condition     = length(var.internal_service_token) >= 32
    error_message = "내부 서비스 토큰은 32자 이상이어야 합니다."
  }
}

# GitHub 읽기 토큰 교체 시 함께 올립니다.
variable "github_token_revision" {
  type    = number
  default = 1
  validation {
    condition     = var.github_token_revision >= 1 && floor(var.github_token_revision) == var.github_token_revision
    error_message = "github_token_revision은 양의 정수여야 합니다."
  }
}

# Only set by Resume-Lab after restoring the exact bound monitoring claims.
variable "grafana_existing_claim" {
  type    = string
  default = ""
}
variable "grafana_existing_secret" {
  type    = string
  default = ""
}
