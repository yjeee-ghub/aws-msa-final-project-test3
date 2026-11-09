# 저장소 이름별 이미지 업로드 주소
output "repository_urls" {
  value = {
    for name, repository in aws_ecr_repository.main :
    name => repository.repository_url
  }
}

# CI의 이미지 업로드 권한을 해당 ECR 저장소로 제한할 때 사용
output "repository_arns" {
  value = [
    for repository in aws_ecr_repository.main : repository.arn
  ]
}
