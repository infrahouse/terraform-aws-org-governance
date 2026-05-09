variable "alarm_emails" {
  description = "Email addresses for Lambda alarm notifications."
  type        = list(string)
}

variable "vanta_secret_arn" {
  description = <<-EOT
    ARN of the Secrets Manager secret containing Vanta API credentials.
    The secret value must be a JSON object with keys:
      client_id     - Vanta OAuth2 client ID
      client_secret - Vanta OAuth2 client secret
  EOT
  type        = string
}

variable "assume_role_name" {
  description = <<-EOT
    Name of the cross-account IAM role the Lambda assumes in each
    member account to read S3 bucket tags. Must have s3:GetBucketTagging.
  EOT
  type        = string
  default     = "InfraHouseGovernance"
}

variable "schedule" {
  description = "EventBridge schedule expression for the reconciler."
  type        = string
  default     = "rate(1 hour)"
}

variable "tags" {
  description = "Tags to apply to all resources."
  type        = map(string)
  default     = {}
}
