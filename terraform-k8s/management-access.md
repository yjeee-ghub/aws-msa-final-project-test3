# 관리 화면 도메인 연결

| 도메인 | 대상 |
|---|---|
| https://server.syong.store | 프로젝트 웹사이트 |
| https://argocd.syong.store | Argo CD 관리 화면 |
| https://grafana.syong.store | Grafana 대시보드 |

세 주소는 `final-shared` IngressGroup의 `final-shared-alb` 하나를 공유한다.
웹사이트 인증서와 관리 화면 인증서는 ALB의 HTTPS 리스너에 함께 등록한다.
HTTP 요청은 HTTPS로 전환하고, Argo CD와 Grafana의 기존 로그인은 유지한다.
Prometheus는 내부 서비스로 유지한다.

## Terraform 설정

`C:\aws-msa-backend-terraform\terraform\terraform.tfvars`:

```hcl
enable_website_dns    = true
website_alb_name      = "final-shared-alb"
enable_management_dns = true
```

`C:\aws-msa-backend-terraform\terraform-k8s\terraform.tfvars`:

```hcl
enable_app_sync           = true
enable_management_ingress = true
```

실제 tfvars, 상태 파일, Plan 파일, 비밀번호와 토큰은 Git에 올리지 않는다.

## 처음 구성하는 순서

1. AWS Terraform으로 인프라와 ACM 인증서를 생성한다. DNS 연결은 우선 끈다.
2. GitHub Actions로 이미지를 ECR에 올린다.
3. EKS Terraform으로 도구와 관리 Ingress를 설치하고 앱 자동 배포를 켠다.
4. 공유 ALB 주소를 확인한 뒤 AWS Terraform의 DNS 연결을 켠다.

기존 `final-app-alb`에서 이전하는 경우 관리 Ingress를 먼저 생성하고,
앱 Ingress의 공유 그룹 설정을 Git에 반영한 뒤 DNS를 새 ALB로 연결한다.
공유 그룹으로 옮길 때 기존 ALB가 삭제되므로 이전 중 접속이 잠시 끊길 수 있다.

## 확인 명령

```powershell
kubectl get ingress -A
kubectl get applications -n argocd
kubectl get pods -n soldesk
Resolve-DnsName argocd.syong.store -Server 1.1.1.1
Resolve-DnsName grafana.syong.store -Server 1.1.1.1
```

관리 화면은 기존 admin 비밀번호로 접속한다. 로그인과 대시보드를 확인한 뒤
노드·파드 장애 대응 실습을 진행한다. Argo CD CLI는 이 UI용 ALB 구성을 사용할 때
`--grpc-web` 옵션을 사용한다.

## 삭제 순서

DNS를 먼저 해제하고, EKS Terraform을 정리한 다음 AWS Terraform을 정리한다.
EKS가 남아 있는 동안 Argo CD와 ALB Controller가 앱과 ALB를 삭제해야 한다.
Grafana·Prometheus·Alertmanager의 PVC와 EBS 잔존 여부도 별도로 확인한다.
