# 이 파일에서 재사용할 이름과 인증 조건 값
locals {
  trail_name = "${var.project_name}-management-trail"

  # Trail 생성 전에 버킷 정책을 구성하기 위해 ARN을 조합
  trail_arn = "arn:aws:cloudtrail:${var.region}:${var.account_id}:trail/${local.trail_name}"
}

resource "aws_s3_bucket" "logs" {
  bucket = "${lower(var.project_name)}-cloudtrail-${var.account_id}-${var.region}"

  # 실수로 로그까지 삭제되지 않도록 보호
  force_destroy = false
}

# 버킷 소유자가 객체를 소유하도록 설정하고 ACL 사용 비활성화
resource "aws_s3_bucket_ownership_controls" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# 감사 로그 버킷의 공개 접근을 모두 차단
resource "aws_s3_bucket_public_access_block" "logs" {
  bucket = aws_s3_bucket.logs.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

# S3 관리 키로 저장 객체를 기본 암호화
resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# 감사 로그를 30일 보관한 뒤 만료 처리
resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "expire-after-30-days"
    status = "Enabled"

    filter {
      prefix = ""
    }

    # 보관 기간이 지난 객체를 S3 수명 주기로 정리
    expiration {
      days = 30
    }
  }
}

# 지정한 CloudTrail만 계정별 로그 경로에 기록하도록 허용
resource "aws_s3_bucket_policy" "logs" {
  bucket = aws_s3_bucket.logs.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "CloudTrailAclCheck"
        Effect = "Allow"

        Principal = {
          Service = "cloudtrail.amazonaws.com"
        }

        Action   = "s3:GetBucketAcl"
        Resource = aws_s3_bucket.logs.arn

        Condition = {
          StringEquals = {
            "aws:SourceArn" = local.trail_arn
          }
        }
      },
      {
        Sid    = "CloudTrailWrite"
        Effect = "Allow"

        Principal = {
          Service = "cloudtrail.amazonaws.com"
        }

        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.logs.arn}/AWSLogs/${var.account_id}/*"

        Condition = {
          StringEquals = {
            "aws:SourceArn" = local.trail_arn
            "s3:x-amz-acl"  = "bucket-owner-full-control"
          }
        }
      }
    ]
  })

  depends_on = [
    aws_s3_bucket_ownership_controls.logs,
    aws_s3_bucket_public_access_block.logs,
  ]
}
