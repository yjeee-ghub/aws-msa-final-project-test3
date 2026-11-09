# EKS 클러스터에 전달할 역할 ARN
output "eks_cluster_role_arn" {
  value = aws_iam_role.eks_cluster.arn
}

# EKS 노드그룹에 전달할 역할 ARN
output "eks_node_role_arn" {
  value = aws_iam_role.eks_node.arn
}
