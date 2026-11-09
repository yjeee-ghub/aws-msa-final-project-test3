> **과거 기록의 적용 범위** · 아래는 당시 코드·계정·브랜치·준비 상태를 보존한 원문입니다. 현재 main의 실행 안내는 [README](../README.md), 실제 완료 범위는 [최신 검증 정리](21-current-validation.md)를 사용하세요. “미실행/예정”은 작성 당시 기준입니다.

# 최초 이미지 게시 후 테스트가 실패한 이유

## 발생 시점과 영향

최초 배포 전에는 18개 Python 테스트가 통과했다. 5개 앱의 테스트, Docker 빌드와 ECR 게시도 성공했다. 이후 배포 PR에서 실제 `app/msa/kustomization.yaml`에 이미지 digest가 추가되자 기존 테스트 2개가 실패했다.

- 실패 실행: https://github.com/yobi84-sy/aws-msa-final-test2/actions/runs/39215953425
- 성공한 이미지 빌드·게시: https://github.com/yobi84-sy/aws-msa-final-test2/actions/runs/39215115059

digest는 이미지 내용의 식별값이다. 배포 파일에 이를 고정하는 동작은 정상이며, 문제는 테스트가 변경되는 실제 배포 파일을 고정된 샘플처럼 사용한 데 있었다.

## 실패 원인

### 선택한 이미지 태그만 바꾸는 검사

`test_update_only_selected_images`는 두 서비스의 태그를 바꾸면 파일의 줄 차이가 정확히 2개라고 가정했다. 초기 파일에는 digest가 없어 이 가정이 맞았다. 게시 후 파일에서는 선택한 이미지의 이전 digest도 제거되므로 줄 수와 줄 위치가 달라졌고 `13 != 2`로 실패했다.

### 이전 digest를 제거하는 검사

`test_tag_update_does_not_keep_previous_digest`는 frontend를 바꾼 뒤 파일 전체에 `digest:`가 없다고 검사했다. 초기 입력에서는 frontend에만 테스트용 digest를 추가하므로 맞는 검사였다. 실제 배포 파일에는 다른 네 서비스에도 digest가 있으므로 frontend의 digest를 정상 제거해도 검사가 실패했다. 다른 서비스의 digest는 유지되는 것이 맞다.

## 수정한 내용과 이유

`tests/fixtures/image-tags.yaml`에 digest가 없는 고정 샘플을 추가하고 위 두 테스트의 입력 경로만 이 파일로 변경했다. assertion은 제거하거나 완화하지 않았다. 배포 파일이 갱신되어도 두 테스트가 원래 의도한 입력 조건을 안정적으로 사용하게 했다.

앱 코드, 이미지 게시·태그 갱신 로직, 실제 배포 파일의 digest 고정 방식은 수정하지 않았다. 기존의 다른 digest 고정/재고정 검사는 실제 배포 파일을 사용하는 방식으로 유지했다. 이번 변경은 태그 갱신 함수의 모든 조합을 새로 검증하는 확장은 아니며, 최초 게시 이후 잘못 실패하던 두 테스트의 입력 의존성만 분리한다.

## 별도로 확인한 설치 순서 문제

최초 Terraform Kubernetes apply에서는 ALB Controller와 External Secrets를 동시에 설치했다. ALB Service webhook이 등록된 직후 실제 endpoint가 준비되기 전에 External Secrets의 Service 생성 요청이 도착해 설치가 실패했다. ALB Controller가 Ready인 것을 확인하고 기존 실패 Helm release를 Terraform 상태에 import한 뒤 재적용하여 해결했다. 이 순서 문제의 코드 수정은 이번 테스트 변경에 포함하지 않았다.
