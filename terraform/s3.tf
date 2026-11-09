# 상품 이미지 저장소와 상품 서비스용 IAM 역할
module "s3" {
  source = "./s3"

  bucket_name  = coalesce(var.product_image_bucket_name, local.environment.productImageBucket)
  project_name = var.project_name

  oidc_provider_arn = module.eks.oidc_provider_arn
  oidc_issuer_url   = module.eks.oidc_issuer_url
}

# 상품 서비스에 설정할 버킷 이름
output "product_image_bucket_name" {
  value = module.s3.bucket_name
}

# ServiceAccount에 연결할 IAM 역할 ARN
output "product_s3_role_arn" {
  value = module.s3.product_s3_role_arn
}
