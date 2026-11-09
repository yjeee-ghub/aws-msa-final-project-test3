> **이전 실행/장애 기록 보관용입니다.** 현재 2차 구축은 [새 실행 가이드](../docs/14-second-build.md)를 사용하세요. 여기의 과거 계정·도메인·small 노드 수치는 현재 실행값이 아닙니다.

# Grafana 배치 장애 재발 가능성을 줄이는 AZ별 노드그룹 전환

## 원인과 변경

노드 장애 후 높은 우선순위의 Cluster Autoscaler(CA)가 2c로 이동하며 Grafana를 선점했다. Grafana의 EBS는 2c에 있어서 2a의 새 노드에서는 실행할 수 없었다. 다중 AZ ASG를 늘려도 필요한 AZ의 노드가 생성된다는 보장이 없었다.

새 구성은 t3.small을 유지한다.

| 그룹 | AZ | 최소/초기 | 최대 | 배치할 주요 파드 |
|---|---|---:|---:|---|
| Final-eks-az-a | ap-northeast-2a | 2 | 2 | CA, 기존 2a EBS의 Alertmanager |
| Final-eks-az-c | ap-northeast-2c | 2 | 3 | Grafana, Prometheus |

Grafana와 Prometheus에는 서로 같은 호스트에 배치하지 않는 필수 anti-affinity를 설정했다. Prometheus 차트의 기본 podAntiAffinity는 사용자 규칙을 덮어쓰므로 전환 시 비활성화한다. CA는 새 두 ASG만 관리하고 기존 다중 AZ ASG를 다시 확장하지 않는다. 노드 수 범위는 terraform/eks.tf의 node_pools에 정의되어 있으며 기존 eks_node_*_size 변수는 전환 중 기존 그룹에만 사용한다.

이 변경은 이번 선점/잘못된 AZ 확장 문제를 줄이기 위한 것으로, 단일 Grafana 파드·단일 AZ EBS의 무중단이나 AZ 전체 장애 복구를 보장하지 않는다. 그래도 올바른 AZ에 대체 노드를 생성하고 필요한 배치 공간을 확보할 수 있도록 개선한다.

## 단계 1: 기존 그룹을 유지하고 새 그룹 생성

C:\aws-msa-backend-terraform\terraform\terraform.tfvars:

```hcl
# 전환 중에만 true. 기존 그룹을 먼저 삭제하지 않는다.
keep_legacy_node_group = true
```

기존 DB 비밀번호 환경 변수가 설정된 PowerShell에서:

```powershell
cd C:\aws-msa-backend-terraform\terraform
terraform validate
terraform plan "-out=zonal-prepare.tfplan"
terraform apply "zonal-prepare.tfplan"
kubectl get nodes -L eks.amazonaws.com/nodegroup,final-node-pool,topology.kubernetes.io/zone
```

검증 당시 Plan은 2 add / 1 change / 0 destroy였다. moved 블록은 기존 main을 main[0]으로 상태 주소만 옮기며 기존 노드그룹을 교체하지 않는다. 새 두 그룹이 각각 Ready 2개인 것을 확인한다. 기존 5개와 새 4개가 잠시 함께 실행되어 최대 9개에 대한 EC2/EBS 비용이 발생할 수 있다. 이 단계에서는 기존 그룹을 유지하므로 최종 5개 제한과 다르다.

DB 비밀번호가 없는 새 PowerShell에서는 먼저 C:\aws-msa-backend-terraform\terraform-k8s\Prepare-Secrets.ps1을 실행한다. 토큰/비밀번호는 채팅이나 파일에 적지 않는다.

## 단계 2: Kubernetes 설정 적용

AWS 출력 autoscaler_node_groups가 생성된 후에만 진행한다.

```powershell
cd C:\aws-msa-backend-terraform\terraform-k8s
.\Prepare-Secrets.ps1
terraform validate
terraform plan "-out=zonal-k8s.tfplan"
terraform apply "zonal-k8s.tfplan"
kubectl get pods -n monitoring -o wide
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-cluster-autoscaler -o wide
kubectl get nodes -L final-node-pool
```

예상 변경은 Helm CA/monitoring 2개이다. 모니터링 파드가 재생성되고 같은 AZ의 기존 EBS를 새 노드에 연결하므로 관리 화면이 잠시 중단될 수 있다. PVC/PV/S3/RDS는 삭제하지 않는다. Grafana와 Prometheus가 서로 다른 az-c 노드에서 Ready이고 Alertmanager/CA가 az-a에 있는지 확인한다. 현재 grafana.syong.store/api/health의 database=ok, Prometheus Ready를 확인한 뒤 다음으로 간다.

## 단계 3: 기존 노드에서 파드 이동 후 기존 그룹 제거

새 노드와 모니터링이 모두 정상일 때 수행한다. 기존 그룹 이름은 Final-eks-nodes이며 새 그룹 이름과 구분한다.

```powershell
$oldNodes = kubectl get nodes -l eks.amazonaws.com/nodegroup=Final-eks-nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
$oldNodes
```

