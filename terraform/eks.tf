# 네트워크와 IAM 역할을 EKS 모듈에 전달
module "eks" {
  source = "./eks"

  cluster_name    = var.eks_cluster_name
  cluster_version = var.eks_cluster_version

  cluster_role_arn   = module.iam.eks_cluster_role_arn
  private_subnet_ids = module.network.private_subnet_ids

  public_access_cidrs = var.eks_public_access_cidrs
  admin_principal_arn = var.eks_admin_principal_arn

  # 노드그룹 설정
  node_role_arn       = module.iam.eks_node_role_arn
  node_instance_types = var.eks_node_instance_types

  node_desired_size = var.eks_node_desired_size
  node_min_size     = var.eks_node_min_size
  node_max_size     = var.eks_node_max_size

  # 현재 환경 전환 중에는 tfvars에서 true, 이전 완료 후 false
  keep_legacy_node_group = var.keep_legacy_node_group

  # 2차: a=1/1/3, c=2/2/3 (min/desired/max). 합계 시작·최소 3, 최대 6.
  node_pools = {
    az-a = {
      availability_zone = "ap-northeast-2a"
      subnet_id         = module.network.private_subnet_ids[index(var.availability_zones, "ap-northeast-2a")]
      desired_size      = 1
      min_size          = 1
      max_size          = 3
    }
    az-c = {
      availability_zone = "ap-northeast-2c"
      subnet_id         = module.network.private_subnet_ids[index(var.availability_zones, "ap-northeast-2c")]
      desired_size      = 2
      min_size          = 2
      max_size          = 3
    }
  }

  # IAM 정책 연결과 네트워크 구성이 끝난 뒤 생성
  depends_on = [
    module.iam,
    module.network
  ]
}

# Kubernetes Terraform이 새 ASG 이름과 확장 범위를 읽음
output "autoscaler_node_groups" {
  value = module.eks.autoscaler_node_groups
}
