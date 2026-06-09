module "org_governance" {
  source  = "registry.infrahouse.com/infrahouse/org-governance/aws"
  version = "0.8.3"

  alarm_emails      = ["security@example.com"]
  vanta_external_id = var.vanta_external_id
}

output "enforce_log_retention_function_name" {
  value = module.org_governance.enforce_log_retention_function_name
}

output "organization_accounts" {
  value = module.org_governance.organization_accounts
}
