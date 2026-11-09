# DB 전용 네트워크와 MySQL RDS를 구성하는 모듈
module "rds" {
  source = "./rds"

  project_name = var.project_name

  vpc_id        = module.network.vpc_id
  db_subnet_ids = module.network.db_subnet_ids

  eks_security_group_id = module.eks.cluster_security_group_id

  # 실제 DB 인스턴스 설정
  db_instance_class   = var.db_instance_class
  db_engine_version   = var.db_engine_version
  db_password         = var.db_password
  manage_db_password  = var.manage_db_password
  snapshot_identifier = var.db_snapshot_identifier
}

# 애플리케이션의 DB_HOST에 사용할 주소
output "db_address" {
  value = module.rds.db_address
}
