# 이 모듈에서 사용할 Terraform 및 Provider 요구사항
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# EKS 클러스터 구성
resource "aws_eks_cluster" "main" {
  name     = var.cluster_name
  version  = var.cluster_version
  role_arn = var.cluster_role_arn

  # 관리 API·감사·인증 로그를 활성화하고 로그 그룹을 먼저 준비합니다.
  enabled_cluster_log_types = ["api", "audit", "authenticator"]
  depends_on                = [aws_cloudwatch_log_group.control_plane]

  # IPv4 기반 Pod 네트워크 사용
  kubernetes_network_config {
    ip_family = "ipv4"
  }

  vpc_config {
    subnet_ids = var.private_subnet_ids

    # VPC 내부 노드는 내부 주소로 관리 API에 접근
    endpoint_private_access = true

    # 내 PC에서는 공인 주소로 관리 API에 접근
    endpoint_public_access = true

    # 외부 접속은 지정한 공인 IP 대역으로 제한
    public_access_cidrs = var.public_access_cidrs
  }

  # 사용자 접근 권한은 액세스 엔트리로 관리
  access_config {
    authentication_mode = "API"

    # 관리자 권한은 다음 단계에서 명시적으로 구성
    bootstrap_cluster_creator_admin_permissions = false
  }

  tags = {
    Name = var.cluster_name
  }
}

# IAM 사용자를 EKS 접근 대상으로 등록
resource "aws_eks_access_entry" "admin" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = var.admin_principal_arn

  # 일반 IAM 사용자 또는 역할의 접근 엔트리
  type = "STANDARD"

  tags = {
    Name = "${var.cluster_name}-admin-access"
  }
}

# 등록한 관리자에게 클러스터 전체 관리 권한 연결
resource "aws_eks_access_policy_association" "admin" {
  cluster_name = aws_eks_cluster.main.name

  # 액세스 엔트리 생성 후 정책을 연결하도록 직접 참조
  principal_arn = aws_eks_access_entry.admin.principal_arn

  policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  # 권한을 클러스터 전체에 적용
  access_scope {
    type = "cluster"
  }
}

# EKS가 자동 생성하기 전에 보관 기간을 명시합니다. 기존 그룹은 먼저 import하세요.
resource "aws_cloudwatch_log_group" "control_plane" {
  name              = "/aws/eks/${var.cluster_name}/cluster"
  retention_in_days = 14
  tags              = { Name = "${var.cluster_name}-control-plane" }
}
