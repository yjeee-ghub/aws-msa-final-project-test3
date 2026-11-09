# 기존 aws-yjeee.com 공개 호스팅 영역 조회: 새 영역을 만들지 않음
data "aws_route53_zone" "website" {
  zone_id = local.environment.hostedZoneId
}

# 서울 ALB에서 사용할 웹사이트 인증서
resource "aws_acm_certificate" "website" {
  domain_name       = local.environment.websiteHost
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# ACM이 지정한 CNAME을 등록하여 도메인 소유권 확인
resource "aws_route53_record" "website_certificate" {
  for_each = {
    for option in aws_acm_certificate.website.domain_validation_options :
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

# 인증서가 발급될 때까지 대기: ALB Controller 설치 전에 완료
resource "aws_acm_certificate_validation" "website" {
  certificate_arn         = aws_acm_certificate.website.arn
  validation_record_fqdns = [for record in aws_route53_record.website_certificate : record.fqdn]
}

# 첫 apply에는 ALB가 없으므로 false 유지
# Kubernetes Ingress로 공유 ALB가 만들어진 뒤 true로 설정
variable "enable_website_dns" {
  type    = bool
  default = false
}

# ALB는 Kubernetes Controller가 생성하고 Terraform은 주소만 조회
variable "website_alb_name" {
  type    = string
  default = "sol-test3-alb"
}

# 공유 ALB로 이전한 뒤 terraform.tfvars에서 이름 변경
data "aws_lb" "website" {
  count = var.enable_website_dns ? 1 : 0
  name  = var.website_alb_name
}

# ALB 생성 후 웹사이트 A 레코드 연결
resource "aws_route53_record" "website" {
  count   = var.enable_website_dns ? 1 : 0
  zone_id = data.aws_route53_zone.website.zone_id
  name    = local.environment.websiteHost
  type    = "A"

  alias {
    name                   = data.aws_lb.website[0].dns_name
    zone_id                = data.aws_lb.website[0].zone_id
    evaluate_target_health = true
  }
}

# 발급 완료된 인증서 ARN과 최종 접속 주소
output "website_certificate_arn" {
  value = aws_acm_certificate_validation.website.certificate_arn
}

output "website_url" {
  value = local.environment.url
}
