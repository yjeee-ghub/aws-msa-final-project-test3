# 노드그룹 등에서 사용할 클러스터 이름
output "cluster_name" {
  value = aws_eks_cluster.main.name
}

# Kubernetes 관리 API 주소
output "cluster_endpoint" {
  value = aws_eks_cluster.main.endpoint
}

# EKS가 자동으로 만드는 클러스터 보안그룹 ID
output "cluster_security_group_id" {
  value = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
}

# 기존 단일 이름을 참조하는 코드와의 호환용 출력
output "node_group_name" {
  value = var.keep_legacy_node_group ? aws_eks_node_group.main[0].node_group_name : aws_eks_node_group.zonal["az-a"].node_group_name
}

# 이후 CA 구성에서 참고할 Auto Scaling Group 이름 목록
output "node_group_asg_names" {
  value = flatten([
    for node_group in concat(aws_eks_node_group.main, values(aws_eks_node_group.zonal)) : [
      for node_resource in node_group.resources : [
        for asg in node_resource.autoscaling_groups : asg.name
      ]
    ]
  ])
}

# 알림은 새 그룹과 전환 중인 기존 그룹을 각각 관리
output "notification_node_groups" {
  value = merge(
    {
      for name, node_group in aws_eks_node_group.zonal :
      name => node_group.resources[0].autoscaling_groups[0].name
    },
    {
      for index, node_group in aws_eks_node_group.main :
      "legacy" => node_group.resources[0].autoscaling_groups[0].name
    }
  )
}

# CA는 새 AZ별 그룹만 관리하여 이전 그룹을 다시 늘리지 않음
output "autoscaler_node_groups" {
  value = {
    for name, node_group in aws_eks_node_group.zonal : name => {
      asg_name = node_group.resources[0].autoscaling_groups[0].name
      min_size = var.node_pools[name].min_size
      max_size = var.node_pools[name].max_size
    }
  }
}

# 상품 서비스 IAM 역할에서 사용할 OIDC Provider ARN
output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.main.arn
}

# 역할의 신뢰 조건에 사용할 토큰 발급자 주소
output "oidc_issuer_url" {
  value = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

output "cluster_arn" { value = aws_eks_cluster.main.arn }
