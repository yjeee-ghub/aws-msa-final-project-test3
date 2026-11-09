# Argo CD와 Grafana가 사용할 관리 화면 도메인
locals {
  management_domains = {
    argocd  = local.environment.argoHost
    grafana = local.environment.grafanaHost
  }
}

# 기존 웹사이트 인증서는 유지하고 관리 화면용 인증서를 추가
resource "aws_acm_certificate" "management" {
  domain_name               = local.management_domains.argocd
  subject_alternative_names = [local.management_domains.grafana]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# 두 관리 도메인의 ACM DNS 인증 레코드
resource "aws_route53_record" "management_certificate" {
  for_each = {
    for option in aws_acm_certificate.management.domain_validation_options :
    option.domain_name => {
      name   = option.resource_record_name
      type   = option.resource_record_type
      record = option.resource_record_value
    }
  }

  zone_id = data.aws_route53_zone.website.zone_id
  name    = each.value.name
  type    = each.value.type
  ttl     = 60
  records = [each.value.record]
}

# 발급이 완료된 인증서만 EKS 단계에 전달
resource "aws_acm_certificate_validation" "management" {
  certificate_arn = aws_acm_certificate.management.arn
  validation_record_fqdns = [
    for record in aws_route53_record.management_certificate : record.fqdn
  ]
}

# 공유 ALB 생성과 앱 이전이 끝나기 전에는 DNS 연결 보류
variable "enable_management_dns" {
  type    = bool
  default = false
}

# 웹사이트와 관리 화면 모두 동일한 ALB에 연결
resource "aws_route53_record" "management" {
  for_each = var.enable_management_dns ? local.management_domains : {}

  zone_id = data.aws_route53_zone.website.zone_id
  name    = each.value
  type    = "A"

  alias {
    name                   = data.aws_lb.website[0].dns_name
    zone_id                = data.aws_lb.website[0].zone_id
    evaluate_target_health = true
  }

  lifecycle {
    precondition {
      condition     = var.enable_website_dns
      error_message = "관리 도메인을 연결하려면 enable_website_dns도 true여야 합니다."
    }
  }
}

output "management_certificate_arn" {
  value = aws_acm_certificate_validation.management.certificate_arn
}

output "management_urls" {
  value = {
    for name, domain in local.management_domains : name => "https://${domain}"
  }
}
