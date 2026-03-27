variable "cloudwatch_retention_days" {
  type    = number
  default = 365
}

module "org_governance" {
  source = "./../../"
  alarm_emails = [
    "security@example.com",
  ]
  cloudwatch_retention_days = var.cloudwatch_retention_days
}

output "enforce_log_retention_function_name" {
  value = module.org_governance.enforce_log_retention_function_name
}

output "organization_accounts" {
  value = module.org_governance.organization_accounts
}

data "aws_caller_identity" "current" {}
