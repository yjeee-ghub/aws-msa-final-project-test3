# 모니터링 데이터 저장용 EBS 볼륨 생성 규칙
resource "kubernetes_storage_class_v1" "gp3" {
  metadata {
    name = "final-gp3"
  }

  # 기존 AWS Terraform에서 설치하는 EBS CSI Driver 사용
  storage_provisioner = "ebs.csi.aws.com"

  parameters = {
    # gp3 유형의 암호화된 EBS 볼륨 생성
    type      = "gp3"
    encrypted = "true"
  }

  # 파드가 배치될 AZ를 확인한 뒤 같은 AZ에 EBS 생성
  volume_binding_mode = "WaitForFirstConsumer"

  # PVC 용량을 늘려 볼륨 확장 가능
  allow_volume_expansion = true

  # PVC 삭제 시 연결된 볼륨도 삭제하는 실습용 정책
  reclaim_policy = "Delete"
}
