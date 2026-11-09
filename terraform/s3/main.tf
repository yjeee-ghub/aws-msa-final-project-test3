# 이 모듈에서 사용할 Terraform 및 Provider 요구사항
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# 상품 이미지 저장소
resource "aws_s3_bucket" "product_images" {
  bucket = var.bucket_name

  # 파일이 남아 있으면 버킷 삭제 방지
  force_destroy = false

  tags = {
    Name = var.bucket_name
  }
}

# ACL을 사용하지 않고 정책으로 접근 권한 관리
resource "aws_s3_bucket_ownership_controls" "product_images" {
  bucket = aws_s3_bucket.product_images.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# 저장되는 객체에 기본 암호화 적용
resource "aws_s3_bucket_server_side_encryption_configuration" "product_images" {
  bucket = aws_s3_bucket.product_images.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# 공개 ACL은 차단하고, 공개 읽기 버킷 정책은 허용
resource "aws_s3_bucket_public_access_block" "product_images" {
  bucket = aws_s3_bucket.product_images.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = false
  restrict_public_buckets = false
}

# products/ 경로의 이미지에만 공개 읽기 허용
resource "aws_s3_bucket_policy" "product_images" {
  bucket = aws_s3_bucket.product_images.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid       = "PublicReadProductImages"
        Effect    = "Allow"
        Principal = "*"

        Action = "s3:GetObject"

        Resource = "${aws_s3_bucket.product_images.arn}/products/*"
      }
    ]
  })

  # 공개 정책 차단 설정을 먼저 구성
  depends_on = [
    aws_s3_bucket_public_access_block.product_images
  ]
}
