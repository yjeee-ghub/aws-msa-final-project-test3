terraform {
  required_providers {
    aws     = { source = "hashicorp/aws" }
    archive = { source = "hashicorp/archive" }
  }
}

variable "name" { type = string }
variable "project_tag" { type = string }
variable "region" { type = string }
variable "account_id" { type = string }
variable "vpc_id" { type = string }
variable "zones" {
  type = map(object({
    app_subnet_id = string
    app_route_id  = string
    health_cidr   = string
    nat_id        = string
    nat_ip        = string
    nat_subnet_id = string
  }))
  validation {
    condition     = length(var.zones) == 2 && length(distinct([for z in var.zones : z.nat_id])) == 2 && length(distinct([for z in var.zones : z.app_route_id])) == 2
    error_message = "서로 다른 NAT와 앱 라우팅 테이블을 가진 두 AZ가 필요합니다."
  }
}

data "aws_partition" "current" {}
data "aws_ssm_parameter" "ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

locals {
  probes = merge(
    { for az, z in var.zones : "app:${az}" => { az = az, role = "app", subnet = z.app_subnet_id } },
    { for az, z in var.zones : "health:${az}" => { az = az, role = "health", subnet = aws_subnet.health[az].id } }
  )
  app_route_arns = [for z in var.zones : "arn:${data.aws_partition.current.partition}:ec2:${var.region}:${var.account_id}:route-table/${z.app_route_id}"]
}

# Native health probes keep their original NAT path while app subnets bypass it.
resource "aws_subnet" "health" {
  for_each                = var.zones
  vpc_id                  = var.vpc_id
  availability_zone       = each.key
  cidr_block              = each.value.health_cidr
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.name}-health-${each.key}", Component = "nat-autofailover" }
}
resource "aws_route_table" "health" {
  for_each = var.zones
  vpc_id   = var.vpc_id
  tags     = { Name = "${var.name}-native-${each.key}" }
}
resource "aws_route" "health" {
  for_each               = var.zones
  route_table_id         = aws_route_table.health[each.key].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = each.value.nat_id
}
resource "aws_route_table_association" "health" {
  for_each       = var.zones
  subnet_id      = aws_subnet.health[each.key].id
  route_table_id = aws_route_table.health[each.key].id
}

resource "aws_security_group" "probe" {
  name_prefix = "${var.name}-probe-"
  description = "NAT probes: no inbound or public IP, HTTPS egress only"
  vpc_id      = var.vpc_id
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${var.name}-probe" }
}
resource "aws_security_group" "endpoints" {
  name_prefix = "${var.name}-ssm-"
  vpc_id      = var.vpc_id
  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.probe.id]
  }
  tags = { Name = "${var.name}-private-control" }
}
resource "aws_vpc_endpoint" "ssm" {
  for_each            = toset(["ssm", "ssmmessages"])
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [for z in var.zones : z.app_subnet_id]
  security_group_ids  = [aws_security_group.endpoints.id]
  tags                = { Name = "${var.name}-${each.key}" }
}
resource "aws_iam_role" "probe" {
  name = "${var.name}-probe"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow",
  Action = "sts:AssumeRole", Principal = { Service = "ec2.amazonaws.com" } }] })
}
resource "aws_iam_role_policy_attachment" "probe" {
  role       = aws_iam_role.probe.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
resource "aws_iam_instance_profile" "probe" {
  name = "${var.name}-probe"
  role = aws_iam_role.probe.name
}
resource "aws_instance" "probe" {
  for_each                    = local.probes
  ami                         = nonsensitive(data.aws_ssm_parameter.ami.value)
  instance_type               = "t3.nano"
  subnet_id                   = each.value.subnet
  vpc_security_group_ids      = [aws_security_group.probe.id]
  iam_instance_profile        = aws_iam_instance_profile.probe.name
  associate_public_ip_address = false
  user_data                   = "#!/bin/bash\nsystemctl enable --now amazon-ssm-agent\n"
  metadata_options { http_tokens = "required" }
  root_block_device {
    volume_size           = 8
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
    tags                  = { Project = var.project_tag, Component = "nat-autofailover" }
  }
  tags = { Name = "${var.name}-${each.value.role}-${each.value.az}", Component = "nat-autofailover" }
  depends_on = [aws_vpc_endpoint.ssm, aws_route.health, aws_route_table_association.health,
  aws_iam_role_policy_attachment.probe]
  lifecycle {
    # Do not replace probes during unrelated applies when the public AMI advances.
    ignore_changes = [ami]
  }
}

resource "aws_dynamodb_table" "state" {
  name         = "${var.name}-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"
  attribute {
    name = "id"
    type = "S"
  }
  server_side_encryption { enabled = true }
}
resource "aws_cloudwatch_log_group" "controller" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = 7
}
resource "aws_iam_role" "controller" {
  name = var.name
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow",
  Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }] })
}
resource "aws_iam_role_policy" "controller" {
  role = aws_iam_role.controller.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.controller.arn}:*" },
    { Effect = "Allow", Action = ["ec2:DescribeRouteTables", "ec2:DescribeNatGateways", "ec2:DescribeInstances"], Resource = "*" },
    { Effect = "Allow", Action = "ec2:ReplaceRoute", Resource = local.app_route_arns },
    { Effect = "Allow", Action = "ssm:SendCommand", Resource = concat(
      ["arn:${data.aws_partition.current.partition}:ssm:${var.region}::document/AWS-RunShellScript"],
    [for p in aws_instance.probe : p.arn]) },
    { Effect = "Allow", Action = "ssm:GetCommandInvocation", Resource = "*" },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem"], Resource = aws_dynamodb_table.state.arn }
  ] })
}

