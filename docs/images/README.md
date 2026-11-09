# 아키텍처 이미지와 로고 출처

[architecture.svg](architecture.svg)가 편집 원본이고 [architecture.png](architecture.png)는 같은 SVG를 직접 렌더링한 결과입니다. 레이아웃·문구·연결선이 동일합니다. SVG에는 사용한 아이콘을 data URI로 포함해 GitHub에서 외부 파일 요청 없이 표시되도록 했습니다. 한국어는 Malgun Gothic / Noto Sans KR / Apple SD Gothic Neo 순서의 글꼴을 사용하며 PNG는 한글 글꼴이 설치된 Windows 환경에서 생성했습니다.

## 아이콘

- AWS: [AWS 공식 Architecture Icons](https://aws.amazon.com/architecture/icons/), 2026-07-31 배포 패키지. 공식 서비스·리소스 SVG의 형태와 색상을 유지했습니다. 실제 리소스가 아닌 AWS 로고를 임의의 서비스로 쓰지 않았습니다.
- Kubernetes·Argo·Prometheus: 프로젝트 / CNCF의 실제 로고.
- Grafana: Grafana 저장소의 실제 로고.
- Docker·Terraform·GitHub Actions: Simple Icons에서 제공하는 브랜드 로고 SVG.
- 사용한 파일과 개별 출처는 [icons/sources.json](icons/sources.json)에 기록했습니다. 원본을 [icons](icons)에 함께 보관했습니다. 상표는 각 권리자의 소유입니다.

## 구성도 해석

- 파란선: 사용자·서비스 요청. 초록선: 빌드·승인 배포. 보라선: 관리·자격 증명. 주황선: 비동기 이벤트. 회색 점선: 배치·논리 연결.
- 상단 CI/CD와 하단 운영 흐름은 논리 연결입니다. VPC 안의 서브넷 그림은 네트워크 배치입니다. 같은 서비스를 두 번 생성한 뜻이 아닙니다.
- RDS 주/대기 위치는 예시이며 실제 AZ를 고정하지 않습니다. 앱 밴드는 두 노드 그룹에 배치되는 논리 구성으로 파드별 AZ를 보장하지 않습니다.
- NAT 제어기·검사기·회복 검사 서브넷을 통합 설계에 표시했습니다. 별도 AWS 시연과 통합판의 미검증 범위는 [NAT 운영 문서](../22-nat-autofailover.md)에 있습니다.

기존 이미지가 설명하던 NAT 1개·RDS Single-AZ·미구현 SQS 소비자는 현재와 다릅니다. 해당 설명은 [이전 아키텍처 원문](../archive/2026-11-04/01-architecture.md)에 보존했습니다.