대상 목록이 기존 그룹의 노드임을 확인하고 하나씩 drain한다. emptyDir 옵션은 옛 파드의 임시 데이터 삭제를 허용하며 PVC의 EBS 데이터를 삭제하지 않는다.

```powershell
foreach ($oldNode in $oldNodes) {
    if ([string]::IsNullOrWhiteSpace($oldNode)) { continue }
    kubectl drain $oldNode --ignore-daemonsets --delete-emptydir-data --timeout=600s
    if ($LASTEXITCODE -ne 0) { throw "이전 중단: $oldNode 의 drain 결과를 확인하세요." }
}
kubectl get pods -n soldesk -o wide
kubectl get pods -n argocd -o wide
kubectl get pods -n monitoring -o wide
```

오류나 Pending이 남으면 기존 그룹 제거로 넘어가지 않는다. 새 그룹 최대치를 임의로 늘리거나 PDB를 강제로 우회하지 말고 배치 원인을 확인한다.

C:\aws-msa-backend-terraform\terraform\terraform.tfvars에서 keep_legacy_node_group=false로 바꾼 후:

```powershell
cd C:\aws-msa-backend-terraform\terraform
terraform plan "-out=zonal-retire.tfplan"
terraform apply "zonal-retire.tfplan"
```

노드그룹 삭제 대상은 기존 module.eks.aws_eks_node_group.main[0] 1개이며 새 그룹/클러스터/PVC/RDS가 삭제 대상이면 중단한다. ASG 알림은 풀별 리소스로 관리하며 기존 그룹의 알림도 제거한다. 삭제 중에는 EKS 종료 대기 때문에 시간이 걸릴 수 있다.

### 통합 알림 설정에서 그룹별 설정으로 전환

이전 통합 알림 리소스는 기존 ASG 삭제 후 알림을 갱신하면서 `AutoScalingGroup name not found` 오류가 발생했다. 현재 코드는 `removed` 블록의 `destroy=false`로 이전 상태 주소만 해제하고 `node_groups["az-a"]`, `node_groups["az-c"]`로 알림을 각각 등록한다. 경고의 "no longer managed"는 이전 통합 주소에 대한 것이며 AWS 알림은 새 두 리소스가 이어서 관리한다.

기존 그룹 삭제가 이미 완료된 이번 복구에서는 다음 새 계획을 사용한다. 이전 zonal-retire.tfplan은 다시 실행하지 않는다.

```powershell
cd C:\aws-msa-backend-terraform\terraform-k8s
.\Prepare-Secrets.ps1
cd C:\aws-msa-backend-terraform\terraform
terraform plan "-out=zonal-alerts-fix.tfplan"
terraform apply "zonal-alerts-fix.tfplan"
```

검증한 복구 계획은 알림 설정만 2 add / 0 change / 0 destroy이며 노드나 DB는 변경하지 않는다. 적용 후 두 ASG 각각 시작·종료·시작 실패·종료 실패 4종 알림을 확인한다. 단계 1의 2 add / 1 change는 이전 통합 알림 코드로 검증했던 당시 수량이다. 새 코드로 처음 구축하거나 전환할 때는 그룹별 알림 리소스 수가 별도로 포함된다.

## 최종 확인 및 재구축

```powershell
kubectl get nodes -L eks.amazonaws.com/nodegroup,final-node-pool,topology.kubernetes.io/zone
kubectl get pods -A
kubectl get applications -n argocd
kubectl logs -n kube-system deployment/cluster-autoscaler --tail=80
```

최종 그룹은 2개, 기본 노드 4개/최대 5개이다. 기존 그룹의 eks_node_*_size 값을 바꿔도 새 그룹 수는 바뀌지 않는다. 다음 전체 재구축부터 keep_legacy_node_group=false를 유지한다. AWS 생성 후 K8s 설치 순서는 같다. 기존 PVC의 AZ와 node pool 라벨이 일치해야 한다.

CA를 잃어도 ASG는 각 그룹의 목표 수량을 맞춰 노드를 보충한다. 모든 자원 부족, 노드 장애, AZ 장애를 없애는 구성은 아니므로 복구 시간과 예산을 함께 관찰한다.

## 전환 준비의 복구 방법

단계 1만 실행했고 Kubernetes 배치를 아직 변경하지 않았다면 기존 그룹은 그대로 서비스 중이다. 새 그룹에 업무 파드가 이미 배치될 수 있으므로 즉시 삭제하지 말고 배치를 확인한다.

단계 2 이후에는 노드 selector가 새 그룹을 가리킨다. 새 그룹만 먼저 삭제하면 모니터링이 Pending이 되므로 제거하지 않는다. 원래 설정으로 되돌릴 때는 Kubernetes 배치 규칙과 CA 관리 그룹을 먼저 복원하고 파드 Ready를 확인한 뒤 새 그룹 정리를 계획한다. Terraform 상태 파일을 옛 백업으로 덮어쓰지 않는다.

AWS 권고: https://docs.aws.amazon.com/eks/latest/userguide/managed-node-groups.html
