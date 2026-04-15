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
  # Test relies on AWSControlTowerExecution, which already exists in
  # every member account and (in this test org) trusts the Lambda's
  # execution role. Real users should stick with the default
  # InfraHouseLogRetention role provisioned by terraform-aws-iso27001.
  enforce_log_retention_role_name = "AWSControlTowerExecution"
  # Exercise the retention pass with a synthetic prefix the test
  # owns. Default is empty since real retention enforcement is
  # meant to be handled by the owning module at creation time.
  enforce_log_retention_prefixes = ["/test/retention/"]
  # CI runs in us-east-1 but the test org's Control Tower landing
  # zone is homed in us-west-1.
  control_tower_home_region = "us-west-1"
  # Fake account ID to exercise the exclude-list code path. The
  # Lambda should log a skip for this ID without attempting AssumeRole.
  enforce_log_retention_excluded_accounts = ["000000000000"]
}

output "enforce_log_retention_function_name" {
  value = module.org_governance.enforce_log_retention_function_name
}

output "organization_accounts" {
  value = module.org_governance.organization_accounts
}

data "aws_caller_identity" "current" {}
