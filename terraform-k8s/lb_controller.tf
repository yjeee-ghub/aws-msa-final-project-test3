# Ingress를 읽고 AWS ALB를 관리하는 Controller 설치
resource "helm_release" "load_balancer_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"

  # 기존 IAM 정책 및 준비된 설정과 맞춘 차트 버전
  version = "3.6.0"

  # EKS에 기본으로 존재하는 시스템 네임스페이스 사용
  namespace = "kube-system"

  values = [
    # 기존에 준비한 복제 수와 CPU/메모리 설정 재사용
    file("${path.module}/../app/msa/k8s/lb-controller/controller-values.yml"),

    # 연결 값은 Terraform 변수와 AWS 생성 결과로 지정
    # 뒤에 전달하는 값이 앞의 YAML 설정보다 우선 적용됨
    yamlencode({
      clusterName = var.cluster_name
      region      = var.aws_region
      vpcId       = data.terraform_remote_state.infra.outputs.vpc_id

      serviceAccount = {
        create = true
        name   = "aws-load-balancer-controller"

        annotations = {
          # 기존 AWS Terraform에서 생성하는 IRSA 역할 연결
          "eks.amazonaws.com/role-arn" = data.terraform_remote_state.infra.outputs.load_balancer_controller_role_arn
        }
      }
    })
  ]

  # Controller 파드가 준비될 때까지 설치 완료를 기다림
  wait    = true
  timeout = 600

  # 설치 실패 시 이번 설치를 정리
  atomic = true

  # Helm 릴리스 변경 이력 보관 개수
  max_history = 3
}
