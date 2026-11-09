# EKS에서 서울 리전 S3로 직접 통신하는 경로
resource "aws_vpc_endpoint" "s3" {
  vpc_id = aws_vpc.main.id

  service_name      = "com.amazonaws.ap-northeast-2.s3"
  vpc_endpoint_type = "Gateway"

  # EKS용 프라이빗 라우팅 테이블 두 개에 연결
  route_table_ids = aws_route_table.private[*].id

  tags = {
    Name = "${var.vpc_name}-s3-endpoint"
  }
}
