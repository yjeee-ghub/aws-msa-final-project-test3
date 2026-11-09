variable "nat_autofailover_enabled" {
  description = "AZ별 NAT 경로 자동 우회·복귀. 검사 EC2 4대와 SSM Interface Endpoint 2개 등 추가 비용 발생."
  type        = bool
  default     = true
}

variable "nat_health_subnet_cidrs" {
  description = "원래 NAT에 고정된 회복 검사 서브넷. 기존 public/app/DB CIDR와 겹치지 않아야 합니다."
  type        = list(string)
  default     = ["10.42.31.0/24", "10.42.32.0/24"]
  validation {
    condition     = length(var.nat_health_subnet_cidrs) == 2 && length(distinct(var.nat_health_subnet_cidrs)) == 2 && alltrue([for c in var.nat_health_subnet_cidrs : can(cidrnetmask(c))])
    error_message = "두 개의 서로 다른 IPv4 검사 서브넷 CIDR가 필요합니다."
  }
}

module "nat_autofailover" {
  count      = var.nat_autofailover_enabled ? 1 : 0
  source     = "./nat-autofailover"
  depends_on = [module.network]

  name        = "${var.project_name}-nat-autofailover"
  project_tag = var.project_name
  account_id  = data.aws_caller_identity.current.account_id
  region      = local.environment.region
  vpc_id      = module.network.vpc_id
  zones = { for i, az in var.availability_zones : az => {
    app_subnet_id = module.network.private_subnet_ids[i]
    app_route_id  = module.network.private_route_table_ids[i]
    health_cidr   = var.nat_health_subnet_cidrs[i]
    nat_id        = module.network.nat_gateway_ids[i]
    nat_ip        = module.network.nat_public_ips[i]
    nat_subnet_id = module.network.public_subnet_ids[i]
  } }
}

output "nat_autofailover" {
  description = "NAT 제어기 조회·정지와 잔여 자원 검사에 사용하는 비민감 운영 정보"
  value       = var.nat_autofailover_enabled ? module.nat_autofailover[0].controller : null
}
