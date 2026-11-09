# Bound SQS consumption; this is not an SES rate-per-second guarantee.
variable "customer_email_max_concurrency" {
  type    = number
  default = 2
  validation {
    condition     = var.customer_email_max_concurrency >= 2 && var.customer_email_max_concurrency <= 1000 && floor(var.customer_email_max_concurrency) == var.customer_email_max_concurrency
    error_message = "SQS maximum concurrency must be an integer from 2 to 1000."
  }
}
# SES 인증 완료 후에만 소비자를 켭니다. 테스트 브랜치 push는 이 리소스를 적용하지 않습니다.
variable "customer_email_enabled" {
  type    = bool
  default = false
  validation {
    condition     = !var.customer_email_enabled || var.customer_email_sender != ""
    error_message = "소비자 활성화 전에 SES 발신자 주소가 필요합니다."
  }
}
variable "customer_email_sender" {
  type    = string
  default = ""
  validation {
    condition     = var.customer_email_sender == "" || can(regex("^[^[:space:]@]+@[^[:space:]@]+\\.[^[:space:]@]+$", var.customer_email_sender))
    error_message = "발신자 이메일 형식을 확인하세요."
  }
}
variable "manage_ses_identities" {
  type    = bool
  default = false
}
variable "customer_email_test_recipients" {
  type    = set(string)
  default = []
}
variable "customer_email_admin" {
  description = "신규 주문 알림을 받을 관리자 이메일. 설치 설정에서 관리자 계정 이메일과 함께 지정합니다."
  type        = string
  default     = ""
  validation {
    condition     = var.customer_email_admin == "" || can(regex("^[^[:space:]@]+@[^[:space:]@]+\\.[^[:space:]@]+$", var.customer_email_admin))
    error_message = "관리자 주문 알림 이메일 형식을 확인하세요."
  }
}
locals { email_configured = var.customer_email_sender != "" }
data "archive_file" "order_email" {
  count       = local.email_configured ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/../lambda/order_email"
  output_path = "${path.module}/.terraform/order-email.zip"
  excludes    = ["__pycache__", "__pycache__/*"]
}
resource "aws_ses_email_identity" "order_sender" {
  count = local.email_configured && var.manage_ses_identities ? 1 : 0
  email = var.customer_email_sender
}
resource "aws_ses_email_identity" "order_test_recipient" {
  for_each = var.manage_ses_identities ? setsubtract(var.customer_email_test_recipients, toset([var.customer_email_sender])) : toset([])
  email    = each.value
}
resource "aws_dynamodb_table" "email_dedup" {
  count        = local.email_configured ? 1 : 0
  name         = "${var.project_name}-order-email-dedup"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "eventId"
  attribute {
    name = "eventId"
    type = "S"
  }
  ttl {
    attribute_name = "expiresAt"
    enabled        = true
  }
}
resource "aws_iam_role" "order_email" {
  count              = local.email_configured ? 1 : 0
  name               = "${var.project_name}-order-email-lambda"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_cloudwatch_log_group" "order_email" {
  count             = local.email_configured ? 1 : 0
  name              = "/aws/lambda/${var.project_name}-order-email"
  retention_in_days = 14
}
resource "aws_iam_role_policy" "order_email" {
  count = local.email_configured ? 1 : 0
  role  = aws_iam_role.order_email[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = module.messaging.order_notifications_queue_arn },
    # Keep the sender fixed while permitting SES identity authorization in this account/region.
    { Effect    = "Allow", Action = ["ses:SendEmail"],
      Resource  = "arn:aws:ses:ap-northeast-2:${data.aws_caller_identity.current.account_id}:identity/*",
      Condition = { StringEquals = { "ses:FromAddress" = var.customer_email_sender } }
    },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:UpdateItem"], Resource = aws_dynamodb_table.email_dedup[0].arn },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.order_email[0].arn}:*" }
  ] })
}
resource "aws_lambda_function" "order_email" {
  count            = local.email_configured ? 1 : 0
  function_name    = "${var.project_name}-order-email"
  role             = aws_iam_role.order_email[0].arn
  runtime          = "python3.13"
  handler          = "handler.handler"
  filename         = data.archive_file.order_email[0].output_path
  source_code_hash = data.archive_file.order_email[0].output_base64sha256
  # Buyer/admin sends are independent; allow both bounded SDK calls to finish.
  timeout                        = 60
  memory_size                    = 128
  reserved_concurrent_executions = -1
  environment {
    variables = {
      SENDER_EMAIL = var.customer_email_sender
      DEDUP_TABLE  = aws_dynamodb_table.email_dedup[0].name
      ADMIN_EMAIL  = var.customer_email_admin
    }
  }
  depends_on = [aws_iam_role_policy.order_email]
}
resource "aws_lambda_event_source_mapping" "order_email" {
  count            = local.email_configured ? 1 : 0
  event_source_arn = module.messaging.order_notifications_queue_arn
  function_name    = aws_lambda_function.order_email[0].arn
  enabled          = var.customer_email_enabled
  scaling_config { maximum_concurrency = var.customer_email_max_concurrency }
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]
  lifecycle {
    precondition {
      condition     = !var.customer_email_enabled || local.email_configured
      error_message = "SES 발신자 및 샌드박스 수신자 인증 후 소비자를 활성화하세요."
    }
  }
}
check "email_sender_required" {
  assert {
    condition     = !var.customer_email_enabled || local.email_configured
    error_message = "customer_email_enabled=true에는 발신자 주소가 필요합니다."
  }
}
output "customer_email_consumer" { value = try(aws_lambda_function.order_email[0].function_name, null) }
