# EKS에서 사용할 IAM 역할 구성
module "iam" {
  source = "./iam"

  project_name = var.project_name
}
