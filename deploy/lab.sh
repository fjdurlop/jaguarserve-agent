#!/usr/bin/env bash
# Lab lifecycle for the EKS deployment (plan_scaling S0): the cluster exists only during a work session.
#
#   deploy/lab.sh bootstrap   once: state bucket, ECR, models bucket, $40 budget, reaper (≈ $3 / month)
#   deploy/lab.sh up          create cluster + add-ons, push image, install the app      (≈ 20 min)
#   deploy/lab.sh weights     once: copy model weights Hub -> S3 (faster cold starts)
#   deploy/lab.sh status      nodes, pods, autoscalers
#   deploy/lab.sh chat        port-forward the chat page to http://localhost:8080 (long-running)
#   deploy/lab.sh extend [h]  push the auto-destroy time h hours from now (default 2)
#   deploy/lab.sh down        delete everything Kubernetes created, then the cluster      (≈ 15 min)
#   deploy/lab.sh leftovers   list anything of this project still billing in the region
#
# Env: AWS_PROFILE (your profile), SESSION_HOURS (auto-destroy, default 6), AUTO_APPROVE=1 (no prompts).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_BOOT="$ROOT/deploy/terraform/bootstrap"
TF_CLUSTER="$ROOT/deploy/terraform/cluster"
CHART="$ROOT/deploy/helm/agent"
export KUBECONFIG="$ROOT/deploy/.kubeconfig"
NS=agent
SESSION_HOURS="${SESSION_HOURS:-6}"
MODEL_DIR="${MODEL_DIR:-Qwen3-14B-AWQ}"
APPROVE=()
[[ "${AUTO_APPROVE:-0}" == 1 ]] && APPROVE=(-auto-approve)

log() { printf '\033[1m==> %s\033[0m\n' "$*"; }
boot_out() { terraform -chdir="$TF_BOOT" output -raw "$1"; }
name() { echo "${TF_VAR_name:-jaguarserve}"; }

region() { boot_out region; }

cluster_exists() { aws eks describe-cluster --name "$(name)" --region "$(region)" >/dev/null 2>&1; }

kubeconfig() { aws eks update-kubeconfig --name "$(name)" --region "$(region)" --kubeconfig "$KUBECONFIG" >/dev/null; }

init_cluster_tf() {
  printf 'bucket = "%s"\nregion = "%s"\n' "$(boot_out state_bucket)" "$(region)" >"$TF_CLUSTER/backend.hcl"
  terraform -chdir="$TF_CLUSTER" init -input=false -reconfigure -backend-config=backend.hcl >/dev/null
}

cluster_vars() {
  local ip expires
  ip="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
  expires="$(date -u -d "+${SESSION_HOURS} hours" +%Y-%m-%dT%H:%M:%SZ)"
  echo "-var=admin_cidrs=[\"${ip}/32\"]" "-var=expires_at=${expires}" "-var=models_bucket=$(boot_out models_bucket)"
}

image_tag() { git -C "$ROOT" rev-parse --short HEAD; }

cmd_bootstrap() {
  [[ -f "$TF_BOOT/terraform.tfvars" ]] || { echo "copy $TF_BOOT/terraform.tfvars.example to terraform.tfvars first"; exit 1; }
  terraform -chdir="$TF_BOOT" init -input=false >/dev/null
  terraform -chdir="$TF_BOOT" apply "${APPROVE[@]}"
}

cmd_image() {
  local repo tag registry
  repo="$(boot_out ecr_repository_url)" tag="$(image_tag)" registry="${repo%%/*}"
  if [[ -n "$(git -C "$ROOT" status --porcelain -- agent api ingest web db data Dockerfile pyproject.toml uv.lock)" ]]; then
    tag="$tag-dirty"
  fi
  if [[ "$tag" != *-dirty ]] && aws ecr describe-images --region "$(region)" --repository-name "${repo#*/}" \
      --image-ids imageTag="$tag" >/dev/null 2>&1; then
    log "image $tag already in ECR"
  else
    log "build + push agent-api:$tag"
    aws ecr get-login-password --region "$(region)" | docker login --username AWS --password-stdin "$registry" >/dev/null
    docker build -t "$repo:$tag" "$ROOT"
    docker push "$repo:$tag"
  fi
  echo "$tag" >"$ROOT/deploy/.session-image"
}

