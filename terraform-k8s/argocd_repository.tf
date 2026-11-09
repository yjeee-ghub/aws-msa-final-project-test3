# Argo CD가 사용할 Private GitHub 저장소 인증 정보
resource "kubernetes_secret_v1" "argocd_repository" {
  count = var.github_repository_public ? 0 : 1
  metadata {
    name = "final-github-repository"

    namespace = kubernetes_namespace_v1.argocd.metadata[0].name

    # Argo CD가 저장소 연결용 Secret으로 인식하는 라벨
    labels = {
      "argocd.argoproj.io/secret-type" = "repository"
    }
  }

  type = "Opaque"

  # 쓰기 전용 속성으로 실제 Secret에 전달
  # 토큰 값을 Terraform 상태 파일에 저장하지 않음
  data_wo = {
    type     = "git"
    url      = var.github_repo_url
    username = var.github_username
    password = var.github_token
  }

  # 토큰을 교체할 때 이 번호도 2, 3 순서로 증가
  data_wo_revision = var.github_token_revision

  # Argo CD 설치가 끝난 뒤 저장소 인증 등록
  depends_on = [
    helm_release.argocd
  ]
}
