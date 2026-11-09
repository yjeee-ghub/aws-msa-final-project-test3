# VPC와 서브넷 및 라우팅을 구성하는 네트워크 모듈
module "network" {
  source = "./network"

  # 프로젝트 설정값을 모듈로 전달
  vpc_cidr = var.vpc_cidr
  vpc_name = var.vpc_name
  igw_name = var.igw_name

  # 서브넷을 만들 때 사용할 AZ랑 IP 대역
  availability_zones   = var.availability_zones
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  db_subnet_cidrs      = var.db_subnet_cidrs
}

# 모듈이 전달한 VPC ID를 터미널에 표시
output "vpc_id" {
  value = module.network.vpc_id
}

# VPC에 연결된 인터넷 게이트웨이 ID
output "igw_id" {
  value = module.network.igw_id
}