cmd_secrets() {
  kubectl get ns "$NS" >/dev/null 2>&1 || kubectl create ns "$NS" >/dev/null
  if kubectl -n "$NS" get secret agent-secrets >/dev/null 2>&1; then return; fi
  log "create agent-secrets (random values; read the internal token with: deploy/lab.sh token)"
  kubectl -n "$NS" create secret generic agent-secrets \
    --from-literal=LLM_API_KEY="$(openssl rand -hex 24)" \
    --from-literal=POSTGRES_PASSWORD="$(openssl rand -hex 24)" \
    --from-literal=INTERNAL_TOKENS="$(openssl rand -hex 16)" >/dev/null
}

weights_uri() { echo "s3://$(boot_out models_bucket)/$MODEL_DIR"; }

weights_present() { [[ -n "$(aws s3 ls "$(weights_uri)/config.json" --region "$(region)" 2>/dev/null)" ]]; }

cmd_deploy() {
  local s3=""
  weights_present && s3="$(weights_uri)"
  log "helm upgrade agent (weights: ${s3:-from the Hub})"
  helm upgrade --install agent "$CHART" -n "$NS" --wait --timeout 20m \
    --set api.image.repository="$(boot_out ecr_repository_url)" \
    --set api.image.tag="$(cat "$ROOT/deploy/.session-image")" \
    --set vllm.weightsS3Uri="$s3" \
    --set vllm.rolloutStrategy=Recreate
}

cmd_up() {
  init_cluster_tf
  log "terraform apply (cluster expires in ${SESSION_HOURS} h; the reaper removes it after that)"
  # shellcheck disable=SC2046
  terraform -chdir="$TF_CLUSTER" apply "${APPROVE[@]}" $(cluster_vars)
  kubeconfig
  cmd_image
  cmd_secrets
  cmd_deploy
  log "up. GPU nodes: 0 until the first chat. Next: deploy/lab.sh chat"
}

cmd_weights() {
  weights_present && { log "weights already in $(weights_uri)"; return; }
  kubeconfig
  log "copy weights Hub -> $(weights_uri) (one-off job on the system node)"
  helm template agent "$CHART" -n "$NS" -s templates/weights-sync.yaml \
    --set api.image.repository=unused --set weightsSync.enabled=true --set vllm.weightsS3Uri="$(weights_uri)" |
    kubectl -n "$NS" apply -f -
  kubectl -n "$NS" wait --for=condition=complete job/weights-sync --timeout=45m
  kubectl -n "$NS" delete job weights-sync --wait=false
  log "done; next deploy uses S3 weights: deploy/lab.sh redeploy"
}

cmd_status() {
  kubeconfig
  kubectl get nodes -L role,node.kubernetes.io/instance-type,karpenter.sh/capacity-type
  kubectl -n "$NS" get pods -o wide
  kubectl -n "$NS" get scaledobject,hpa
  kubectl get nodeclaims 2>/dev/null || true
  aws eks describe-cluster --name "$(name)" --region "$(region)" --query 'cluster.tags."lab-expires-at"' --output text |
    sed 's/^/auto-destroy at (UTC): /'
}

cmd_token() {
  kubeconfig
  kubectl -n "$NS" get secret agent-secrets -o jsonpath='{.data.INTERNAL_TOKENS}' | base64 -d; echo
}

cmd_chat() {
  kubeconfig
  log "chat on http://localhost:8080 (Ctrl+C to stop)"
  kubectl -n "$NS" port-forward svc/agent-api 8080:80
}

cmd_extend() {
  local hours="${1:-2}" arn expires
  arn="$(aws eks describe-cluster --name "$(name)" --region "$(region)" --query cluster.arn --output text)"
  expires="$(date -u -d "+${hours} hours" +%Y-%m-%dT%H:%M:%SZ)"
  aws eks tag-resource --resource-arn "$arn" --tags "lab-expires-at=$expires" --region "$(region)"
  log "auto-destroy moved to $expires"
}

