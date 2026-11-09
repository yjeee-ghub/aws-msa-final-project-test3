#!/usr/bin/env bash
# AWS와 운영 DB 없이 실행 가능한 기존 테스트를 이미지 게시 전에 수행합니다.
set -euo pipefail
cd "$(dirname "$0")/../.."
service=${1:?서비스 이름 필요}
case "$service" in
  frontend) node --test app/msa/frontend/tests/*.test.cjs; exit ;;
  member) tests=(--tests '*AdminAccessTest' --tests '*AdminDashboardAccessTest' --tests '*AdminDashboardServiceTest' --tests '*HealthGroupsTest' --tests '*InternalMemberAccessTest') ;;
  product) tests=(--tests '*StockConcurrencyTest' --tests '*ReservationWorkflowTest') ;;
  ordering) tests=(--tests '*OrderFeaturesTest') ;;
  apigateway)
    # 테스트 전용 임의 키이며 외부 서비스나 배포에 사용하지 않습니다.
    export JWT_SECRET=$(python3 -c 'import secrets,base64; print(base64.b64encode(secrets.token_bytes(64)).decode())')
    tests=() ;;
  *) echo "알 수 없는 서비스: $service" >&2; exit 1 ;;
esac
cd "app/msa/$service"
bash gradlew --no-daemon --max-workers=2 test "${tests[@]}" bootJar
