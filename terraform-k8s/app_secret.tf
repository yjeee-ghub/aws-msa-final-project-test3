# 앱이 참조하는 DB 접속 정보와 JWT 키 생성
resource "kubernetes_secret_v1" "app" {
  metadata {
    name      = "my-app-secrets"
    namespace = kubernetes_namespace_v1.soldesk.metadata[0].name
  }

  type = "Opaque"

  # 쓰기 전용 속성: 비밀번호와 JWT 키를 Terraform 상태에 저장하지 않음
  # Kubernetes Secret에는 실제 값이 저장되므로 조회 권한은 관리해야 함
  data_wo = {
    DB_HOST                = data.terraform_remote_state.infra.outputs.db_address
    INTERNAL_SERVICE_TOKEN = var.internal_service_token
    JWT_SECRET             = var.jwt_secret
    JWT_REFRESH_SECRET     = var.jwt_refresh_secret
  }

  # 쓰기 전용 값의 변경은 이 번호를 올려 Terraform에 알려줌
  data_wo_revision = var.app_secret_revision
}

# 수동 비밀번호 방식과 ESO가 같은 Secret을 동시에 관리하지 않게 분리합니다.
resource "kubernetes_secret_v1" "database" {
  count = data.terraform_remote_state.infra.outputs.manage_db_password ? 0 : 1
  metadata {
    name      = "db-credentials"
    namespace = kubernetes_namespace_v1.soldesk.metadata[0].name
  }
  data_wo          = { DB_PW = var.db_password }
  data_wo_revision = var.app_secret_revision
}
