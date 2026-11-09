provider "aws" {
  # 지역은 서울
  region = local.environment.region

  # Profile Default
  profile = local.environment.profile

  allowed_account_ids = [local.environment.account]

  # 콘솔에서 알기 쉽도록 Tag
  default_tags {
    tags = {
      Project = var.project_name
    }
  }
}

# AWS CLI로 로그인한 계정 정보 가져오기
# 여기서는 조회만 하고 리소스를 만들지는 않음
data "aws_caller_identity" "current" {}

# 내가 쓰려던 계정이 맞는지 ID 확인
output "aws_account_id" {
  value = data.aws_caller_identity.current.account_id
}
