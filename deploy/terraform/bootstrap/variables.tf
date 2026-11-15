variable "region" {
  description = "AWS region; pick one with G-instance quota (Service Quotas: Running On-Demand G and VT instances)"
  type        = string
  default     = "eu-north-1"
}

variable "name" {
  description = "Prefix for every resource and the `project` tag"
  type        = string
  default     = "jaguarserve"
}

variable "budget_usd" {
  description = "Monthly cost ceiling (B11)"
  type        = number
  default     = 40
}

variable "budget_emails" {
  description = "Who gets the budget alerts (set in terraform.tfvars, never committed)"
  type        = list(string)
}
