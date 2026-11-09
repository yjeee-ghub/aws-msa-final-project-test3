# 이 모듈에서 사용할 Terraform 및 Provider 요구사항
terraform {
  # Terraform은 1.12 이상으로 사용
  # 2.x는 일단 제외해두기
  required_version = ">= 1.12.0, < 2.0.0"

  required_providers {
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
    aws = {
      # AWS 연결에 사용할 공식 provider
      source = "hashicorp/aws"

      # provider는 6.x 안에서 사용
      version = "~> 6.0"
    }
  }
}
