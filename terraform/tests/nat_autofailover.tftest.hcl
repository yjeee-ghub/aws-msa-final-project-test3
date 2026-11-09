# All providers mocked. No credential lookup, EC2 creation or route writes.
mock_provider "aws" {
  mock_data "aws_partition" { defaults = { partition = "aws" } }
  mock_data "aws_ssm_parameter" { defaults = { value = "ami-0123456789abcdef0" } }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }
  mock_resource "aws_cloudwatch_event_rule" {
    defaults = { arn = "arn:aws:events:ap-northeast-2:123456789012:rule/offline" }
  }
  mock_resource "aws_lambda_function" {
    defaults = { arn = "arn:aws:lambda:ap-northeast-2:123456789012:function:offline" }
  }
}
mock_provider "archive" {}

run "independent_control_and_scoped_routes" {
  command = apply
  module { source = "./nat-autofailover" }
  variables {
    name        = "offline-nat-controller"
    project_tag = "offline"
    region      = "ap-northeast-2"
    account_id  = "123456789012"
    vpc_id      = "vpc-offline"
    zones = {
      ap-northeast-2a = {
        app_subnet_id = "subnet-app-a", app_route_id = "rtb-app-a", health_cidr = "10.42.31.0/24",
        nat_id        = "nat-a", nat_ip = "1.1.1.1", nat_subnet_id = "subnet-public-a"
      }
      ap-northeast-2c = {
        app_subnet_id = "subnet-app-c", app_route_id = "rtb-app-c", health_cidr = "10.42.32.0/24",
        nat_id        = "nat-c", nat_ip = "2.2.2.2", nat_subnet_id = "subnet-public-c"
      }
    }
  }
  assert {
    condition = length(aws_instance.probe) == 4 && alltrue([for p in aws_instance.probe :
      !p.associate_public_ip_address && p.instance_type == "t3.nano" &&
      p.metadata_options[0].http_tokens == "required" && p.root_block_device[0].encrypted &&
      p.root_block_device[0].delete_on_termination
    ])
    error_message = "Four private encrypted IMDSv2 probes are required, separate from the EKS nodes."
  }
  assert {
    condition = length(aws_vpc_endpoint.ssm) == 2 && alltrue([for ep in aws_vpc_endpoint.ssm :
      ep.private_dns_enabled && ep.vpc_endpoint_type == "Interface" && length(ep.subnet_ids) == 2
    ])
    error_message = "SSM control must remain private and independent of either NAT."
  }
  assert {
    condition = alltrue([for az, z in var.zones :
      aws_route.health[az].nat_gateway_id == z.nat_id &&
      aws_instance.probe["health:${az}"].subnet_id != aws_instance.probe["app:${az}"].subnet_id
    ])
    error_message = "Native recovery probes must not follow the app bypass route."
  }
  assert {
    condition = toset(jsondecode(aws_iam_role_policy.controller.policy).Statement[2].Resource) == toset([
      "arn:aws:ec2:ap-northeast-2:123456789012:route-table/rtb-app-a",
      "arn:aws:ec2:ap-northeast-2:123456789012:route-table/rtb-app-c"
    ]) && jsondecode(aws_iam_role_policy.controller.policy).Statement[2].Action == "ec2:ReplaceRoute"
    error_message = "Route writes must be scoped to the two app tables, never native health routes or arbitrary routes."
  }
  assert {
    condition = (aws_lambda_function.controller.reserved_concurrent_executions == 1 &&
      length(aws_lambda_function.controller.vpc_config) == 0 &&
      aws_cloudwatch_event_rule.monitor.schedule_expression == "rate(1 minute)" &&
      aws_lambda_function_event_invoke_config.controller.maximum_retry_attempts == 0 &&
    aws_cloudwatch_event_target.monitor.retry_policy[0].maximum_retry_attempts == 0)
    error_message = "Single-writer control API must not depend on NAT or retry old events."
  }
  assert {
    condition = jsondecode(aws_lambda_function.controller.environment[0].variables.CONFIG).policy == {
      failure_threshold = 2, recovery_threshold = 3, minimum_bypass_seconds = 120
    }
    error_message = "Keep the demonstrated two-failure, three-recovery and hold-down policy."
  }
}
