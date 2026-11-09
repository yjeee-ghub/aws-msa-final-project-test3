# 먼저 terraform 루트의 apply를 완료해야 합니다. 다른 state 키를 참조하지 않도록 고정.
data "terraform_remote_state" "infra" {
  backend = "s3"
  config = {
    bucket              = local.environment.stateBucket
    key                 = "${local.environment.project}/infra/terraform.tfstate"
    region              = local.environment.region
    profile             = var.aws_profile
    encrypt             = true
    allowed_account_ids = [local.environment.account]
  }
}
