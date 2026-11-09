# 이전 실습 파일 보관

Nginx Ingress, cert-manager 인증서 및 개별 Prometheus/Grafana 설정을 원형 그대로 보관했다.
현재 배포에는 이 폴더를 적용하지 않는다. 앱은 상위 `kustomization.yaml`, 운영 도구는 각 Helm values 파일을 사용한다.
`kubectl apply -R -f app/msa`처럼 모든 파일을 재귀 적용하지 않는다.

