variable "region" {
  type    = string
  default = "eu-north-1"
}

variable "name" {
  description = "Cluster name and `project` tag (the reaper only touches this project)"
  type        = string
  default     = "jaguarserve"
}

variable "kubernetes_version" {
  description = "EKS version in standard support (aws eks describe-cluster-versions)"
  type        = string
  default     = "1.35"
}

variable "admin_cidrs" {
  description = "CIDRs allowed to reach the public Kubernetes API (make up sets your current IP /32)"
  type        = list(string)
}

variable "expires_at" {
  description = "UTC time after which the reaper tears the cluster down (make up sets now + SESSION_HOURS)"
  type        = string
}

variable "system_instance_type" {
  description = "Always-on CPU node: add-ons, agent-api, Redis, Postgres, Prometheus"
  type        = string
  default     = "t3.large"
}

variable "gpu_instance_types" {
  description = "GPU node types Karpenter may launch (one GPU each: L4/A10G 24 GB, g6e L40S 48 GB); cheapest available wins. Wide on purpose: capacity is often short. Mind the spot vCPU quota (a g6.4xlarge has 16 vCPU)."
  type        = list(string)
  default     = ["g6.xlarge", "g5.xlarge", "g6.2xlarge", "g6.4xlarge", "g6e.xlarge"]
}

variable "gpu_capacity_types" {
  description = "spot and/or on-demand; Karpenter picks the cheapest available"
  type        = list(string)
  default     = ["spot", "on-demand"]
}

variable "gpu_limit" {
  description = "Max GPUs Karpenter may run at once (also KEDA maxReplicaCount)"
  type        = number
  default     = 3
}

variable "models_bucket" {
  description = "S3 bucket with model weights (bootstrap output); vLLM pods get read access"
  type        = string
}

variable "enable_alb" {
  description = "Install the AWS Load Balancer Controller (public ALB ingress). Lab default: off, use port-forward"
  type        = bool
  default     = false
}
