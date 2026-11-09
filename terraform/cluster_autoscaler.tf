# 기존 EKS OIDC와 연결해 CA 전용 IAM 권한 구성
module "cluster_autoscaler" {
  source = "./cluster_autoscaler"

  project_name = var.project_name

  # EKS에서 실제 사용하는 클러스터 이름 전달
  cluster_name = module.eks.cluster_name

  # ServiceAccount 기반 AWS 인증에 사용할 OIDC 정보
  oidc_provider_arn = module.eks.oidc_provider_arn
  oidc_issuer_url   = module.eks.oidc_issuer_url
}

# CA 설치 시 사용할 역할 ARN을 터미널에 출력
output "cluster_autoscaler_role_arn" {
  description = "Cluster Autoscaler용 IAM 역할 ARN"
  value       = module.cluster_autoscaler.role_arn
}
