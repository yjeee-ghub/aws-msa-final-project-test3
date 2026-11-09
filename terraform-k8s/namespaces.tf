# 애플리케이션 파드와 서비스를 배포할 공간
resource "kubernetes_namespace_v1" "soldesk" {
  metadata {
    name = "soldesk"
  }
}

# Prometheus, Grafana, Alertmanager를 설치할 공간
resource "kubernetes_namespace_v1" "monitoring" {
  metadata {
    name = "monitoring"
  }
}

# Argo CD를 설치할 공간
resource "kubernetes_namespace_v1" "argocd" {
  metadata {
    name = "argocd"
  }
}
