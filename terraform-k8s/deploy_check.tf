resource "kubernetes_role_v1" "deploy_check" {
  metadata {
    name      = "deployment-reader"
    namespace = kubernetes_namespace_v1.soldesk.metadata[0].name
  }
  rule {
    api_groups = ["apps"]
    resources  = ["deployments"]
    verbs      = ["get", "list", "watch"]
  }
}
resource "kubernetes_role_binding_v1" "deploy_check" {
  metadata {
    name      = "deployment-reader"
    namespace = kubernetes_namespace_v1.soldesk.metadata[0].name
  }
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role_v1.deploy_check.metadata[0].name
  }
  subject {
    kind      = "Group"
    name      = "final-deploy-readers"
    api_group = "rbac.authorization.k8s.io"
  }
}
resource "kubernetes_role_v1" "argocd_check" {
  metadata {
    name      = "final-app-reader"
    namespace = kubernetes_namespace_v1.argocd.metadata[0].name
  }
  rule {
    api_groups     = ["argoproj.io"]
    resources      = ["applications"]
    resource_names = ["final-apps"]
    verbs          = ["get"]
  }
}
resource "kubernetes_role_binding_v1" "argocd_check" {
  metadata {
    name      = "final-app-reader"
    namespace = kubernetes_namespace_v1.argocd.metadata[0].name
  }
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role_v1.argocd_check.metadata[0].name
  }
  subject {
    kind      = "Group"
    name      = "final-deploy-readers"
    api_group = "rbac.authorization.k8s.io"
  }
}
