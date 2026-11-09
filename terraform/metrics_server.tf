# HPA에 Pod CPU·메모리 사용량을 제공하는 Metrics Server
resource "aws_eks_addon" "metrics_server" {
  # 기존 EKS 클러스터에 설치
  cluster_name = module.eks.cluster_name

  addon_name = "metrics-server"

  # 서울 리전, Kubernetes 1.35에서 확인한 기본 지원 버전
  addon_version = "v0.9.0-eksbuild.11"

  # 기존 설치와 설정이 충돌하면 오류로 확인하고 처리
  resolve_conflicts_on_create = "NONE"
  resolve_conflicts_on_update = "NONE"

  # Metrics Server Pod가 실행될 노드그룹까지 생성된 후 설치
  depends_on = [
    module.eks,
  ]
}

# 설치 대상으로 설정한 Metrics Server 버전 확인
output "metrics_server_addon_version" {
  description = "Metrics Server 애드온 버전"
  value       = aws_eks_addon.metrics_server.addon_version
}
