# Argo CD에 GitHub 저장소의 앱 배포 대상 등록
resource "helm_release" "argocd_application" {
  name       = "final-apps"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argocd-apps"
  version    = "2.0.6"

  namespace = kubernetes_namespace_v1.argocd.metadata[0].name

  values = [
    yamlencode({
      applications = {
        "final-apps" = {
          namespace = kubernetes_namespace_v1.argocd.metadata[0].name
          project   = "default"

          # Application 삭제 시 앱 리소스도 함께 정리
          finalizers = ["resources-finalizer.argocd.argoproj.io"]

          # 기본 main을 유지하며, 별도 검증 환경에서는 test를 명시할 수 있음
          source = {
            repoURL        = var.github_repo_url
            targetRevision = var.github_revision
            path           = "app/msa"
          }

          # 현재 EKS의 soldesk 네임스페이스로 배포
          destination = {
            server    = "https://kubernetes.default.svc"
            namespace = kubernetes_namespace_v1.soldesk.metadata[0].name
          }

          # HPA가 늘리거나 줄인 파드 수를 Argo CD가 되돌리지 않도록 설정
          ignoreDifferences = concat([{
            group        = "apps"
            kind         = "Deployment"
            name         = "member-depl"
            namespace    = kubernetes_namespace_v1.soldesk.metadata[0].name
            jsonPointers = ["/spec/replicas", "/spec/template/metadata/annotations/final.project~1db-secret-sha256"]
            }], [for name in ["product-depl", "ordering-depl"] : {
            group     = "apps"
            kind      = "Deployment"
            name      = name
            namespace = kubernetes_namespace_v1.soldesk.metadata[0].name
            # 이 annotation만 DB 갱신 worker가 관리합니다. image 등 다른 설정은 Git 관리.
            jsonPointers = ["/spec/template/metadata/annotations/final.project~1db-secret-sha256"]
          }])

          syncPolicy = {
            automated = {
              # 이미지와 앱 Secret 준비 후 true로 변경
              enabled = var.enable_app_sync

              # 자동 배포를 켜면 Git에서 삭제한 리소스도 삭제
              prune = true

              # 클러스터 설정이 달라지면 Git 설정으로 복구
              selfHeal = true
            }

            # 위의 HPA 제외 설정을 실제 배포에도 반영
            syncOptions = ["RespectIgnoreDifferences=true"]
          }
        }
      }
    })
  ]

  wait        = true
  timeout     = 600
  atomic      = true
  max_history = 3

  # 저장소 인증과 앱 Secret이 준비된 뒤 배포 대상 등록
  depends_on = [
    kubernetes_secret_v1.argocd_repository,
    kubernetes_secret_v1.app,
    kubernetes_secret_v1.database,
    helm_release.database_secret,
    terraform_data.database_secret_ready,
    helm_release.argocd,
    terraform_data.load_balancer_webhook_ready
  ]
}
