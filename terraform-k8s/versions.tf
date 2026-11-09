# EKS 내부 설치에 사용할 Terraform과 Provider
terraform {
  required_version = ">= 1.12.0, < 2.0.0"

  required_providers {
    # 이미 생성한 EKS 정보 조회
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }

    # 네임스페이스와 Kubernetes 리소스 관리
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.38"
    }

    # 모니터링과 Argo CD 등의 Helm 차트 설치
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.0"
    }
  }
}
