# 바깥에서 VPC 대역 받아오기
variable "vpc_cidr" {
  type = string
}

# AWS 콘솔에 표시할 VPC 이름
variable "vpc_name" {
  type = string
}

# 인터넷 게이트웨이 이름
variable "igw_name" {
  type = string
}

# 바깥에서 정한 가용 영역 받아오기
variable "availability_zones" {
  type = list(string)
}

# 퍼블릭 서브넷 대역 받아오기
variable "public_subnet_cidrs" {
  type = list(string)
}

# EKS용 프라이빗 서브넷 대역 받아오기
variable "private_subnet_cidrs" {
  type = list(string)
}

# DB 전용 서브넷 대역 받아오기
variable "db_subnet_cidrs" {
  type = list(string)
}
