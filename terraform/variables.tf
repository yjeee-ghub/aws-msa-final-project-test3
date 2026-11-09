# 이번 프로젝트에서 사용할 VPC 대역
variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

# 콘솔에서 찾기 편하게 이름 설정
variable "vpc_name" {
  type    = string
  default = "sol-test3-VPC"
}

# 인터넷 게이트웨이 이름
variable "igw_name" {
  type    = string
  default = "sol-test3-igw"
}

# 서울 리전에서 사용할 가용 영역 두 곳
variable "availability_zones" {
  type    = list(string)
  default = ["ap-northeast-2a", "ap-northeast-2c"]
}

# ALB랑 NAT Gateway가 들어갈 대역
variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.42.1.0/24", "10.42.2.0/24"]
}

# EKS 노드가 들어갈 대역
variable "private_subnet_cidrs" {
  type    = list(string)
  default = ["10.42.11.0/24", "10.42.12.0/24"]
}

# RDS가 들어갈 대역
variable "db_subnet_cidrs" {
  type    = list(string)
  default = ["10.42.21.0/24", "10.42.22.0/24"]
}

# IAM 역할 등 여러 리소스 이름에 사용할 프로젝트 이름
variable "project_name" {
  type    = string
  default = "sol-test3"
}

# EKS 클러스터 이름
variable "eks_cluster_name" {
  type    = string
  default = "sol-test3-eks"
}

# 클러스터와 노드에서 사용할 Kubernetes 버전
variable "eks_cluster_version" {
  type    = string
  default = "1.35"
}

# 외부에서 EKS API에 접속할 수 있는 공인 IP 대역
variable "eks_public_access_cidrs" {
  type = list(string)
}

# EKS를 관리할 IAM 사용자 또는 역할의 ARN
variable "eks_admin_principal_arn" {
  type = string
}

# 노드에서 사용할 EC2 인스턴스 종류
variable "eks_node_instance_types" {
  type    = list(string)
  default = ["t3.medium"]
}

# 처음 생성할 노드 수
variable "eks_node_desired_size" {
  type    = number
  default = 3
}

# 유지할 최소 노드 수
variable "eks_node_min_size" {
  type    = number
  default = 3
}

# 확장할 수 있는 최대 노드 수
variable "eks_node_max_size" {
  type    = number
  default = 6
}

# 전환 완료 후 false: 새로 구축할 때도 AZ별 그룹만 생성
variable "keep_legacy_node_group" {
  type    = bool
  default = false
}

# 서비스별 Docker 이미지를 저장할 ECR 저장소 이름
variable "ecr_repository_names" {
  type = set(string)

  default = [
    "apigateway",
    "member-service",
    "product-service",
    "ordering-service",
    "frontend-service"
  ]
}

# RDS 인스턴스 크기
variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

# RDS MySQL 버전
variable "db_engine_version" {
  type    = string
  default = "8.4.11"
}

# DB 관리자 비밀번호
# 파일과 Terraform state에 저장하지 않고 실행 시 전달
variable "db_password" {
  default   = null
  type      = string
  sensitive = true
  ephemeral = true

  # RDS MySQL의 관리자 비밀번호 길이 제한을 AWS 요청 전에 확인
  validation {
    condition     = var.db_password == null ? true : length(var.db_password) >= 8 && length(var.db_password) <= 41
    error_message = "RDS MySQL 비밀번호는 8~41자로 입력하세요."
  }
}

# 상품 이미지용 버킷 이름
# S3 버킷 이름은 다른 사용자와도 중복될 수 없음
variable "product_image_bucket_name" {
  type    = string
  default = null
}

# 운영 알림을 받을 이메일
variable "alert_email" {
  type = string
}

# true에서는 RDS가 관리자 비밀번호를 생성하여 Secrets Manager에 저장합니다.
variable "manage_db_password" {
  type    = bool
  default = true
}

# Set only for creation from a preserved manual snapshot. Never replaces a live DB.
variable "db_snapshot_identifier" {
  type    = string
  default = null
}
