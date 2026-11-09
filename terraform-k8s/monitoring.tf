locals {
  # 새 AWS 출력이 준비된 다음 적용해야 새 노드 라벨로 배치 가능
  use_zonal_monitoring = length(local.autoscaler_node_groups) > 0

  # Grafana와 Prometheus를 같은 작은 노드에 함께 배치하지 않음
  monitoring_anti_affinity = {
    podAntiAffinity = {
      requiredDuringSchedulingIgnoredDuringExecution = [{
        topologyKey = "kubernetes.io/hostname"
        labelSelector = {
          matchExpressions = [
            {
              key      = "app.kubernetes.io/name"
              operator = "In"
              values   = ["grafana", "prometheus"]
            },
            {
              # Operator가 만든 Prometheus는 Helm 릴리스와 instance 라벨이 다름
              key      = "app.kubernetes.io/instance"
              operator = "In"
              values   = ["monitoring", "monitoring-kube-prometheus-prometheus"]
            }
          ]
        }
      }]
    }
  }
}

# Prometheus, Grafana, Alertmanager 설치
resource "helm_release" "monitoring" {
  name       = "monitoring"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"

  # 기존에 검증한 모니터링 차트 버전
  version = "92.3.0"

  # 앞 단계에서 만든 monitoring 네임스페이스 사용
  namespace = kubernetes_namespace_v1.monitoring.metadata[0].name

  values = [
    # CPU/메모리, EBS 저장 공간, 수집 대상, 알림 규칙 재사용
    file("${path.module}/../app/msa/k8s/k8s-monitoring/monitoring-values.yml"),

    # AWS 연결 값은 실제 Terraform 생성 결과로 지정
    yamlencode({
      # 공개 도메인으로 로그인 후 이동할 주소 지정
      grafana = merge(var.enable_management_ingress ? {
        "grafana.ini" = {
          server = {
            domain   = local.environment.grafanaHost
            root_url = "https://${local.environment.grafanaHost}"
          }
          # 대시보드는 기존 로그인 인증을 유지
          "auth.anonymous" = {
            enabled = false
          }
        }
        } : {}, {
        persistence = var.grafana_existing_claim != "" ? { existingClaim = var.grafana_existing_claim } : {}
        admin       = var.grafana_existing_secret != "" ? { existingSecret = var.grafana_existing_secret } : {}
        # 기존 Grafana EBS와 같은 2c 그룹 사용
        nodeSelector = local.use_zonal_monitoring ? { "final-node-pool" = "az-c" } : {}
        affinity     = local.use_zonal_monitoring ? local.monitoring_anti_affinity : null
      })

      prometheus = {
        prometheusSpec = {
          nodeSelector = local.use_zonal_monitoring ? { "final-node-pool" = "az-c" } : {}
          affinity     = local.use_zonal_monitoring ? local.monitoring_anti_affinity : null
          # 차트 기본 규칙이 사용자 podAntiAffinity를 덮어쓰지 않도록 비활성화
          podAntiAffinity = local.use_zonal_monitoring ? "" : "soft"
        }
      }

      alertmanager = {
        # 기존 Alertmanager EBS가 있는 2a 그룹 사용
        alertmanagerSpec = {
          nodeSelector = local.use_zonal_monitoring ? { "final-node-pool" = "az-a" } : {}
        }

        serviceAccount = {
          create = true

          # 기존 IAM 신뢰 정책의 이름과 일치
          name = "alertmanager"

          annotations = {
            "eks.amazonaws.com/role-arn" = data.terraform_remote_state.infra.outputs.alertmanager_role_arn
          }
        }

        config = {
          # receivers 목록은 아래 값으로 교체
          # 기존 YAML의 route와 알림 규칙은 유지
          receivers = [
            {
              # 기본 알림은 SNS로 전송하지 않음
              name = "null"
            },
            {
              # Final로 시작하는 프로젝트 알림의 수신 대상
              name = "operations-sns"

              sns_configs = [
                {
                  # ServiceAccount의 IAM 역할로 AWS 인증
                  sigv4 = {
                    region = var.aws_region
                  }

                  # 기존 AWS Terraform에서 생성한 운영 알림 토픽
                  topic_arn = data.terraform_remote_state.infra.outputs.operations_alerts_topic_arn

                  # 장애 해소 알림도 전달
                  send_resolved = true

                  # 아래 템플릿은 Alertmanager가 알림 발송 시 처리
                  subject = "[Final] {{ .Status }}: {{ .GroupLabels.alertname }}"

                  message = <<-EOT
                    프로젝트: ${var.cluster_name}
                    상태: {{ .Status }}
                    {{ range .Alerts }}
                    - {{ .Annotations.summary }}
                      {{ .Annotations.description }}
                    {{ end }}
                  EOT
                }
              ]
            }
          ]
        }
      }
    })
  ]

  # 모니터링 파드와 설치 작업이 준비될 때까지 대기
  wait          = true
  wait_for_jobs = true
  timeout       = 900

  # 설치 실패 시 이번 설치 정리
  atomic      = true
  max_history = 3

  # 저장 규칙과 Controller 설치가 끝난 뒤 모니터링 설치
  depends_on = [
    kubernetes_storage_class_v1.gp3,
    helm_release.cluster_autoscaler,
    terraform_data.load_balancer_webhook_ready
  ]
}
