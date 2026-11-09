# 조회 전용입니다. 결과가 없어도 실패와 구분하며 삭제 명령은 포함하지 않습니다.
[CmdletBinding()]
param(
    [string]$Profile = '512-team01',
    [string]$Region = 'ap-northeast-2',
    [string]$StateBucket = 'sol-test3-tfstate-683668078297-ap-northeast-2'
)
$ErrorActionPreference = 'Stop'
$env:AWS_PAGER = ''
$script:Failures = 0
function Read-Aws([string]$Label, [string[]]$Arguments, [switch]$Retained) {
    Write-Host "`n=== $Label $(if ($Retained) { '[의도적 보관]' }) ==="
    # native stderr와 종료 코드를 직접 처리: AccessDenied를 '없음'으로 처리하지 않습니다.
    $result = & aws @Arguments --profile $Profile --region $Region --output json --no-cli-pager 2>&1
    if ($LASTEXITCODE -ne 0) {
        $script:Failures++
        Write-Warning "조회 실패: $($result -join ' ')"
        return
    }
    try { $data = ($result -join "`n") | ConvertFrom-Json } catch {
        $script:Failures++
        Write-Warning "JSON 응답 해석 실패: $Label"
        return
    }
    if ($null -eq $data -or @($data).Count -eq 0) { Write-Host '조회 성공: 해당 자원 없음' }
    else { $data | ConvertTo-Json -Depth 20 | Write-Output }
}
$identity = & aws sts get-caller-identity --profile $Profile --region $Region --output json --no-cli-pager
if ($LASTEXITCODE -ne 0) { throw 'AWS 계정 조회 실패. 이후 조회를 중단합니다.' }
if (($identity | ConvertFrom-Json).Account -ne '683668078297') { throw '프로젝트 AWS 계정과 다릅니다.' }
Read-Aws 'Project=sol-test3 태그 자원 (보조 목록, 미태그 자원은 아래 별도 조회)' @('resourcegroupstaggingapi','get-resources','--tag-filters','Key=Project,Values=sol-test3','--query','ResourceTagMappingList')
Read-Aws 'EKS 및 노드그룹 존재 여부 (클러스터가 남으면 콘솔에서 노드그룹도 확인)' @('eks','list-clusters','--query',"clusters[?@ == 'sol-test3-eks']")
Read-Aws 'RDS 본 DB와 복원 실습 DB' @('rds','describe-db-instances','--query',"DBInstances[?starts_with(DBInstanceIdentifier, 'sol-test3-')].{Id:DBInstanceIdentifier,Status:DBInstanceStatus,Endpoint:Endpoint.Address}")
Read-Aws '수동 스냅샷: 별도 보관/비용 판단 필요' @('rds','describe-db-snapshots','--snapshot-type','manual','--query',"DBSnapshots[?starts_with(DBInstanceIdentifier, 'sol-test3-')].{Id:DBSnapshotIdentifier,Status:Status,DB:DBInstanceIdentifier}") -Retained
Read-Aws 'S3 상품·CloudTrail 버킷 (객체가 남으면 destroy 실패 가능)' @('s3api','list-buckets','--query',"Buckets[?starts_with(Name, 'sol-test3-') && Name != '$StateBucket']")
Read-Aws 'S3 state 버킷: 프로젝트 destroy 대상 아님' @('s3api','list-buckets','--query',"Buckets[?Name == '$StateBucket']") -Retained
Read-Aws 'ECR 이미지 저장소' @('ecr','describe-repositories','--query',"repositories[?contains(['member-service','product-service','ordering-service','apigateway','frontend-service'], repositoryName)]")
Read-Aws 'ALB' @('elbv2','describe-load-balancers','--query',"LoadBalancers[?LoadBalancerName == 'sol-test3-alb' || starts_with(LoadBalancerName, 'k8s-soldesk') || starts_with(LoadBalancerName, 'k8s-argocd') || starts_with(LoadBalancerName, 'k8s-monitor')]")
Read-Aws '타깃 그룹 (이름 기반 후보, 다른 실습 자원인지 태그 확인)' @('elbv2','describe-target-groups','--query',"TargetGroups[?starts_with(TargetGroupName, 'k8s-soldesk') || starts_with(TargetGroupName, 'k8s-argocd') || starts_with(TargetGroupName, 'k8s-monitor')]")
Read-Aws 'EC2 (종료된 인스턴스도 잠시 표시)' @('ec2','describe-instances','--query',"Reservations[].Instances[] | [?Tags[?(Key == 'Project' && Value == 'sol-test3') || (Key == 'eks:cluster-name' && Value == 'sol-test3-eks') || Key == 'kubernetes.io/cluster/sol-test3-eks']].{Id:InstanceId,State:State.Name,Vpc:VpcId}")
Read-Aws 'ASG (EKS 생성 이름과 프로젝트 태그)' @('autoscaling','describe-auto-scaling-groups','--query',"AutoScalingGroups[?contains(AutoScalingGroupName, 'sol-test3') || Tags[?Key == 'Project' && Value == 'sol-test3']]")
Read-Aws 'EBS (프로젝트 태그 또는 CSI 후보: 다른 클러스터 자원과 대조 필요)' @('ec2','describe-volumes','--query',"Volumes[?Tags[?(Key == 'Project' && Value == 'sol-test3') || (Key == 'kubernetes.io/cluster/sol-test3-eks') || (Key == 'ebs.csi.aws.com/cluster' && Value == 'true')]]")
Read-Aws 'EIP (NAT 잔여 포함, Project 태그)' @('ec2','describe-addresses','--filters','Name=tag:Project,Values=Final','--query','Addresses')
# VPC 안의 미태그 ENI/SG 등도 확인하려고 VPC ID를 먼저 수집합니다.
$vpcResult = & aws ec2 describe-vpcs --profile $Profile --region $Region --output json --no-cli-pager 2>&1
if ($LASTEXITCODE -ne 0) { $script:Failures++; Write-Warning "VPC 조회 실패: $vpcResult" }
else {
    $vpcs = (($vpcResult -join "`n") | ConvertFrom-Json).Vpcs | Where-Object {
        @($_.Tags | Where-Object { ($_.Key -eq 'Project' -and $_.Value -eq 'sol-test3') -or ($_.Key -eq 'Name' -and $_.Value -eq 'sol-test3-VPC') }).Count -gt 0
    }
    if (-not $vpcs) { Write-Host '조회 성공: 프로젝트 VPC 없음' }
    foreach ($vpc in $vpcs) {
        $id = $vpc.VpcId
        Write-Host "`n프로젝트 VPC: $id"
        foreach ($entry in @(
            @('ENI','describe-network-interfaces','NetworkInterfaces'),
            @('SG','describe-security-groups','SecurityGroups'),
            @('Subnet','describe-subnets','Subnets'),
            @('RouteTable','describe-route-tables','RouteTables'),
            @('VPC Endpoint','describe-vpc-endpoints','VpcEndpoints'),
            @('NAT Gateway','describe-nat-gateways','NatGateways')
        )) {
            $filterOption = if ($entry[1] -eq 'describe-nat-gateways') { '--filter' } else { '--filters' }
            Read-Aws "$id $($entry[0])" @('ec2',$entry[1],$filterOption,"Name=vpc-id,Values=$id",'--query',$entry[2])
        }
        Read-Aws "$id IGW" @('ec2','describe-internet-gateways','--filters',"Name=attachment.vpc-id,Values=$id",'--query','InternetGateways')
    }
}
Read-Aws 'IAM 프로젝트 역할 (IRSA/CI 포함)' @('iam','list-roles','--query',"Roles[?starts_with(RoleName, 'sol-test3')].{Name:RoleName,Arn:Arn}")
Read-Aws 'IAM 프로젝트 정책' @('iam','list-policies','--scope','Local','--query',"Policies[?starts_with(PolicyName, 'sol-test3')].{Name:PolicyName,Arn:Arn}")
Read-Aws 'OIDC 공급자 후보: 다른 클러스터도 포함하므로 ARN 비교 필요' @('iam','list-open-id-connect-providers','--query','OpenIDConnectProviderList')
Read-Aws 'CloudWatch EKS 로그' @('logs','describe-log-groups','--log-group-name-prefix','/aws/eks/sol-test3-eks/','--query','logGroups')
Read-Aws 'CloudWatch 프로젝트 알람' @('cloudwatch','describe-alarms','--query',"MetricAlarms[?starts_with(AlarmName, 'sol-test3')]")
Read-Aws 'SNS 프로젝트 토픽' @('sns','list-topics','--query',"Topics[?contains(TopicArn, ':sol-test3-')]")
Read-Aws 'SQS 프로젝트 큐' @('sqs','list-queues','--queue-name-prefix','sol-test3-','--query','QueueUrls')
Read-Aws 'CloudTrail' @('cloudtrail','describe-trails','--query',"trailList[?starts_with(Name, 'sol-test3-')]")
Read-Aws 'ACM 프로젝트 도메인 인증서' @('acm','list-certificates','--query',"CertificateSummaryList[?DomainName == 'server.aws-yjeee.com' || DomainName == 'argocd.aws-yjeee.com']")
Read-Aws '주문 이메일 Lambda' @('lambda','list-functions','--query',"Functions[?FunctionName == 'sol-test3-order-email'].{Name:FunctionName,State:State}")
Read-Aws '주문 이메일 Lambda 로그' @('logs','describe-log-groups','--log-group-name-prefix','/aws/lambda/sol-test3-order-email','--query','logGroups')
Read-Aws '이메일 중복 처리 DynamoDB' @('dynamodb','list-tables','--query',"TableNames[?@ == 'sol-test3-order-email-dedup']")
Read-Aws '프로젝트/RDS 비밀값 후보 (예약 삭제 포함)' @('secretsmanager','list-secrets','--include-planned-deletion','--query',"SecretList[?starts_with(Name, 'sol-test3') || Tags[?(Key == 'Project' && Value == 'sol-test3') || (Key == 'aws:rds:primaryDBInstanceArn' && contains(Value, ':db:sol-test3-ordermsa-db'))]].{Name:Name,Arn:ARN,Deleted:DeletedDate}")
Write-Host 'SES 기존 인증 ID는 계정 공유 자원일 수 있어 자동 삭제 대상이 아닙니다. manage_ses_identities=true로 만든 전용 ID만 별도로 대조하세요.'
Read-Aws '기존 Route53 호스팅 영역: 삭제하지 않음' @('route53','get-hosted-zone','--id','Z0423440PXYPZGKLZVJ7','--query','HostedZone') -Retained
Read-Aws 'Route53 프로젝트 레코드 후보' @('route53','list-resource-record-sets','--hosted-zone-id','Z0423440PXYPZGKLZVJ7','--query',"ResourceRecordSets[?contains(Name, 'server.aws-yjeee.com') || contains(Name, 'argocd.aws-yjeee.com') || contains(Name, 'grafana.aws-yjeee.com')]")
Write-Host "`n완료: 조회 실패 $script:Failures 건. 목록은 지정 리전·태그·이름 기반 후보이며 무잔여를 보장하지 않습니다."
if ($script:Failures -gt 0) { exit 1 }
