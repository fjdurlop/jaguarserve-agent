output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "models_bucket" {
  value = aws_s3_bucket.models.bucket
}

output "ecr_repository_url" {
  value = aws_ecr_repository.agent.repository_url
}

output "region" {
  value = var.region
}
