data "aws_iam_policy_document" "this" {
  statement {
    sid       = "ReadVantaSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.vanta_secret_arn]
  }

  statement {
    sid    = "AssumeRoleInMemberAccounts"
    effect = "Allow"
    actions = [
      "sts:AssumeRole",
    ]
    resources = [
      "arn:aws:iam::*:role/${var.assume_role_name}",
    ]
  }
}

resource "aws_iam_policy" "this" {
  name_prefix = "vanta-s3-crr-reconciler-"
  description = "Vanta S3 CRR reconciler: read secret + assume cross-account role"
  policy      = data.aws_iam_policy_document.this.json
  tags        = var.tags
}

module "lambda" {
  source  = "registry.infrahouse.com/infrahouse/lambda-monitored/aws"
  version = "1.1.0"

  function_name     = "vanta-s3-crr-reconciler"
  lambda_source_dir = "${path.module}/lambda"
  handler           = "handler.handler"
  source_code_files = ["handler.py"]
  timeout           = 900
  memory_size       = 1024

  alarm_emails                         = var.alarm_emails
  memory_utilization_threshold_percent = 80

  environment_variables = {
    VANTA_SECRET_ARN = var.vanta_secret_arn
    ASSUME_ROLE_NAME = var.assume_role_name
  }

  additional_iam_policy_arns = [
    aws_iam_policy.this.arn,
  ]

  tags = var.tags
}

resource "aws_cloudwatch_event_rule" "this" {
  name_prefix         = "vanta-s3-crr-"
  description         = "Vanta S3 CRR exemption reconciliation"
  schedule_expression = var.schedule
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "this" {
  rule = aws_cloudwatch_event_rule.this.name
  arn  = module.lambda.lambda_function_arn
}

resource "aws_lambda_permission" "this" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda.lambda_function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.this.arn
}
