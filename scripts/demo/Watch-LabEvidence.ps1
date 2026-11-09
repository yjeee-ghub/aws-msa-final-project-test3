param(
    [ValidateSet('Deployment', 'HA')][string]$Mode = 'Deployment',
    [string]$Label = 'before',
    [ValidateRange(2, 300)][int]$IntervalSeconds = 5,
    [ValidateRange(1, 120)][int]$Minutes = 15,
    [string]$OutputDirectory,
    [switch]$Once
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$config = Get-Content -Raw -LiteralPath (Join-Path $repoRoot 'scripts/ops/environment.json') | ConvertFrom-Json
if ($Label -notmatch '^[A-Za-z0-9_-]+$') { throw 'Label: use letters, numbers, dash or underscore.' }
$outDir = if ($OutputDirectory) { $OutputDirectory } else { Join-Path $repoRoot '.lab/release-demo/evidence' }
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$jsonLog = Join-Path $outDir "$stamp-$Label.jsonl"
$textLog = Join-Path $outDir "$stamp-$Label.txt"
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Read-NativeJson([string]$Program, [string[]]$Arguments) {
    $result = & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program query failed (exit $LASTEXITCODE); not an empty inventory." }
    return (($result -join "`n") | ConvertFrom-Json)
}
function Read-Aws([string[]]$Arguments) {
    return Read-NativeJson 'aws' ($Arguments + @('--profile', $config.profile, '--region', $config.region, '--output', 'json', '--no-cli-pager'))
}
function Read-Kube([string[]]$Arguments) {
    return Read-NativeJson 'kubectl' ($Arguments + @('--context', $script:expectedContext, '--request-timeout=15s', '-o', 'json'))
}
function Emit-Table($Rows) {
    $text = $Rows | Format-Table -AutoSize -Wrap | Out-String -Width 180
    Write-Host $text
    [IO.File]::AppendAllText($textLog, $text, $utf8)
}
function Emit-Line([string]$Text) {
    Write-Host $Text
    [IO.File]::AppendAllText($textLog, $Text + [Environment]::NewLine, $utf8)
}

$identity = Read-Aws @('sts', 'get-caller-identity')
if ($identity.Account -ne $config.account) { throw 'Wrong AWS account; no observation started.' }
$expectedContext = "arn:aws:eks:$($config.region):$($config.account):cluster/$($config.cluster)"
if ($Mode -eq 'Deployment') {
    $current = & kubectl config current-context
    if ($LASTEXITCODE -ne 0 -or $current.Trim() -ne $expectedContext) { throw 'Wrong Kubernetes context.' }
}
Emit-Line 'READ-ONLY LIVE OBSERVATION. No build, apply, restart, rollback or deletion.'
Emit-Line "Account=$($identity.Account) Cluster=$($config.cluster) Stage=$Label Mode=$Mode"
Emit-Line "Logs: $jsonLog"
$deadline = (Get-Date).AddMinutes($Minutes)
do {
    $time = Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'
    Emit-Line "===== $time | $Label ====="
    $record = [ordered]@{ time = $time; label = $Label; mode = $Mode; account = $config.account }
    try {
        if ($Mode -eq 'Deployment') {
            $application = Read-Kube @('get', 'application', 'final-apps', '-n', 'argocd')
            $deploy = Read-Kube @('get', 'deployment', 'frontend-depl', '-n', $config.namespace)
            $pods = Read-Kube @('get', 'pods', '-n', $config.namespace, '-l', 'app=frontend')
            $replicasets = Read-Kube @('get', 'replicasets', '-n', $config.namespace, '-l', 'app=frontend')
            $record.application = [ordered]@{ revision = $application.status.sync.revision; sync = $application.status.sync.status; health = $application.status.health.status }
            Emit-Table ([PSCustomObject]$record.application)
            $record.deployment = [ordered]@{
                generation = $deploy.metadata.generation; observed = $deploy.status.observedGeneration
                desired = $deploy.spec.replicas; updated = $deploy.status.updatedReplicas
                ready = $deploy.status.readyReplicas; available = $deploy.status.availableReplicas
                image = $deploy.spec.template.spec.containers[0].image
            }
            Emit-Table ([PSCustomObject]$record.deployment)
            $record.pods = @($pods.items | ForEach-Object {
                $pod = $_
                [PSCustomObject]@{ Name = $pod.metadata.name; Ready = (@($pod.status.conditions | Where-Object { $_.type -eq 'Ready' -and $_.status -eq 'True' }).Count -gt 0)
                    Phase = $pod.status.phase; Deleting = [bool]$pod.metadata.deletionTimestamp
                    UID = $pod.metadata.uid; Image = $pod.spec.containers[0].image }
            })
            Emit-Table $record.pods
            $record.replicaSets = @($replicasets.items | ForEach-Object {
                [PSCustomObject]@{ Name = $_.metadata.name; Desired = $_.spec.replicas; Ready = $_.status.readyReplicas; Image = $_.spec.template.spec.containers[0].image }
            })
            Emit-Table $record.replicaSets
        } else {
            $vpc = (Read-Aws @('eks', 'describe-cluster', '--name', $config.cluster)).cluster.resourcesVpcConfig.vpcId
            $filter = "Name=vpc-id,Values=$vpc"
            $subnets = (Read-Aws @('ec2', 'describe-subnets', '--filters', $filter)).Subnets
            $nats = (Read-Aws @('ec2', 'describe-nat-gateways', '--filter', $filter)).NatGateways
            $routes = (Read-Aws @('ec2', 'describe-route-tables', '--filters', $filter)).RouteTables
            $db = (Read-Aws @('rds', 'describe-db-instances', '--db-instance-identifier', $config.database)).DBInstances[0]
            $record.nats = @($nats | Where-Object { $_.State -ne 'deleted' } | ForEach-Object {
                $nat = $_
                [PSCustomObject]@{ Nat = $nat.NatGatewayId; State = $nat.State; Subnet = $nat.SubnetId; AZ = ($subnets | Where-Object { $_.SubnetId -eq $nat.SubnetId }).AvailabilityZone }
            })
            Emit-Table $record.nats
            $record.routes = @($routes | ForEach-Object {
                $table = $_
                foreach ($route in $table.Routes) {
                    if ($route.NatGatewayId) {
                        [PSCustomObject]@{ RouteTable = $table.RouteTableId; Subnets = ($table.Associations.SubnetId -join ','); Destination = $route.DestinationCidrBlock; Nat = $route.NatGatewayId; State = $route.State }
                    }
                }
            })
            Emit-Table $record.routes
            $record.rds = [ordered]@{ DB = $db.DBInstanceIdentifier; Status = $db.DBInstanceStatus; MultiAZ = $db.MultiAZ; PrimaryAZ = $db.AvailabilityZone; StandbyAZ = $db.SecondaryAvailabilityZone; Public = $db.PubliclyAccessible }
            Emit-Table ([PSCustomObject]$record.rds)
            Emit-Line 'Inventory only. Run verify_lab.py infra for same-AZ routing checks. No failover was induced.'
        }
        $record.query = 'OK'
    } catch {
        $record.query = 'ERROR'
        $record.errorType = $_.Exception.GetType().Name
        Emit-Line "QUERY ERROR: $($record.errorType). This is not a PASS or an empty inventory."
        Write-Warning $_.Exception.Message
    }
    [IO.File]::AppendAllText($jsonLog, ($record | ConvertTo-Json -Depth 10 -Compress) + [Environment]::NewLine, $utf8)
    if ($Once) { break }
    if ((Get-Date) -lt $deadline) { Start-Sleep -Seconds $IntervalSeconds }
} while ((Get-Date) -lt $deadline)
Emit-Line 'Observation finished. Ctrl+C also stops observation only; it does not cancel deployment.'
