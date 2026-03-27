output "enforce_log_retention_function_name" {
  description = "Name of the log retention enforcement Lambda function."
  value = (
    var.enforce_log_retention
    ? module.enforce_log_retention[0].lambda_function_name
    : null
  )
}

output "enforce_log_retention_role_arn" {
  description = "ARN of the Lambda execution role for log retention enforcement."
  value = (
    var.enforce_log_retention
    ? module.enforce_log_retention[0].lambda_role_arn
    : null
  )
}

output "organization_accounts" {
  description = "Map of organization account IDs to account details (name, email, status, ARN)."
  value = {
    for account in data.aws_organizations_organization.current.accounts :
    account.id => {
      name   = account.name
      email  = account.email
      status = account.status
      arn    = account.arn
    }
  }
}
