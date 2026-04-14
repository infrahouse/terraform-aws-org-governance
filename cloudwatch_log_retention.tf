data "aws_iam_policy_document" "enforce_log_retention" {
  count = var.enforce_log_retention ? 1 : 0

  statement {
    sid    = "ListAccounts"
    effect = "Allow"
    actions = [
      "organizations:ListAccounts",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "GetGovernedRegions"
    effect = "Allow"
    actions = [
      "controltower:ListLandingZones",
      "controltower:GetLandingZone",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "AssumeRoleInMemberAccounts"
    effect = "Allow"
    actions = [
      "sts:AssumeRole",
    ]
    # Wildcard account ID is intentional: the target role's trust
    # policy is the real access boundary. Enumerating org account IDs
    # here would force a policy update on every account change.
    resources = [
      "arn:aws:iam::*:role/${var.enforce_log_retention_role_name}",
    ]
  }
}

resource "aws_iam_policy" "enforce_log_retention" {
  count       = var.enforce_log_retention ? 1 : 0
  name_prefix = "enforce-log-retention-"
  description = "Allow Lambda to list accounts and assume role in member accounts"
  policy      = data.aws_iam_policy_document.enforce_log_retention[0].json
  tags        = local.default_module_tags
}

module "enforce_log_retention" {
  count   = var.enforce_log_retention ? 1 : 0
  source  = "registry.infrahouse.com/infrahouse/lambda-monitored/aws"
  version = "1.0.4"

  function_name     = "enforce-log-retention"
  lambda_source_dir = "${path.module}/lambda/enforce_log_retention"
  handler           = "handler.handler"
  source_code_files = ["handler.py"]
  timeout           = 900
  memory_size       = 1024
  alarm_emails      = var.alarm_emails

  environment_variables = {
    RETENTION_DAYS     = tostring(var.cloudwatch_retention_days)
    LOG_GROUP_PREFIXES = jsonencode(var.enforce_log_retention_prefixes)
    ASSUME_ROLE_NAME   = var.enforce_log_retention_role_name
  }

  additional_iam_policy_arns = [
    aws_iam_policy.enforce_log_retention[0].arn,
  ]

  tags = local.default_module_tags
}

resource "aws_cloudwatch_event_rule" "enforce_log_retention" {
  count               = var.enforce_log_retention ? 1 : 0
  name_prefix         = "enforce-log-retention-"
  description         = "Daily enforcement of minimum CloudWatch log group retention"
  schedule_expression = var.enforce_log_retention_schedule
  tags                = local.default_module_tags
}

resource "aws_cloudwatch_event_target" "enforce_log_retention" {
  count = var.enforce_log_retention ? 1 : 0
  rule  = aws_cloudwatch_event_rule.enforce_log_retention[0].name
  arn   = module.enforce_log_retention[0].lambda_function_arn
}

resource "aws_lambda_permission" "enforce_log_retention" {
  count         = var.enforce_log_retention ? 1 : 0
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.enforce_log_retention[0].lambda_function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.enforce_log_retention[0].arn
}
