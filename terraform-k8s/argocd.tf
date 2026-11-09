# GitHub의 배포 설정을 EKS에 반영할 Argo CD 설치
resource "helm_release" "argocd" {
  name       = "argocd"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-cd"

  # 기존에 준비한 설정과 맞춘 차트 버전
  version = "10.10.3"

  # 앞 단계에서 만든 Argo CD 네임스페이스 사용
  namespace = kubernetes_namespace_v1.argocd.metadata[0].name

  values = [
    # 단일 복제, CPU/메모리 제한, 관리 화면 설정 재사용
    file("${path.module}/../app/msa/k8s/k8s-argocd/argocd-values.yml"),
    # 공유 ALB로 공개할 때 실제 관리 화면 주소 지정
    yamlencode({
      configs = {
        cm = {
          url = var.enable_management_ingress ? "https://${local.environment.argoHost}" : "https://argocd.example.com"
        }
      }
    })
  ]

  # Argo CD 구성 요소가 준비될 때까지 대기
  wait          = true
  wait_for_jobs = true
  timeout       = 900

  # 설치 실패 시 이번 설치 정리
  atomic      = true
  max_history = 3

  # 설치가 한꺼번에 몰리지 않도록 모니터링 설치 후 진행
  depends_on = [
    helm_release.monitoring
  ]
}
