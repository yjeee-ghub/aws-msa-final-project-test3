# 다른 모듈에서도 사용할 수 있게 VPC ID 전달
output "vpc_id" {
  value = aws_vpc.main.id
}

# IGW ID도 바깥에서 확인할 수 있게 전달
output "igw_id" {
  value = aws_internet_gateway.main.id
}

# 나중에 ALB랑 NAT에서 사용할 서브넷 ID
output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

# EKS 모듈에 전달할 서브넷 ID
output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

# RDS 모듈에 전달할 서브넷 ID
output "db_subnet_ids" {
  value = aws_subnet.db[*].id
}

# 생성한 S3 Gateway Endpoint ID
output "s3_endpoint_id" {
  value = aws_vpc_endpoint.s3.id
}

output "private_route_table_ids" {
  value = aws_route_table.private[*].id
}

output "nat_gateway_ids" {
  value = aws_nat_gateway.main[*].id
}

output "nat_public_ips" {
  value = aws_eip.nat[*].public_ip
}

