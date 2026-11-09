# 이 모듈에서 사용할 Terraform 및 Provider 요구사항
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# 프로젝트에서 사용할 VPC
resource "aws_vpc" "main" {
  # 바깥에서 받은 IP 대역 사용
  cidr_block = var.vpc_cidr

  # DNS 검색과 호스트 이름 사용
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = var.vpc_name
  }
}

# 위에서 만든 VPC에 IGW 연결
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = var.igw_name
  }
}

# ALB와 NAT Gateway를 배치할 퍼블릭 서브넷
resource "aws_subnet" "public" {
  count = length(var.public_subnet_cidrs)

  vpc_id            = aws_vpc.main.id
  cidr_block        = var.public_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  # EC2에 공인 IP를 자동으로 할당하지 않기
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.vpc_name}-public-${count.index + 1}"

    # ALB 컨트롤러가 퍼블릭 서브넷을 찾을 때 사용
    "kubernetes.io/role/elb" = "1"
  }
}

# EKS 노드가 들어갈 프라이빗 서브넷 두 개
resource "aws_subnet" "private" {
  count = length(var.private_subnet_cidrs)

  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  map_public_ip_on_launch = false

  tags = {
    Name = "${var.vpc_name}-private-${count.index + 1}"

    # 내부용 로드밸런서가 사용할 서브넷
    "kubernetes.io/role/internal-elb" = "1"
  }
}

# RDS용 서브넷 두 개
resource "aws_subnet" "db" {
  count = length(var.db_subnet_cidrs)

  vpc_id            = aws_vpc.main.id
  cidr_block        = var.db_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  map_public_ip_on_launch = false

  tags = {
    Name = "${var.vpc_name}-db-${count.index + 1}"
  }
}

# 퍼블릭 서브넷에서 사용할 라우팅 테이블
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  # 인터넷 목적지로 가는 트래픽을 IGW로 보내기
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.vpc_name}-public-rt"
  }
}

# 퍼블릭 서브넷 두 개를 위 라우팅 테이블에 연결
resource "aws_route_table_association" "public" {
  count = length(var.public_subnet_cidrs)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# EKS용 프라이빗 라우팅 테이블을 AZ별로 만들기
resource "aws_route_table" "private" {
  count = length(var.private_subnet_cidrs)

  vpc_id = aws_vpc.main.id

  # 인터넷으로 나가는 NAT 경로는 다음 단계에서 추가
  tags = {
    Name = "${var.vpc_name}-private-rt-${count.index + 1}"
  }
}

# 프라이빗 서브넷을 각각의 라우팅 테이블에 연결
resource "aws_route_table_association" "private" {
  count = length(var.private_subnet_cidrs)

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# DB 서브넷에서 사용할 라우팅 테이블
resource "aws_route_table" "db" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.vpc_name}-db-rt"
  }
}

# DB 서브넷 두 개를 DB 라우팅 테이블에 연결
resource "aws_route_table_association" "db" {
  count = length(var.db_subnet_cidrs)

  subnet_id      = aws_subnet.db[count.index].id
  route_table_id = aws_route_table.db.id
}

# NAT Gateway에서 사용할 고정 공인 IP
resource "aws_eip" "nat" {
  count  = length(var.availability_zones)
  domain = "vpc"

  tags = {
    Name = "${var.vpc_name}-nat-eip-${count.index + 1}"
  }
}

# 각 AZ의 퍼블릭 서브넷에 NAT를 배치한다. 장애 우회는 별도 nat_autofailover 제어기가 담당한다.
resource "aws_nat_gateway" "main" {
  count         = length(var.availability_zones)
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  connectivity_type = "public"

  tags = {
    Name = "${var.vpc_name}-nat-${count.index + 1}"
  }

  lifecycle {
    precondition {
      condition = (
        length(var.availability_zones) == 2 &&
        length(distinct(var.availability_zones)) == 2 &&
        length(var.public_subnet_cidrs) == 2 &&
        length(var.private_subnet_cidrs) == 2 &&
        length(var.db_subnet_cidrs) == 2
      )
      error_message = "This lab requires two distinct AZs and two public/private/DB subnets in matching AZ order."
    }
  }

  # IGW와 퍼블릭 경로가 준비된 뒤 생성
  depends_on = [
    aws_internet_gateway.main,
    aws_route_table_association.public
  ]
}

# 프라이빗 라우팅 테이블 두 개에 인터넷 기본 경로 추가
resource "aws_route" "private_nat" {
  count = length(var.private_subnet_cidrs)

  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main[count.index].id

  lifecycle {
    # Terraform creates/removes the route; only the controller owns its runtime
    # target. Re-applying infra must not undo a verified bypass during a fault.
    # When disabling the controller, restore and verify native routes first.
    ignore_changes = [nat_gateway_id]
  }
}

# Retain the existing AZ-a resources if an older state is used. Fresh installs
# create both indexed resources; they are not a migration screenshot.
moved {
  from = aws_eip.nat
  to   = aws_eip.nat[0]
}

moved {
  from = aws_nat_gateway.main
  to   = aws_nat_gateway.main[0]
}
