# 프로젝트 인프라와 별도로 한 번만 준비하며 이 폴더의 local state도 안전하게 보관합니다.
terraform {
  required_version = ">= 1.12.0, < 2.0.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}
provider "aws" {
  region              = "ap-northeast-2"
  profile             = "512-team01"
  allowed_account_ids = ["683668078297"]
}
variable "state_bucket_name" {
  type    = string
  default = "sol-test3-tfstate-683668078297-ap-northeast-2"
}
resource "aws_s3_bucket" "state" {
  bucket        = var.state_bucket_name
  force_destroy = false
  tags          = { Project = "sol-test3", Purpose = "TerraformState", Retain = "true" }
  # 별도 루트 + 삭제 보호: 프로젝트 destroy에 포함되지 않으며 이 루트도 삭제를 거부합니다.
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport", Effect = "Deny", Principal = "*", Action = "s3:*"
      Resource  = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}
output "state_bucket_name" { value = aws_s3_bucket.state.id }