cmd_down() {
  init_cluster_tf
  if cluster_exists; then
    kubeconfig
    log "remove what Kubernetes created outside Terraform (load balancers, volumes, GPU nodes)"
    helm uninstall agent -n "$NS" --wait --timeout 10m 2>/dev/null || true
    kubectl -n "$NS" delete pvc --all --wait --timeout=5m 2>/dev/null || true
    kubectl delete nodepools --all --wait --timeout=10m 2>/dev/null || true
    kubectl wait --for=delete nodeclaims --all --timeout=10m 2>/dev/null || true
    # While the network is intact: its finalizer needs AWS access (Karpenter has no NAT once
    # Terraform drops the public route table), else destroy hangs. See deploy/KNOWN_ISSUES.md #2.
    kubectl delete ec2nodeclasses --all --wait --timeout=5m 2>/dev/null || true
  else
    log "cluster already gone (reaper?): drop in-cluster resources from the state"
    terraform -chdir="$TF_CLUSTER" state list 2>/dev/null | grep -E '^helm_release\.' |
      xargs -r -n1 terraform -chdir="$TF_CLUSTER" state rm >/dev/null || true
  fi
  log "terraform destroy"
  terraform -chdir="$TF_CLUSTER" destroy "${APPROVE[@]}" \
    -var='admin_cidrs=["0.0.0.0/32"]' -var=expires_at=now -var=models_bucket="$(boot_out models_bucket)"
  rm -f "$KUBECONFIG"
  cmd_leftovers
}

cmd_leftovers() {
  local r n found=0 out
  r="$(region)" n="$(name)"
  log "leftovers of '$n' in $r"
  check() { # label, command output
    if [[ -n "$2" && "$2" != "None" ]]; then echo "  ! $1: $2"; found=1; else echo "  ok $1"; fi
  }
  out="$(aws eks list-clusters --region "$r" --query "clusters[?@=='$n']" --output text)"
  check "EKS cluster" "$out"
  out="$(aws ec2 describe-instances --region "$r" --filters "Name=tag:project,Values=$n" \
    "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].[InstanceId,InstanceType]' --output text)"
  check "EC2 instances" "$out"
  out="$(aws ec2 describe-volumes --region "$r" --filters "Name=tag-key,Values=kubernetes.io/cluster/$n" \
    --query 'Volumes[].[VolumeId,Size,State]' --output text)"
  check "EBS volumes" "$out"
  out="$(aws elbv2 describe-load-balancers --region "$r" --query 'LoadBalancers[].LoadBalancerArn' --output text |
    tr '\t' '\n' | while read -r arn; do
      [[ -z "$arn" ]] && continue
      aws elbv2 describe-tags --region "$r" --resource-arns "$arn" \
        --query "TagDescriptions[?Tags[?Key=='elbv2.k8s.aws/cluster' && Value=='$n']].ResourceArn" --output text
    done)"
  check "load balancers" "$out"
  out="$(aws ec2 describe-addresses --region "$r" --filters "Name=tag:project,Values=$n" \
    --query 'Addresses[].PublicIp' --output text)"
  check "Elastic IPs" "$out"
  out="$(aws ec2 describe-vpcs --region "$r" --filters "Name=tag:project,Values=$n" --query 'Vpcs[].VpcId' --output text)"
  check "VPC" "$out"
  [[ $found == 0 ]] && log "nothing of this project is billing in $r (bootstrap stack excluded, ≈ \$3 / month)"
  return $found
}

case "${1:-}" in
  bootstrap) cmd_bootstrap ;;
  up) cmd_up ;;
  image) cmd_image ;;
  redeploy) kubeconfig; cmd_image; cmd_deploy ;;
  weights) cmd_weights ;;
  status) cmd_status ;;
  token) cmd_token ;;
  chat) cmd_chat ;;
  extend) cmd_extend "${2:-2}" ;;
  down) cmd_down ;;
  leftovers) cmd_leftovers ;;
  *) sed -n '2,15p' "$0"; exit 1 ;;
esac
