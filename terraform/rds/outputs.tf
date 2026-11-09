# 실제 DB 인스턴스에서 사용할 서브넷 그룹 이름
output "db_subnet_group_name" {
  value = aws_db_subnet_group.main.name
}

# 실제 DB 인스턴스에 연결할 보안그룹 ID
output "db_security_group_id" {
  value = aws_security_group.rds.id
}

# 포트를 제외한 DB 호스트 주소
output "db_address" {
  value = aws_db_instance.main.address
}

# 애플리케이션에서 접속할 DB 포트
output "db_port" {
  value = aws_db_instance.main.port
}

# 애플리케이션에서 사용할 데이터베이스 이름
output "db_name" {
  value = aws_db_instance.main.db_name
}

# CloudWatch에서 감시할 RDS 인스턴스 식별자
output "db_instance_identifier" {
  value = aws_db_instance.main.identifier
}

output "master_secret_arn" {
  value = try(aws_db_instance.main.master_user_secret[0].secret_arn, null)
}
