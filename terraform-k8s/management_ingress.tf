# 도메인별 대상 서비스와 상태 확인 설정
# Prometheus는 외부에 공개하지 않고 기존 내부 접속 유지
locals {
  management_services = {
    argocd = {
      host             = local.environment.argoHost
      namespace        = kubernetes_namespace_v1.argocd.metadata[0].name
      service          = "argocd-server"
      port             = 443
      backend_protocol = "HTTPS"
      healthcheck_path = "/healthz"
    }
    grafana = {
      host             = local.environment.grafanaHost
      namespace        = kubernetes_namespace_v1.monitoring.metadata[0].name
      service          = "monitoring-grafana"
      port             = 80
      backend_protocol = "HTTP"
      healthcheck_path = "/api/health"
    }
  }
}

# 두 Ingress를 같은 그룹에 넣어 ALB 하나를 공유
resource "kubernetes_ingress_v1" "management" {
  for_each = var.enable_management_ingress ? local.management_services : {}

  # ALB 주소가 Ingress에 등록될 때까지 대기
  wait_for_load_balancer = true

  metadata {
    name      = "${each.key}-public"
    namespace = each.value.namespace

    annotations = {
      "alb.ingress.kubernetes.io/group.name"         = "${local.environment.project}-shared"
      "alb.ingress.kubernetes.io/load-balancer-name" = local.environment.loadBalancer
      "alb.ingress.kubernetes.io/scheme"             = "internet-facing"
      "alb.ingress.kubernetes.io/target-type"        = "ip"
      "alb.ingress.kubernetes.io/listen-ports"       = "[{\"HTTP\":80},{\"HTTPS\":443}]"
      "alb.ingress.kubernetes.io/ssl-redirect"       = "443"

      # 같은 HTTPS 리스너에 웹사이트용과 관리 화면용 인증서 등록
      "alb.ingress.kubernetes.io/certificate-arn" = join(",", [
        data.terraform_remote_state.infra.outputs.website_certificate_arn,
        data.terraform_remote_state.infra.outputs.management_certificate_arn
      ])

      # Argo CD의 내부 TLS를 유지하여 리다이렉트 반복 방지
      "alb.ingress.kubernetes.io/backend-protocol"     = each.value.backend_protocol
      "alb.ingress.kubernetes.io/healthcheck-protocol" = each.value.backend_protocol
      "alb.ingress.kubernetes.io/healthcheck-path"     = each.value.healthcheck_path
      "alb.ingress.kubernetes.io/success-codes"        = "200"
    }
  }

  spec {
    ingress_class_name = "alb"

    rule {
      host = each.value.host

      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              name = each.value.service
              port {
                number = each.value.port
              }
            }
          }
        }
      }
    }
  }

  # 두 도구의 설치를 완료한 뒤 관리 화면 공개
  # 삭제 시에도 Ingress finalizer 처리가 끝날 때까지 Controller를 유지합니다.
  depends_on = [helm_release.argocd, helm_release.monitoring, helm_release.load_balancer_controller]
}
