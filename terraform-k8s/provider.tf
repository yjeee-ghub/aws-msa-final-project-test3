# 기존 AWS 인프라와 동일한 계정으로 조회
provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  # 다른 계정에서 실행되는 것을 방지
  allowed_account_ids = [local.environment.account]
}

# AWS 인프라 단계에서 생성한 EKS 정보 조회
data "aws_eks_cluster" "main" {
  name = var.cluster_name
}

# Kubernetes API에 접속하여 리소스 관리
provider "kubernetes" {
  host = data.aws_eks_cluster.main.endpoint

  # EKS API 서버의 인증서 확인
  cluster_ca_certificate = base64decode(
    data.aws_eks_cluster.main.certificate_authority[0].data
  )

  # 고정 토큰 대신 AWS CLI로 임시 인증 토큰 발급
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"

    args = [
      "eks", "get-token",
      "--cluster-name", var.cluster_name,
      "--region", var.aws_region,
      "--profile", var.aws_profile
    ]
  }
}

# Helm 차트를 같은 EKS 클러스터에 설치
# Helm Provider 3.x는 kubernetes = { ... } 문법 사용
provider "helm" {
  kubernetes = {
    host = data.aws_eks_cluster.main.endpoint

    cluster_ca_certificate = base64decode(
      data.aws_eks_cluster.main.certificate_authority[0].data
    )

    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"

      args = [
        "eks", "get-token",
        "--cluster-name", var.cluster_name,
        "--region", var.aws_region,
        "--profile", var.aws_profile
      ]
    }
  }
}
