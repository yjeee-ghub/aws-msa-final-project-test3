# ALB 컨트롤러용 IRSA 역할과 권한을 준비하는 모듈
module "lb_controller" {
  source = "./lb_controller"

  project_name = var.project_name

  oidc_provider_arn = module.eks.oidc_provider_arn
  oidc_issuer_url   = module.eks.oidc_issuer_url
}

# ALB 컨트롤러 ServiceAccount에 연결할 IAM 역할 ARN
output "load_balancer_controller_role_arn" {
  description = "AWS Load Balancer Controller용 IAM 역할 ARN"
  value       = module.lb_controller.role_arn
}
