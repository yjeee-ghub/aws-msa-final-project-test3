# 기존 상태 주소를 보존하여 전환 준비 단계에서 삭제/재생성하지 않음
moved {
  from = aws_eks_node_group.main
  to   = aws_eks_node_group.main[0]
}

# 전환 중에만 유지하는 기존 다중 AZ 노드그룹
resource "aws_eks_node_group" "main" {
  count = var.keep_legacy_node_group ? 1 : 0

  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${var.cluster_name}-nodes"

  # 앞에서 만든 EC2 노드용 IAM 역할
  node_role_arn = var.node_role_arn

  # 기존 프라이빗 서브넷 두 개에 노드 배치
  subnet_ids = var.private_subnet_ids

  # 클러스터와 같은 Kubernetes 버전 사용
  version = var.cluster_version

  # EKS 최적화 Amazon Linux 2023, x86_64 이미지
  ami_type = "AL2023_x86_64_STANDARD"

  # 비용과 장애 실습을 고려해 선택한 노드 인스턴스 종류
  instance_types = var.node_instance_types
  # 중단 가능성이 있는 Spot 대신 On-Demand 노드 사용
  capacity_type = "ON_DEMAND"

  # 노드마다 사용할 루트 디스크 크기
  disk_size = 20

  # 초기 노드 수와 CA가 조절할 최소 및 최대 범위
  scaling_config {
    desired_size = var.node_desired_size
    min_size     = var.node_min_size
    max_size     = var.node_max_size
  }

  # 업데이트 중 동시에 사용 불가능해질 노드 수
  update_config {
    max_unavailable = 1
  }

  # 이후 CA가 늘리거나 줄인 노드 수를 Terraform이 되돌리지 않기
  lifecycle {
    ignore_changes = [
      scaling_config[0].desired_size
    ]
  }

  tags = {
    Name = "${var.cluster_name}-nodes"
  }
}
