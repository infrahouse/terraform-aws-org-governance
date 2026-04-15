variable "alarm_emails" {
  description = <<-EOT
    List of email addresses to receive Lambda alarm notifications.
  EOT
  type        = list(string)
}

variable "enforce_log_retention" {
  description = <<-EOT
    Enable the scheduled Lambda that enforces minimum CloudWatch
    log group retention across all organization accounts.
  EOT
  type        = bool
  default     = true
}

variable "cloudwatch_retention_days" {
  description = <<-EOT
    Desired retention in days for CloudWatch log groups created
    implicitly by AWS services. The Lambda will set retention to
    this value on any matching log group.
  EOT
  type        = number
  default     = 365

  validation {
    condition = contains(
      [1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365,
      400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653],
      var.cloudwatch_retention_days
    )
    error_message = <<-EOT
      cloudwatch_retention_days must be a valid CloudWatch Logs
      retention value. Valid values: 1, 3, 5, 7, 14, 30, 60, 90,
      120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557,
      2922, 3288, 3653.
      Got: ${var.cloudwatch_retention_days}
    EOT
  }
}

variable "enforce_log_retention_prefixes" {
  description = <<-EOT
    Log group name prefixes to target for retention enforcement.
    Only log groups matching these prefixes will be updated.
  EOT
  type        = list(string)
  default = [
    "/aws/lambda/aws-controltower-",
    "/aws/guardduty/",
    "StackSet-AWSControlTowerBP-",
  ]
}

variable "enforce_log_retention_role_name" {
  description = <<-EOT
    Name of the cross-account IAM role the Lambda assumes in each
    member account to enforce log retention. The role must exist in
    every scanned account and trust the management account root.
    Defaults to InfraHouseLogRetention, provisioned by
    terraform-aws-iso27001.
  EOT
  type        = string
  default     = "InfraHouseLogRetention"
}

variable "control_tower_home_region" {
  description = <<-EOT
    AWS region where the Control Tower landing zone is configured
    (its "home" region). Control Tower APIs are regional and only
    return the landing zone in its home region. Defaults to null,
    in which case the Lambda's own region is used — set this only
    when the Lambda runs in a different region than Control Tower.
  EOT
  type        = string
  default     = null
}

variable "enforce_log_retention_excluded_accounts" {
  description = <<-EOT
    List of AWS account IDs to skip during log retention
    enforcement. Use this for accounts that are part of the
    organization but intentionally not managed by this module
    (e.g., accounts owned by external parties, sandbox accounts
    with no compliance requirement). Excluded accounts are
    skipped in addition to any account that is not enrolled in
    Control Tower.
  EOT
  type        = list(string)
  default     = []
}

variable "enforce_log_retention_schedule" {
  description = <<-EOT
    EventBridge schedule expression for the log retention
    enforcement Lambda.
  EOT
  type        = string
  default     = "rate(1 day)"
}
