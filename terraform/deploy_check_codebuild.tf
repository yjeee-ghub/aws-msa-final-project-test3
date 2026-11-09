locals {
  deploy_verify_name = local.environment.verifyProject
}

resource "aws_s3_bucket" "deploy_verify" {
  bucket = local.environment.verifyBucket
}

resource "aws_s3_bucket_public_access_block" "deploy_verify" {
  bucket                  = aws_s3_bucket.deploy_verify.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "deploy_verify" {
  bucket = aws_s3_bucket.deploy_verify.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "deploy_verify" {
  bucket = aws_s3_bucket.deploy_verify.id
  rule {
    id     = "expire-verification-inputs"
    status = "Enabled"
    filter { prefix = "sources/" }
    expiration { days = 7 }
  }
}

resource "aws_cloudwatch_log_group" "deploy_verify" {
  name              = "/aws/codebuild/${local.deploy_verify_name}"
  retention_in_days = 7
}

resource "aws_security_group" "deploy_verify" {
  name        = local.deploy_verify_name
  description = "Outbound HTTPS for private deployment verification"
  vpc_id      = module.network.vpc_id
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_vpc_security_group_ingress_rule" "deploy_verify_api" {
  security_group_id            = module.eks.cluster_security_group_id
  referenced_security_group_id = aws_security_group.deploy_verify.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
  description                  = "CodeBuild to private EKS API"
}

resource "aws_iam_role" "deploy_verify" {
  name = "${local.deploy_verify_name}-codebuild"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "codebuild.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = {
      StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id },
      ArnEquals    = { "aws:SourceArn" = "arn:aws:codebuild:${local.environment.region}:${data.aws_caller_identity.current.account_id}:project/${local.deploy_verify_name}" }
    }
  }] })
}

resource "aws_iam_role_policy" "deploy_verify" {
  role = aws_iam_role.deploy_verify.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["eks:DescribeCluster"], Resource = module.eks.cluster_arn },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = "${aws_s3_bucket.deploy_verify.arn}/sources/*" },
    { Effect = "Allow", Action = ["s3:GetBucketLocation", "s3:GetBucketAcl"], Resource = aws_s3_bucket.deploy_verify.arn },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.deploy_verify.arn}:*" },
    {
      Effect = "Allow", Action = [
        "ec2:CreateNetworkInterface", "ec2:DeleteNetworkInterface", "ec2:DescribeNetworkInterfaces",
        "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups", "ec2:DescribeDhcpOptions", "ec2:DescribeVpcs"
      ], Resource = "*"
    },
    {
      Effect   = "Allow", Action = "ec2:CreateNetworkInterfacePermission",
      Resource = "arn:aws:ec2:${local.environment.region}:${data.aws_caller_identity.current.account_id}:network-interface/*",
      Condition = { StringEquals = {
        "ec2:AuthorizedService" = "codebuild.amazonaws.com",
        "ec2:Subnet"            = [for id in module.network.private_subnet_ids : "arn:aws:ec2:${local.environment.region}:${data.aws_caller_identity.current.account_id}:subnet/${id}"]
      } }
    }
  ] })
}

resource "aws_eks_access_entry" "deploy_verify" {
  cluster_name      = module.eks.cluster_name
  principal_arn     = aws_iam_role.deploy_verify.arn
  kubernetes_groups = ["final-deploy-readers"]
  type              = "STANDARD"
}

resource "aws_codebuild_project" "deploy_verify" {
  name                   = local.deploy_verify_name
  service_role           = aws_iam_role.deploy_verify.arn
  build_timeout          = 15
  queued_timeout         = 10
  concurrent_build_limit = 1
  artifacts { type = "NO_ARTIFACTS" }
  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/standard:7.0"
    type                        = "LINUX_CONTAINER"
    privileged_mode             = false
    image_pull_credentials_type = "CODEBUILD"
  }
  source {
    type     = "S3"
    location = "${aws_s3_bucket.deploy_verify.id}/sources/pending.zip"
    buildspec = yamlencode({
      version = "0.2"
      phases = {
        install = {
          "runtime-versions" = { python = "3.12" }
          commands = [
            "curl --fail --silent --show-error --retry 3 -o /tmp/kubectl https://dl.k8s.io/release/v1.35.0/bin/linux/amd64/kubectl",
            "curl --fail --silent --show-error --retry 3 -o /tmp/kubectl.sha256 https://dl.k8s.io/release/v1.35.0/bin/linux/amd64/kubectl.sha256",
            "echo \"$(cat /tmp/kubectl.sha256)  /tmp/kubectl\" | sha256sum --check",
            "install -m 0755 /tmp/kubectl /usr/local/bin/kubectl",
            "python3 -m pip install PyYAML==6.0.3"
          ]
        }
        build = { commands = [
          "aws eks update-kubeconfig --region ${local.environment.region} --name ${module.eks.cluster_name}",
          "kubectl --request-timeout=15s get application final-apps -n argocd -o name",
          "python3 -u scripts/ops/check_release.py --revision \"$REVISION\" --url ${local.environment.url}"
        ] }
      }
    })
  }
  vpc_config {
    vpc_id             = module.network.vpc_id
    subnets            = module.network.private_subnet_ids
    security_group_ids = [aws_security_group.deploy_verify.id]
  }
  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.deploy_verify.name
    }
  }
  depends_on = [aws_iam_role_policy.deploy_verify, aws_eks_access_entry.deploy_verify, aws_vpc_security_group_ingress_rule.deploy_verify_api]
}

# GitHub can submit sources and start this verifier; Kubernetes access stays in CodeBuild.
resource "aws_iam_role_policy" "deploy_check_codebuild" {
  role = aws_iam_role.deploy_check.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = "s3:PutObject", Resource = "${aws_s3_bucket.deploy_verify.arn}/sources/*" },
    { Effect = "Allow", Action = "codebuild:StartBuild", Resource = aws_codebuild_project.deploy_verify.arn },
    { Effect = "Allow", Action = ["codebuild:BatchGetBuilds", "codebuild:StopBuild"], Resource = aws_codebuild_project.deploy_verify.arn },
    { Effect = "Allow", Action = "logs:GetLogEvents", Resource = "${aws_cloudwatch_log_group.deploy_verify.arn}:*" }
  ] })
}

output "deploy_verify_project" { value = aws_codebuild_project.deploy_verify.name }
output "deploy_verify_source_bucket" { value = aws_s3_bucket.deploy_verify.id }

# Only TLS is accepted for source bundles; the bucket is never public.
resource "aws_s3_bucket_policy" "deploy_verify" {
  bucket = aws_s3_bucket.deploy_verify.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid       = "DenyInsecureTransport", Effect = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.deploy_verify.arn, "${aws_s3_bucket.deploy_verify.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
