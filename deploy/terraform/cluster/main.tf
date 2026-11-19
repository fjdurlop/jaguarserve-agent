# Cluster stack: created by `make up`, destroyed by `make down` (lab mode, plan_scaling S0).
# VPC with public subnets only (no NAT gateway: ≈ $33 / month saved), EKS, one always-on system node,
# Karpenter for GPU nodes (0..gpu_limit), pod identities for Karpenter, EBS CSI, vLLM (S3) and the ALB
# controller. Add-ons are in addons.tf.

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  tags = { project = var.name }
  azs  = slice(data.aws_availability_zones.available.names, 0, 3)
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.7"

  name                    = var.name
  cidr                    = "10.40.0.0/16"
  azs                     = local.azs
  public_subnets          = [for i, _ in local.azs : cidrsubnet("10.40.0.0/16", 4, i)]
  map_public_ip_on_launch = true
  enable_nat_gateway      = false

  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
    "karpenter.sh/discovery" = var.name
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.29"

  name               = var.name
  kubernetes_version = var.kubernetes_version

  endpoint_public_access       = true
  endpoint_public_access_cidrs = var.admin_cidrs
  endpoint_private_access      = true # nodes reach the API inside the VPC

  enable_cluster_creator_admin_permissions = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.public_subnets

  # Lab: no control-plane log group, no customer KMS key (both bill after destroy otherwise).
  enabled_log_types           = []
  create_cloudwatch_log_group = false
  create_kms_key              = false
  encryption_config           = null

  addons = {
    vpc-cni                = { before_compute = true }
    eks-pod-identity-agent = { before_compute = true }
    kube-proxy             = {}
    coredns                = {}
    aws-ebs-csi-driver = {
      pod_identity_association = [{
        role_arn        = module.ebs_csi_identity.iam_role_arn
        service_account = "ebs-csi-controller-sa"
      }]
    }
  }

  eks_managed_node_groups = {
    system = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = [var.system_instance_type]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
      labels         = { role = "system" }
      # 60 GB: agent image + the one-off weights sync job (model staged on disk before S3 upload).
      block_device_mappings = {
        root = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = 60
            volume_type           = "gp3"
            encrypted             = true
            delete_on_termination = true
          }
        }
      }
    }
  }

  node_security_group_tags = { "karpenter.sh/discovery" = var.name }
  cluster_tags             = { "lab-expires-at" = var.expires_at }
  tags                     = local.tags
}

# --- Karpenter: controller IAM (pod identity), node role, SQS queue for spot interruptions ---
module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 21.29"

  cluster_name                  = module.eks.cluster_name
  node_iam_role_use_name_prefix = false
  node_iam_role_name            = "${var.name}-karpenter-node"
  node_iam_role_additional_policies = {
    AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }
  tags = local.tags
}

# --- Pod identities ---
module "ebs_csi_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.10"

  name                      = "${var.name}-ebs-csi"
  attach_aws_ebs_csi_policy = true
  tags                      = local.tags
}

module "vllm_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.10"

  name                 = "${var.name}-vllm"
  attach_custom_policy = true
  policy_statements = [
    {
      sid       = "ListModels"
      actions   = ["s3:ListBucket"]
      resources = ["arn:aws:s3:::${var.models_bucket}"]
    },
    {
      sid       = "ReadWriteModels" # write only used by the one-off weights sync job
      actions   = ["s3:GetObject", "s3:PutObject"]
      resources = ["arn:aws:s3:::${var.models_bucket}/*"]
    },
  ]
  associations = {
    vllm = {
      cluster_name    = module.eks.cluster_name
      namespace       = "agent"
      service_account = "vllm"
    }
  }
  tags = local.tags
}

module "lb_controller_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.10"
  count   = var.enable_alb ? 1 : 0

  name                            = "${var.name}-lb-controller"
  attach_aws_lb_controller_policy = true
  associations = {
    controller = {
      cluster_name    = module.eks.cluster_name
      namespace       = "kube-system"
      service_account = "aws-load-balancer-controller"
    }
  }
  tags = local.tags
}
