# AWS 관리 이벤트를 비공개 S3에 기록하는 감사 로그 모듈
module "cloudtrail" {
  source = "./cloudtrail"

  project_name = var.project_name
  account_id   = data.aws_caller_identity.current.account_id
  region       = "ap-northeast-2"
}

# AWS 관리 작업을 기록하는 CloudTrail ARN
output "cloudtrail_arn" {
  description = "CloudTrail ARN"
  value       = module.cloudtrail.trail_arn
}

# CloudTrail 로그가 저장되는 비공개 S3 버킷 이름
output "cloudtrail_log_bucket_name" {
  description = "CloudTrail 로그 저장 버킷 이름"
  value       = module.cloudtrail.log_bucket_name
}
