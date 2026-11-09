# chart 버전은 고정합니다. 첫 설치에서 CRD 조회가 필요한 kubernetes_manifest는 사용하지 않습니다.
resource "helm_release" "external_secrets" {
  count            = data.terraform_remote_state.infra.outputs.manage_db_password ? 1 : 0
  name             = "external-secrets"
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  version          = "0.20.4"
  namespace        = "external-secrets"
  create_namespace = true
  depends_on       = [terraform_data.load_balancer_webhook_ready]
  wait             = true
  timeout          = 600
  values = [yamlencode({
    installCRDs    = true
    resources      = { requests = { cpu = "20m", memory = "64Mi" }, limits = { cpu = "200m", memory = "256Mi" } }
    webhook        = { resources = { requests = { cpu = "10m", memory = "32Mi" }, limits = { cpu = "100m", memory = "128Mi" } } }
    certController = { resources = { requests = { cpu = "10m", memory = "32Mi" }, limits = { cpu = "100m", memory = "128Mi" } } }
  })]
}
resource "helm_release" "database_secret" {
  count     = data.terraform_remote_state.infra.outputs.manage_db_password ? 1 : 0
  name      = "database-secret"
  chart     = "${path.module}/charts/database-secret"
  namespace = kubernetes_namespace_v1.soldesk.metadata[0].name
  values = [yamlencode({
    region    = var.aws_region
    secretArn = data.terraform_remote_state.infra.outputs.database_secret_arn
    roleArn   = data.terraform_remote_state.infra.outputs.database_secret_reader_role_arn
  })]
  depends_on = [helm_release.external_secrets]
}

# Helm installed does not imply that ESO has fetched the password successfully.
resource "terraform_data" "database_secret_ready" {
  count = data.terraform_remote_state.infra.outputs.manage_db_password ? 1 : 0
  triggers_replace = [
    helm_release.database_secret[0].id,
    sha256(join("", helm_release.database_secret[0].values)),
    sha256(local.readiness_python_command),
    filesha256("${path.module}/../scripts/ops/wait_database_secret.py"),
    filesha256("${path.module}/../scripts/ops/wait_webhook.py")
  ]
  provisioner "local-exec" {
    interpreter = ["python", "-c"]
    command     = local.readiness_python_command
    environment = merge(local.readiness_environment, {
      FINAL_CHECK_SCRIPT = abspath("${path.module}/../scripts/ops/wait_database_secret.py")
    })
  }
}
