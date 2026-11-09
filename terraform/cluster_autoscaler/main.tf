# 이 모듈에서 사용할 AWS Provider
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

locals {
  # IAM 조건 키에서는 URL의 https:// 부분을 제외
  oidc_provider_host = trimprefix(var.oidc_issuer_url, "https://")
}

# Cluster Autoscaler Pod가 사용할 전용 IAM 역할
resource "aws_iam_role" "main" {
  name = "${var.project_name}-cluster-autoscaler-role"

  # 지정한 ServiceAccount의 토큰만 역할 사용 허용
  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Federated = var.oidc_provider_arn
        }

        Action = "sts:AssumeRoleWithWebIdentity"

        Condition = {
          StringEquals = {
            # 토큰의 사용 대상이 AWS STS인지 확인
            "${local.oidc_provider_host}:aud" = "sts.amazonaws.com"

            # kube-system의 cluster-autoscaler만 역할 사용 허용
            "${local.oidc_provider_host}:sub" = "system:serviceaccount:kube-system:cluster-autoscaler"
          }
        }
      }
    ]
  })
}

# 노드그룹 조회와 확장·축소에 필요한 권한
resource "aws_iam_policy" "main" {
  name = "${var.project_name}-cluster-autoscaler-policy"

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "ReadNodeGroupInformation"
        Effect = "Allow"

        # 노드 배치 가능 여부 판단에 필요한 정보 조회
        Action = [
          "autoscaling:DescribeAutoScalingGroups",
          "autoscaling:DescribeAutoScalingInstances",
          "autoscaling:DescribeLaunchConfigurations",
          "autoscaling:DescribeScalingActivities",
          "autoscaling:DescribeTags",
          "ec2:DescribeImages",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeLaunchTemplateVersions",
          "ec2:GetInstanceTypesFromInstanceRequirements",
          "eks:DescribeNodegroup",
        ]

        # 여러 조회 API는 개별 리소스 ARN 제한을 지원하지 않음
        Resource = "*"
      },
      {
        Sid    = "ScaleOnlyThisCluster"
        Effect = "Allow"

        # 원하는 노드 수 변경과 축소 대상 인스턴스 종료
        Action = [
          "autoscaling:SetDesiredCapacity",
          "autoscaling:TerminateInstanceInAutoScalingGroup",
        ]

        Resource = "*"

        # 아래 태그를 모두 가진 ASG에만 변경 권한 허용
        Condition = {
          StringEquals = {
            "aws:ResourceTag/k8s.io/cluster-autoscaler/enabled"             = "true"
            "aws:ResourceTag/k8s.io/cluster-autoscaler/${var.cluster_name}" = "owned"
          }
        }
      }
    ]
  })
}

# CA 역할에 위 정책 연결
resource "aws_iam_role_policy_attachment" "main" {
  role       = aws_iam_role.main.name
  policy_arn = aws_iam_policy.main.arn
}
