# 서비스별 이미지 저장소 구성
module "ecr" {
  source = "./ecr"

  repository_names = var.ecr_repository_names
}

# Docker push와 Kubernetes 이미지 설정에 사용할 주소
output "ecr_repository_urls" {
  value = module.ecr.repository_urls
}
