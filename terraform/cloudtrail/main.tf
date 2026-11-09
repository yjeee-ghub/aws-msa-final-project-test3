# 이 모듈에서 사용할 Terraform 및 Provider 요구사항
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# 모든 리전의 읽기 및 쓰기 관리 이벤트를 S3에 기록
resource "aws_cloudtrail" "main" {
  name           = local.trail_name
  s3_bucket_name = aws_s3_bucket.logs.id

  # Trail 생성 후 관리 이벤트 기록 시작
  enable_logging = true
  # 서울 외 다른 리전의 관리 작업도 함께 기록
  is_multi_region_trail = true
  # IAM 같은 글로벌 서비스의 이벤트도 기록
  include_global_service_events = true
  # 로그 무결성을 나중에 검증할 수 있도록 다이제스트 파일 생성
  enable_log_file_validation = true

  # 읽기·쓰기 관리 이벤트 기록
  event_selector {
    # 조회와 변경 관리 이벤트를 모두 기록
    read_write_type = "All"
    # AWS 리소스 관리 이벤트 기록: 객체 업로드 등의 데이터 이벤트와 구분
    include_management_events = true
  }

  depends_on = [
    aws_s3_bucket_policy.logs,
    aws_s3_bucket_server_side_encryption_configuration.logs,
  ]
}
