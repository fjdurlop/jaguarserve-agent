# Cluster add-ons as Helm releases. All run on the system node; versions pinned.

locals {
  chart_versions = {
    karpenter      = "1.15.2"
    keda           = "2.20.2"
    prometheus     = "29.46.0"
    metrics_server = "3.13.1"
    nvidia_plugin  = "0.19.3"
    lb_controller  = "3.6.2"
  }
  on_system_node = { role = "system" }
}

resource "helm_release" "karpenter" {
  name       = "karpenter"
  namespace  = "kube-system"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter"
  version    = local.chart_versions.karpenter
  wait       = true

  values = [yamlencode({
    replicas     = 1 # one system node; two replicas would sit Pending
    nodeSelector = local.on_system_node
    serviceAccount = {
      name = module.karpenter.service_account
    }
    settings = {
      clusterName       = module.eks.cluster_name
      clusterEndpoint   = module.eks.cluster_endpoint
      interruptionQueue = module.karpenter.queue_name
    }
    controller = {
      resources = {
        requests = { cpu = "100m", memory = "256Mi" }
        limits   = { memory = "512Mi" }
      }
    }
  })]

  depends_on = [module.eks]
}

# EC2NodeClass + NodePool for GPUs and a gp3 default StorageClass (local chart; CRDs come with Karpenter).
resource "helm_release" "platform" {
  name      = "platform"
  namespace = "kube-system"
  chart     = "${path.module}/../../helm/platform"

  values = [yamlencode({
    clusterName       = module.eks.cluster_name
    nodeRole          = module.karpenter.node_iam_role_name
    gpuInstanceTypes  = var.gpu_instance_types
    gpuCapacityTypes  = var.gpu_capacity_types
    gpuLimit          = var.gpu_limit
    consolidateAfter  = "5m"
    tags              = merge(local.tags, { "lab-expires-at" = var.expires_at })
    gpuRootVolumeSize = "120Gi"
  })]

  depends_on = [helm_release.karpenter]
}

resource "helm_release" "nvidia_device_plugin" {
  name       = "nvidia-device-plugin"
  namespace  = "kube-system"
  repository = "https://nvidia.github.io/k8s-device-plugin"
  chart      = "nvidia-device-plugin"
  version    = local.chart_versions.nvidia_plugin

  values = [yamlencode({
    # No node-feature-discovery: schedule on any node Karpenter launched with a GPU.
    affinity = {
      nodeAffinity = {
        requiredDuringSchedulingIgnoredDuringExecution = {
          nodeSelectorTerms = [{
            matchExpressions = [{ key = "karpenter.k8s.aws/instance-gpu-count", operator = "Exists" }]
          }]
        }
      }
    }
    tolerations = [{ key = "nvidia.com/gpu", operator = "Exists", effect = "NoSchedule" }]
  })]

  depends_on = [module.eks]
}

resource "helm_release" "metrics_server" {
  name       = "metrics-server"
  namespace  = "kube-system"
  repository = "https://kubernetes-sigs.github.io/metrics-server/"
  chart      = "metrics-server"
  version    = local.chart_versions.metrics_server
  values     = [yamlencode({ nodeSelector = local.on_system_node })]
  depends_on = [module.eks]
}

resource "helm_release" "keda" {
  name             = "keda"
  namespace        = "keda"
  create_namespace = true
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  version          = local.chart_versions.keda

  values = [yamlencode({
    nodeSelector = local.on_system_node
    resources = {
      operator     = { requests = { cpu = "50m", memory = "128Mi" }, limits = { memory = "512Mi" } }
      metricServer = { requests = { cpu = "50m", memory = "128Mi" }, limits = { memory = "512Mi" } }
      webhooks     = { requests = { cpu = "20m", memory = "64Mi" }, limits = { memory = "256Mi" } }
    }
  })]

  depends_on = [module.eks]
}

# Prometheus server only: scrapes pods annotated prometheus.io/scrape (agent-api, vLLM). KEDA reads it.
resource "helm_release" "prometheus" {
  name             = "prometheus"
  namespace        = "monitoring"
  create_namespace = true
  repository       = "https://prometheus-community.github.io/helm-charts"
  chart            = "prometheus"
  version          = local.chart_versions.prometheus

  values = [yamlencode({
    alertmanager               = { enabled = false }
    "prometheus-pushgateway"   = { enabled = false }
    "prometheus-node-exporter" = { enabled = false }
    "kube-state-metrics"       = { enabled = false }
    configmapReload            = { prometheus = { enabled = false } }
    server = {
      nodeSelector     = local.on_system_node
      retention        = "2d"
      persistentVolume = { enabled = false }
      global           = { scrape_interval = "15s", evaluation_interval = "15s" }
      resources = {
        requests = { cpu = "100m", memory = "256Mi" }
        limits   = { memory = "768Mi" }
      }
    }
  })]

  depends_on = [module.eks]
}

resource "helm_release" "lb_controller" {
  count      = var.enable_alb ? 1 : 0
  name       = "aws-load-balancer-controller"
  namespace  = "kube-system"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = local.chart_versions.lb_controller

  values = [yamlencode({
    clusterName    = module.eks.cluster_name
    region         = var.region
    vpcId          = module.vpc.vpc_id
    replicaCount   = 1
    nodeSelector   = local.on_system_node
    serviceAccount = { name = "aws-load-balancer-controller" }
  })]

  depends_on = [module.lb_controller_identity]
}
