> **과거 문서 보존본** · 2026-11-04 최신화 전 main `cc040cf`의 원문입니다. 현재 실행 안내가 아닙니다. [현재 README](../../../README.md)와 [검증 범위](../../21-current-validation.md)를 사용하세요.

# 배포 자동화

배포는 수정한 앱을 실제 서버에서 실행할 수 있게 반영하는 과정이다. 처음에는 이미지를 직접 올렸지만, 이후에는 GitHub에 코드를 올리면 EKS까지 반영되도록 연결했다.

## 코드가 홈페이지에 반영되는 과정

```text
코드 수정 → GitHub push
  → GitHub Actions가 관련 서비스 테스트·이미지 빌드
  → ECR에 이미지 업로드
  → Git의 이미지 태그 변경
  → Argo CD가 확인
  → EKS에서 새 버전 실행
```

**Docker 이미지**는 앱 실행에 필요한 파일과 환경을 묶은 것이다. **ECR**은 이 이미지를 보관하는 AWS 저장소다.

**GitHub Actions**는 GitHub에서 정해둔 작업을 자동 실행하는 도구다. 이번에는 앱 이미지 빌드·업로드와 배포 태그 변경을 맡겼다.

**Argo CD**는 Git의 배포 설정과 Kubernetes의 실제 상태를 비교해 맞추는 도구다. Git에 새 이미지 태그가 올라오면 그 버전을 실행하도록 반영한다.

## Helm — 여러 설치 파일을 묶어서 설치

Prometheus나 Grafana를 Kubernetes에 설치하려면 실행·통신·저장 공간 등에 필요한 여러 설정이 있어야 한다.

Helm은 이런 파일을 **Chart라는 설치 패키지**로 묶어서 사용하게 해준다. 내 프로젝트에서는 Prometheus·Grafana·Argo CD 같은 운영 도구를 설치할 때 사용했다.

```text
Terraform → Helm Chart + 설정값 → EKS에 운영 도구 설치
```

예를 들어 Grafana의 저장 공간이나 Prometheus의 메모리를 설정값으로 전달했다. 설치만 하는 게 아니라 이후 설정을 갱신할 때도 사용한다.

## Kustomize — 앱 배포 목록과 이미지 버전 관리

Kubernetes에는 어떤 앱을 몇 개 실행하고 어떤 이미지로 띄울지 적은 설정 파일이 필요하다.

Kustomize는 **사용할 배포 파일을 모으고 이미지 태그 같은 값을 지정**하는 도구다. `app/msa/kustomization.yaml`에서 회원·상품·주문 등의 배포 목록과 이미지 태그를 관리한다.

Helm은 주로 운영 도구 설치에, Kustomize는 내가 만든 앱의 배포 설정 관리에 사용했다.

## 이미지 태그는 버전을 구분하는 이름

같은 서비스라도 수정 전·후의 이미지가 다르다. 어떤 이미지를 실행할지 구분하는 이름이 **태그**다.

이번에는 Git 커밋 값으로 태그를 만들었다. 코드 변경을 저장한 기록과 이미지를 연결해서 확인하기 위해서다.

현재 태그는 Kustomize 파일에 있고, 차수별 기록은 [배포 이력](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/RELEASES.md)에 정리했다. 이전 이미지로 돌아가는 과정은 [롤백 안내](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/ROLLBACK.md)에서 볼 수 있다.

## 직접 확인한 내용

프런트엔드 수정부터 관리자 대시보드 추가까지 같은 흐름으로 배포했다. Actions 성공, 이미지 태그 변경, 파드 교체, 실제 화면 변경을 확인했다.

**롤링 업데이트**는 실행 중인 파드를 새 버전으로 조금씩 교체하는 방식이다. 프런트엔드는 새 파드가 준비된 뒤 기존 파드를 종료하도록 설정했다. 이 설정만으로 모든 상황에서 무중단이 보장되는 것은 아니므로 접속 결과도 함께 확인했다.

AWS 인증에는 GitHub Actions용 OIDC와 앱용 ServiceAccount 연결 IAM 역할을 사용했다. 필요한 권한을 역할로 받아 사용하도록 구성한 것이다.

다시 구축할 때는 AWS 인프라, 이미지·Secret과 EKS 내부 도구, 앱 배포, ALB 확인 후 DNS 연결 순으로 진행한다. **Secret은 비밀번호처럼 앱에 필요한 값을 Kubernetes에 전달하는 리소스**다.

[앱 기능 설정 절차](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/app/msa/APP-FEATURES.md)


## 변경한 서비스만 테스트·빌드

회원 서비스 코드만 바뀌었다면 회원 이미지만 다시 만들도록 개선했다. 여러 서비스가 함께 사용하는 파일이나 CI 설정이 바뀌면 필요한 검증이 빠지지 않도록 전체를 대상으로 한다. 배포 파일이나 문서만 바뀌면 이미지 빌드는 생략한다.

```text
변경 경로 확인 → 관련 서비스 테스트 → 이미지 빌드·게시
  → 해당 서비스의 이미지 태그만 변경 → Argo CD 반영
```

선택한 서비스의 테스트가 모두 성공해야 이미지를 게시한다. 수동 전체 빌드도 남겨두어 처음 구축할 때 사용할 수 있다. 테스트 대상에는 관리자 접근 제한, 재고 동시 처리, 주문 검증, 프런트엔드 장바구니 등이 포함된다.

GitHub Actions의 게시와 AWS 인증은 main에서만 수행한다. main 병합 전 PR에서는 검증만 진행한다. 현재 test는 개선 전 main 보관용이며, 별도 검증 환경은 최신 main에서 새 브랜치를 만들어 이미지 게시와 Argo 대상을 지정한다.

## 파드를 두 개 띄우는 것과 종료 순서

프런트엔드는 두 파드를 다른 노드에 배치했다. **PDB는 노드 점검처럼 파드를 자발적으로 내릴 때 최소한의 파드를 남기도록 제한하는 설정**이다. 실제로 첫 파드 축출은 허용하고 두 번째 동시 축출은 막는지 확인했다.

파드가 너무 빨리 종료되면 ALB가 대상 변경을 반영하는 중 요청이 실패할 수 있었다. 종료 전 대기를 추가하고 같은 실습에서 접속을 다시 확인했다. 파드 수와 종료 순서를 함께 고려해야 했다.

## 정상 상태를 확인하는 세 가지 점검

| 점검 | 확인하는 내용 |
| --- | --- |
| startupProbe | 앱이 처음 실행될 시간을 기다림 |
| readinessProbe | 지금 요청을 받을 준비가 됐는지 확인 |
| livenessProbe | 앱 자체가 정상적으로 살아 있는지 확인 |

DB 연결 문제가 생겼다는 이유만으로 앱을 계속 재시작하지 않도록 readiness와 liveness를 나눴다. 배포 후에는 HTTPS 화면과 공개 상품 API까지 확인한다. [실제 적용·검증](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/10-live-validation.md)에 확인 범위를 정리했다.

---

[프로젝트 홈](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/README.md) · [이전: 프로젝트 구성](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/01-architecture.md) · [다음: 모니터링과 실습 결과](https://github.com/yobi84-sy/aws-msa-final-test2/blob/cc040cf5d8f621d19d3851aa1a59ae2229815e53/docs/03-monitoring-and-tests.md)
