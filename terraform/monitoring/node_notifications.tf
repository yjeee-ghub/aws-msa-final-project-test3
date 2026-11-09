# 이전 통합 알림은 상태에서만 해제한다. 기존 AWS 알림은 아래 그룹별 리소스가 이어서 관리한다.
# 이미 삭제된 ASG에 DeleteNotificationConfiguration을 호출하지 않도록 한다.
removed {
  from = aws_autoscaling_notification.eks_nodes

  lifecycle {
    destroy = false
  }
}

# 그룹별로 관리하여 노드그룹 제거 전에 해당 그룹의 알림부터 제거한다.
resource "aws_autoscaling_notification" "node_groups" {
  for_each = var.node_group_asgs

  # PutNotificationConfiguration은 기존 설정을 갱신하므로 중복 구독을 만들지 않는다.
  group_names = [each.value]

  # EC2 시작과 종료 및 각 작업의 실패 이벤트 구독
  notifications = [
    "autoscaling:EC2_INSTANCE_LAUNCH",
    "autoscaling:EC2_INSTANCE_TERMINATE",
    "autoscaling:EC2_INSTANCE_LAUNCH_ERROR",
    "autoscaling:EC2_INSTANCE_TERMINATE_ERROR",
  ]

  topic_arn = aws_sns_topic.operations_alerts.arn

  depends_on = [
    aws_sns_topic_policy.operations_alerts,
  ]
}
