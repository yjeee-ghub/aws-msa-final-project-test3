param([string]$Observer, [string]$OutputDirectory, [string]$Mode)
$ErrorActionPreference = 'Stop'
function global:aws {
    $global:LASTEXITCODE = 0
    $query = $args[1]
    switch ($query) {
        'get-caller-identity' { return '{"Account":"683668078297"}' }
        'describe-cluster' { return '{"cluster":{"resourcesVpcConfig":{"vpcId":"vpc-demo"}}}' }
        'describe-subnets' { return '{"Subnets":[{"SubnetId":"pub-a","AvailabilityZone":"ap-northeast-2a"},{"SubnetId":"pub-c","AvailabilityZone":"ap-northeast-2c"}]}' }
        'describe-nat-gateways' { return '{"NatGateways":[{"NatGatewayId":"nat-a","SubnetId":"pub-a","State":"available"},{"NatGatewayId":"nat-c","SubnetId":"pub-c","State":"available"}]}' }
        'describe-route-tables' { return '{"RouteTables":[{"RouteTableId":"rt-a","Associations":[{"SubnetId":"app-a"}],"Routes":[{"NatGatewayId":"nat-a","DestinationCidrBlock":"0.0.0.0/0","State":"active"}]}]}' }
        'describe-db-instances' { return '{"DBInstances":[{"DBInstanceIdentifier":"sol-test3-db","DBInstanceStatus":"available","MultiAZ":true,"AvailabilityZone":"ap-northeast-2a","SecondaryAvailabilityZone":"ap-northeast-2c","PubliclyAccessible":false}]}' }
        default { throw "Unexpected fake AWS query: $query" }
    }
}
function global:kubectl {
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'config') { return 'arn:aws:eks:ap-northeast-2:683668078297:cluster/sol-test3-eks' }
    switch ($args[1]) {
        'application' { return '{"status":{"sync":{"revision":"abc","status":"Synced"},"health":{"status":"Healthy"}}}' }
        'deployment' { return '{"metadata":{"generation":2},"spec":{"replicas":2,"template":{"spec":{"containers":[{"image":"frontend@sha256:demo"}]}}},"status":{"observedGeneration":2,"updatedReplicas":2,"readyReplicas":2,"availableReplicas":2}}' }
        'pods' { return '{"items":[{"metadata":{"name":"frontend-new","uid":"uid-new"},"status":{"phase":"Running","conditions":[{"type":"Ready","status":"True"}]},"spec":{"containers":[{"image":"frontend@sha256:demo"}]}}]}' }
        'replicasets' { return '{"items":[{"metadata":{"name":"frontend-new"},"spec":{"replicas":2,"template":{"spec":{"containers":[{"image":"frontend@sha256:demo"}]}}},"status":{"readyReplicas":2}}]}' }
        default { throw 'Unexpected fake kubectl command' }
    }
}
& $Observer -Mode $Mode -Label offline-test -Once -OutputDirectory $OutputDirectory
