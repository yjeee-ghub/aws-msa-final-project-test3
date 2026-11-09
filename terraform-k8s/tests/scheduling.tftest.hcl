# Plan-only mocks: no AWS/Kubernetes/Helm changes or real credentials.
mock_provider "aws" {
  mock_data "aws_eks_cluster" {
    defaults = {
      endpoint              = "https://example.invalid"
      certificate_authority = [{ data = "dGVzdA==" }]
    }
  }
}
mock_provider "kubernetes" {}
mock_provider "helm" {}

override_data {
  target = data.terraform_remote_state.infra
  values = {
    outputs = {
      autoscaler_node_groups = {
        az-a = { asg_name = "mock-final-az-a", min_size = 1, max_size = 3 }
        az-c = { asg_name = "mock-final-az-c", min_size = 2, max_size = 3 }
      }
      manage_db_password                = true
      database_secret_arn               = "arn:aws:secretsmanager:ap-northeast-2:683668078297:secret:mock-database"
      database_secret_reader_role_arn   = "arn:aws:iam::683668078297:role/mock-secret-reader"
      db_address                        = "db.example.invalid"
      vpc_id                            = "vpc-0123456789abcdef0"
      cluster_autoscaler_role_arn       = "arn:aws:iam::683668078297:role/mock-ca"
      load_balancer_controller_role_arn = "arn:aws:iam::683668078297:role/mock-lb"
      alertmanager_role_arn             = "arn:aws:iam::683668078297:role/mock-alertmanager"
      operations_alerts_topic_arn       = "arn:aws:sns:ap-northeast-2:683668078297:mock-alerts"
      management_certificate_arn        = "arn:aws:acm:ap-northeast-2:683668078297:certificate/mock-management"
      website_certificate_arn           = "arn:aws:acm:ap-northeast-2:683668078297:certificate/mock-website"
    }
  }
}

variables {
  internal_service_token    = "mock-internal-service-token-only-32-chars"
  db_password               = "mock-password-only" # gitleaks:allow -- mock provider fixture, not a credential
  github_token              = "mock-token-only"
  jwt_secret                = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
  jwt_refresh_secret        = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
  enable_management_ingress = true
  enable_app_sync           = true
}

run "zonal_scheduling" {
  command = plan

  assert {
    condition     = yamldecode(helm_release.cluster_autoscaler.values[0]).nodeSelector["final-node-pool"] == "az-a"
    error_message = "CA must stay in the new 2a pool."
  }
  assert {
    condition     = length(yamldecode(helm_release.cluster_autoscaler.values[0]).autoscalingGroups) == 2 && yamldecode(helm_release.cluster_autoscaler.values[0]).autoDiscovery.clusterName == ""
    error_message = "CA must manage exactly the two zonal groups, excluding the legacy group."
  }
  assert {
    condition     = sum([for group in yamldecode(helm_release.cluster_autoscaler.values[0]).autoscalingGroups : group.maxSize]) == 6
    error_message = "New pool maximum must be six nodes total."
  }
  assert {
    condition     = yamldecode(helm_release.monitoring.values[1]).grafana.nodeSelector["final-node-pool"] == "az-c" && yamldecode(helm_release.monitoring.values[1]).prometheus.prometheusSpec.nodeSelector["final-node-pool"] == "az-c"
    error_message = "Grafana and Prometheus must remain in their EBS zone."
  }
  assert {
    condition     = yamldecode(helm_release.monitoring.values[1]).alertmanager.alertmanagerSpec.nodeSelector["final-node-pool"] == "az-a"
    error_message = "Alertmanager must remain in its existing EBS zone."
  }
  assert {
    condition     = yamldecode(helm_release.monitoring.values[1]).grafana.affinity == yamldecode(helm_release.monitoring.values[1]).prometheus.prometheusSpec.affinity && contains(yamldecode(helm_release.monitoring.values[1]).grafana.affinity.podAntiAffinity.requiredDuringSchedulingIgnoredDuringExecution[0].labelSelector.matchExpressions[1].values, "monitoring-kube-prometheus-prometheus")
    error_message = "Anti-affinity must match both actual workload labels."
  }
  assert {
    condition     = yamldecode(helm_release.monitoring.values[1]).prometheus.prometheusSpec.podAntiAffinity == ""
    error_message = "Disable the chart-generated anti-affinity so it cannot overwrite the custom rule."
  }
  assert {
    condition     = length(kubernetes_secret_v1.database) == 0 && length(helm_release.external_secrets) == 1 && length(helm_release.database_secret) == 1
    error_message = "Managed password must have one ESO owner and no Terraform-owned password Secret."
  }
  assert {
    condition     = length(kubernetes_secret_v1.argocd_repository) == 0
    error_message = "Public source must not require a GitHub token Secret."
  }

}

run "private_repository_opt_in" {
  command = plan
  variables {
    github_repository_public = false
  }
  assert {
    condition     = length(kubernetes_secret_v1.argocd_repository) == 1
    error_message = "Private repository opt-in must create its authentication Secret."
  }
}

run "restored_grafana_claim" {
  command = plan
  variables {
    grafana_existing_claim  = "monitoring-grafana"
    grafana_existing_secret = "monitoring-grafana-restored"
  }
  assert {
    condition     = yamldecode(helm_release.monitoring.values[1]).grafana.persistence.existingClaim == "monitoring-grafana" && yamldecode(helm_release.monitoring.values[1]).grafana.admin.existingSecret == "monitoring-grafana-restored"
    error_message = "Restore must reuse the prebound Grafana PVC and its original credentials."
  }
}
