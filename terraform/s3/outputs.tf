# 상품 서비스 설정에 사용할 이름
output "bucket_name" {
  value = aws_s3_bucket.product_images.id
}

# 이후 상품 서비스 IAM 정책에서 사용할 ARN
output "bucket_arn" {
  value = aws_s3_bucket.product_images.arn
}

# 이후 Kubernetes ServiceAccount에 연결할 역할 ARN
output "product_s3_role_arn" {
  value = aws_iam_role.product_s3.arn
}
