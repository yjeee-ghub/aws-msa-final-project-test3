# CloudTrail ARN을 루트 모듈로 전달
output "trail_arn" {
  description = "CloudTrail ARN"
  value       = aws_cloudtrail.main.arn
}

# 감사 로그 버킷 이름을 루트 모듈로 전달
output "log_bucket_name" {
  description = "CloudTrail 로그 저장 버킷 이름"
  value       = aws_s3_bucket.logs.id
}
