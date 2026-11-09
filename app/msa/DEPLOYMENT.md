# 배포 안내

현재 운영 도구는 `terraform-k8s`로 관리하고 앱은 Argo CD가 배포한다.

이 문서에 있던 초기 수동 Helm 설치 명령은 현재 구성과 달라 제거했다. 같은 도구를 중복 설치하지 않도록 아래 문서를 기준으로 확인한다.

- [프로젝트 구성](../../docs/01-architecture.md)
- [배포 자동화](../../docs/02-deployment.md)
- [앱 기능 설정 절차](APP-FEATURES.md)

AWS 인프라 → EKS 내부 구성과 이미지·Secret 준비 → 앱 배포 → ALB 확인 후 DNS 연결 순으로 진행한다. 비밀번호·토큰·Terraform 상태 파일은 저장소에 올리지 않는다.

## 개선 코드 적용 안내

`test` 브랜치 개선 사항의 초기 구축·재구축·삭제 순서는 [월요일 PowerShell 실행 안내](../../docs/06-monday-runbook.md)를 기준으로 진행합니다. main 반영과 실제 AWS 적용은 별도 작업입니다.
