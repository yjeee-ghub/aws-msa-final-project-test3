# EKS가 발급한 ServiceAccount 토큰을 IAM에서 신뢰하도록 등록
resource "aws_iam_openid_connect_provider" "main" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer

  client_id_list = ["sts.amazonaws.com"]

  tags = {
    Name = "${var.cluster_name}-oidc"
  }
}
