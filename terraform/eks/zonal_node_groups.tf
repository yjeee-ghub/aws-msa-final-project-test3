# EBS가 있는 AZ에 필요한 노드를 정확히 늘릴 수 있도록 AZ별 그룹 생성
data "aws_subnet" "node_pool" {
  for_each = var.node_pools
  id       = each.value.subnet_id
}

resource "aws_eks_node_group" "zonal" {
  for_each = var.node_pools

  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${var.cluster_name}-${each.key}"
  node_role_arn   = var.node_role_arn

  # 한 그룹에는 한 AZ의 서브넷만 지정
  subnet_ids     = [each.value.subnet_id]
  version        = var.cluster_version
  ami_type       = "AL2023_x86_64_STANDARD"
  instance_types = var.node_instance_types
  capacity_type  = "ON_DEMAND"
  disk_size      = 20

  scaling_config {
    desired_size = each.value.desired_size
    min_size     = each.value.min_size
    max_size     = each.value.max_size
  }

  # Autoscaler/모니터링에서 사용할 배치 기준
  labels = {
    "final-node-pool" = each.key
  }

  update_config {
    max_unavailable = 1
  }

  lifecycle {
    # CA가 조절한 현재 노드 수를 Terraform이 되돌리지 않음
    ignore_changes = [scaling_config[0].desired_size]

    precondition {
      condition     = data.aws_subnet.node_pool[each.key].availability_zone == each.value.availability_zone
      error_message = "노드그룹의 서브넷과 가용 영역이 일치해야 합니다."
    }
  }

  tags = {
    Name = "${var.cluster_name}-${each.key}"
  }
}
