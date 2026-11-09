# 이 모듈에서 사용할 Terraform 및 Provider 요구사항
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# 기존 DB 서브넷 두 개를 RDS용 그룹으로 묶기
resource "aws_db_subnet_group" "main" {
  name        = "${lower(var.project_name)}-db-subnet-group"
  description = "DB subnets for the final project"

  subnet_ids = var.db_subnet_ids

  tags = {
    Name = "${var.project_name}-db-subnet-group"
  }
}

# RDS에 연결할 보안그룹
resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds-sg"
  description = "Allow MySQL access from EKS"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.project_name}-rds-sg"
  }
}

# EKS 보안그룹을 사용하는 대상에서 MySQL 접속 허용
resource "aws_vpc_security_group_ingress_rule" "mysql_from_eks" {
  security_group_id = aws_security_group.rds.id

  referenced_security_group_id = var.eks_security_group_id

  ip_protocol = "tcp"
  from_port   = 3306
  to_port     = 3306

  description = "MySQL from EKS nodes and pods"
}

# 서비스에서 사용할 RDS MySQL
resource "aws_db_instance" "main" {
  identifier = "${lower(var.project_name)}-ordermsa-db"

  snapshot_identifier = var.snapshot_identifier
  engine              = "mysql"
  engine_version      = var.db_engine_version
  instance_class      = var.db_instance_class

  # 기존 애플리케이션 설정과 맞추기
  db_name  = "ordermsa"
  username = "admin"
  port     = 3306

  # 비밀번호를 state에 저장하지 않는 쓰기 전용 설정
  manage_master_user_password = var.manage_db_password
  password_wo                 = var.manage_db_password ? null : var.db_password
  # 비밀번호를 변경할 때 함께 올리는 갱신 번호
  password_wo_version = var.manage_db_password ? null : 1

  # 비용 절약용 저장 공간
  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  # 앞 단계에서 만든 DB 네트워크 연결
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  # Multi-AZ DB instance: primary + synchronous standby (not a read replica).
  multi_az            = true
  publicly_accessible = false

  # 자동 백업을 하루 보관
  backup_retention_period    = 1
  auto_minor_version_upgrade = true

  # 실습 환경 삭제 시 최종 스냅샷 생성을 생략
  deletion_protection      = false
  skip_final_snapshot      = true
  delete_automated_backups = true

  lifecycle { ignore_changes = [snapshot_identifier] }

  tags = {
    Name = "${var.project_name}-ordermsa-db"
  }
}
