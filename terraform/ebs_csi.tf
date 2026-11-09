# 기존 EKS와 OIDC를 사용해 EBS CSI Driver 구성
module "ebs_csi" {
  source = "./ebs_csi"

  project_name = var.project_name
  cluster_name = module.eks.cluster_name

  # ServiceAccount 기반 AWS 인증에 사용할 정보
  oidc_provider_arn = module.eks.oidc_provider_arn
  oidc_issuer_url   = module.eks.oidc_issuer_url

  # 컨트롤러 Pod가 실행될 노드그룹까지 생성된 후 설치
  depends_on = [
    module.eks,
  ]
}

# EBS CSI Driver용 IAM 역할 확인
output "ebs_csi_role_arn" {
  value = module.ebs_csi.role_arn
}

# EBS CSI Driver 애드온 버전 확인
output "ebs_csi_addon_version" {
  value = module.ebs_csi.addon_version
}
