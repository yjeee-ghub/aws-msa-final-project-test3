# 이 모듈에서 사용할 Terraform 및 Provider 요구사항
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# 서비스 이름별로 ECR 저장소 생성
resource "aws_ecr_repository" "main" {
  for_each = var.repository_names

  name = each.value

  # 기존 latest 태그 업로드 방식과 호환
  image_tag_mutability = "MUTABLE"

  # 이미지가 남아 있으면 저장소 삭제 방지
  force_delete = false

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = each.value
  }
}

# 태그 없는 오래된 이미지를 정리해 저장 공간 절약
resource "aws_ecr_lifecycle_policy" "main" {
  for_each = aws_ecr_repository.main

  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"

        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }

        action = {
          type = "expire"
        }
      }
    ]
  })
}
