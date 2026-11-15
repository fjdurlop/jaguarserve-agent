# Bootstrap: what stays between lab sessions (≈ $3 / month). Applied once; local state on purpose
# (it creates the bucket that holds the cluster stack's state).
#
#   cd deploy/terraform/bootstrap && cp terraform.tfvars.example terraform.tfvars && terraform init && terraform apply

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.28" }
    archive = { source = "hashicorp/archive", version = "~> 2.7" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { project = var.name, stack = "bootstrap" }
  }
}

data "aws_caller_identity" "me" {}

locals {
  suffix = data.aws_caller_identity.me.account_id # bucket names are global
}

# --- Terraform state for the cluster stack (S3 native locking, no DynamoDB) ---
resource "aws_s3_bucket" "state" {
  bucket = "${var.name}-tfstate-${local.suffix}"
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 30 }
  }
}

# --- Model weights copied once from the Hub; vLLM pods read them in-region (faster cold start) ---
resource "aws_s3_bucket" "models" {
  bucket        = "${var.name}-models-${local.suffix}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "models" {
  bucket                  = aws_s3_bucket.models.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- agent-api image ---
resource "aws_ecr_repository" "agent" {
  name                 = "${var.name}/agent-api"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_lifecycle_policy" "agent" {
  repository = aws_ecr_repository.agent.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the last 5 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}

# --- Budget: alerts at 50 % and 100 % of the monthly ceiling, plus a forecast alert ---
resource "aws_budgets_budget" "monthly" {
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = var.budget_emails
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.budget_emails
  }
}
