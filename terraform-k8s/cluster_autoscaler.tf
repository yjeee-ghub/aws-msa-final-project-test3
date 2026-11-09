locals {
  # AWS 준비 적용 전에는 기존 자동 탐색 설정 유지
  autoscaler_node_groups = try(data.terraform_remote_state.infra.outputs.autoscaler_node_groups, {})
}

# 배치하지 못한 파드가 생기면 노드 확장을 판단하는 CA 설치
resource "helm_release" "cluster_autoscaler" {
  depends_on = [terraform_data.load_balancer_webhook_ready]
  name       = "cluster-autoscaler"
  repository = "https://kubernetes.github.io/autoscaler"
  chart      = "cluster-autoscaler"

  # EKS 1.35용 이미지 설정을 지원하는 차트 버전
  version   = "9.59.0"
  namespace = "kube-system"

  values = [
    yamlencode({
      # 생성할 Kubernetes 리소스 이름 고정
      fullnameOverride = "cluster-autoscaler"

      cloudProvider = "aws"
      awsRegion     = var.aws_region

      # AZ별 그룹 전환 후에는 명시한 새 그룹만 관리
      autoDiscovery = {
        clusterName = length(local.autoscaler_node_groups) > 0 ? "" : var.cluster_name
      }

      autoscalingGroups = [
        for group in values(local.autoscaler_node_groups) : {
          name    = group.asg_name
          minSize = group.min_size
          maxSize = group.max_size
        }
      ]

      # 높은 우선순위의 CA가 2c의 Grafana를 밀어내지 않도록 분리
      nodeSelector = length(local.autoscaler_node_groups) > 0 ? { "final-node-pool" = "az-a" } : {}

      # EKS와 같은 Kubernetes 마이너 버전 사용
      image = {
        repository = "registry.k8s.io/autoscaling/cluster-autoscaler"
        tag        = "v1.35.2"
      }

      # Kubernetes 조회·노드 관리 권한과 ServiceAccount 생성
      rbac = {
        create = true

        serviceAccount = {
          create = true

          # 기존 IAM 신뢰 정책에서 허용한 이름과 일치
          name = "cluster-autoscaler"

          annotations = {
            # AWS 인프라 단계에서 생성한 CA 전용 역할 연결
            "eks.amazonaws.com/role-arn" = data.terraform_remote_state.infra.outputs.cluster_autoscaler_role_arn
          }
        }
      }

      # 실습 비용을 고려해 CA 파드 한 개 실행
      replicaCount      = 1
      priorityClassName = "system-cluster-critical"

      extraArgs = {
        # 확장 판단 과정을 확인할 로그 수준
        v               = "4"
        stderrthreshold = "info"

        # 현재 클러스터 이름 전달
        "cluster-name" = var.cluster_name

        # 확장할 그룹을 선택할 때 자원 낭비 고려
        expander = "least-waste"

        # 로컬 임시 저장 공간 사용 파드가 있어도 축소 검토
        # 해당 파드의 임시 데이터는 노드 축소 시 사라질 수 있음
        "skip-nodes-with-local-storage" = "false"
      }

      # 기존 CA YAML과 동일한 자원 설정
      resources = {
        requests = {
          cpu    = "100m"
          memory = "600Mi"
        }
        limits = {
          cpu    = "100m"
          memory = "600Mi"
        }
      }
    })
  ]

  # CA 파드 준비까지 대기
  wait    = true
  timeout = 600

  # 설치 실패 시 이번 설치 정리
  atomic      = true
  max_history = 3
}
