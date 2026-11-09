# Built-in Terraform state item, not an AWS resource. Check before charts create Services.
resource "terraform_data" "load_balancer_webhook_ready" {
  triggers_replace = [
    helm_release.load_balancer_controller.id,
    helm_release.load_balancer_controller.version,
    sha256(join("", helm_release.load_balancer_controller.values)),
    sha256(local.readiness_python_command),
    filesha256("${path.module}/../scripts/ops/wait_webhook.py")
  ]
  provisioner "local-exec" {
    interpreter = ["python", "-c"]
    command     = local.readiness_python_command
    environment = merge(local.readiness_environment, {
      FINAL_CHECK_SCRIPT = abspath("${path.module}/../scripts/ops/wait_webhook.py")
    })
  }
}