data "archive_file" "controller" {
  type        = "zip"
  source_dir  = "${path.module}/../../lambda/nat_failover"
  output_path = "${path.root}/.terraform/nat-autofailover.zip"
  excludes    = ["__pycache__", "__pycache__/*"]
}
resource "aws_cloudwatch_event_rule" "monitor" {
  name                = "${var.name}-every-minute"
  schedule_expression = "rate(1 minute)"
  state               = "ENABLED"
}
resource "aws_lambda_function" "controller" {
  function_name                  = var.name
  role                           = aws_iam_role.controller.arn
  runtime                        = "python3.13"
  handler                        = "controller.handler"
  filename                       = data.archive_file.controller.output_path
  source_code_hash               = data.archive_file.controller.output_base64sha256
  timeout                        = 40
  memory_size                    = 192
  reserved_concurrent_executions = 1
  # Intentionally outside the VPC: NAT failure must not break the control API.
  environment {
    variables = {
      CONFIG = jsonencode({
        account = var.account_id, region = var.region, vpc = var.vpc_id,
        table   = aws_dynamodb_table.state.name, rule_arn = aws_cloudwatch_event_rule.monitor.arn,
        policy  = { failure_threshold = 2, recovery_threshold = 3, minimum_bypass_seconds = 120 },
        zones = { for az, z in var.zones : az => {
          app_route    = z.app_route_id
          health_route = aws_route_table.health[az].id
          nat          = { id = z.nat_id, ip = z.nat_ip, subnet = z.nat_subnet_id }
          probes = { for role in ["app", "health"] : role => {
            instance = aws_instance.probe["${role}:${az}"].id
            subnet   = local.probes["${role}:${az}"].subnet
          } }
        } }
      })
    }
  }
  depends_on = [aws_iam_role_policy.controller]
}
resource "aws_lambda_function_event_invoke_config" "controller" {
  function_name                = aws_lambda_function.controller.function_name
  maximum_event_age_in_seconds = 60
  maximum_retry_attempts       = 0
}
resource "aws_lambda_permission" "schedule" {
  statement_id   = "ScheduledNatHealthCheck"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.controller.function_name
  principal      = "events.amazonaws.com"
  source_arn     = aws_cloudwatch_event_rule.monitor.arn
  source_account = var.account_id
}
resource "aws_cloudwatch_event_target" "monitor" {
  rule = aws_cloudwatch_event_rule.monitor.name
  arn  = aws_lambda_function.controller.arn
  retry_policy {
    maximum_event_age_in_seconds = 60
    maximum_retry_attempts       = 0
  }
  depends_on = [aws_lambda_permission.schedule, aws_lambda_function_event_invoke_config.controller]
}

output "controller" {
  value = {
    function = aws_lambda_function.controller.function_name
    rule     = aws_cloudwatch_event_rule.monitor.name
    table    = aws_dynamodb_table.state.name
    vpc      = var.vpc_id
    timeout  = aws_lambda_function.controller.timeout
    zones = { for az, z in var.zones : az => {
      app_route    = z.app_route_id, native_nat = z.nat_id, native_ip = z.nat_ip,
      health_route = aws_route_table.health[az].id,
      app_probe    = aws_instance.probe["app:${az}"].id, health_probe = aws_instance.probe["health:${az}"].id
    } }
  }
}
