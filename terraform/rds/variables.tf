# 리소스 이름에 사용할 프로젝트 이름
variable "project_name" {
  type = string
}

# RDS를 배치할 VPC
variable "vpc_id" {
  type = string
}

# RDS가 사용할 DB 전용 서브넷 목록
variable "db_subnet_ids" {
  type = list(string)
}

# DB 접속을 허용할 EKS 보안그룹
variable "eks_security_group_id" {
  type = string
}

# RDS 인스턴스 크기
variable "db_instance_class" {
  type = string
}

# RDS MySQL 엔진 버전
variable "db_engine_version" {
  type = string
}

# 실행 시 전달하는 DB 비밀번호: sensitive는 표시를 숨기고 ephemeral은 state 저장을 방지
variable "db_password" {
  type      = string
  sensitive = true
  ephemeral = true
}

variable "manage_db_password" {
  type    = bool
  default = true
}

variable "snapshot_identifier" {
  type    = string
  default = null
}
