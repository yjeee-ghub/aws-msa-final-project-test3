# RDS의 지속적인 CPU 과부하 감시
resource "aws_cloudwatch_metric_alarm" "rds_cpu_high" {
  alarm_name        = "${var.project_name}-rds-cpu-high"
  alarm_description = "RDS CPU average is at least 80 percent"

  namespace   = "AWS/RDS"
  metric_name = "CPUUtilization"
  statistic   = "Average"

  # 5분 평균을 평가하고, 3회 연속 초과 시 경보
  period              = 300
  evaluation_periods  = 3
  datapoints_to_alarm = 3

  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 80

  dimensions = {
    DBInstanceIdentifier = var.db_instance_identifier
  }

  # 지표 누락만으로 경보를 발생시키지 않음: 서비스 장애 탐지를 대체하지 않음
  treat_missing_data = "notBreaching"

  # 경보가 ALARM 상태로 전환되면 운영 SNS에 발행
  alarm_actions = [aws_sns_topic.operations_alerts.arn]

  depends_on = [
    aws_sns_topic_policy.operations_alerts
  ]
}

# RDS의 남은 저장 공간 감시
resource "aws_cloudwatch_metric_alarm" "rds_storage_low" {
  alarm_name        = "${var.project_name}-rds-storage-low"
  alarm_description = "RDS free storage is at most 2 GiB"

  namespace   = "AWS/RDS"
  metric_name = "FreeStorageSpace"
  statistic   = "Minimum"

  # 5분 구간 최솟값을 평가하고, 2회 연속 조건 충족 시 경보
  period              = 300
  evaluation_periods  = 2
  datapoints_to_alarm = 2

  comparison_operator = "LessThanOrEqualToThreshold"

  # FreeStorageSpace는 Bytes 단위: 2 GiB
  threshold = 2 * 1024 * 1024 * 1024

  dimensions = {
    DBInstanceIdentifier = var.db_instance_identifier
  }

  # 지표 누락만으로 경보를 발생시키지 않음: 서비스 장애 탐지를 대체하지 않음
  treat_missing_data = "notBreaching"

  # 경보가 ALARM 상태로 전환되면 운영 SNS에 발행
  alarm_actions = [aws_sns_topic.operations_alerts.arn]

  depends_on = [
    aws_sns_topic_policy.operations_alerts
  ]
}
