module "vanta_s3_crr" {
  count  = var.vanta_api_secret_arn != null ? 1 : 0
  source = "./modules/vanta_exemption/s3_crr"

  alarm_emails     = var.alarm_emails
  vanta_secret_arn = var.vanta_api_secret_arn
  assume_role_name = var.enforce_log_retention_role_name
  schedule         = "rate(1 day)"
  tags             = local.default_module_tags
}
