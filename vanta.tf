resource "aws_ssm_parameter" "vanta_external_id" {
  name  = "/vanta/external_id"
  type  = "SecureString"
  value = var.vanta_external_id

  tags = local.default_module_tags
}

resource "aws_cloudformation_stack_set" "vanta_external_id" {
  name             = "vanta-external-id"
  description      = "Distribute /vanta/external_id SSM parameter to all member accounts"
  permission_model = "SERVICE_MANAGED"

  auto_deployment {
    enabled                          = true
    retain_stacks_on_account_removal = false
  }

  capabilities = []

  template_body = jsonencode({
    AWSTemplateFormatVersion = "2010-09-09"
    Description              = "SSM parameter for Vanta external ID, managed by terraform-aws-org-governance"
    Parameters = {
      ExternalId = { Type = "String", NoEcho = true }
    }
    Resources = {
      VantaExternalId = {
        Type = "AWS::SSM::Parameter"
        Properties = {
          Name  = "/vanta/external_id"
          Type  = "SecureString"
          Value = { Ref = "ExternalId" }
        }
      }
    }
  })

  # NoEcho hides the value in the CF console but DescribeStackSet still returns it in cleartext.
  # Acceptable: the external ID is a confused-deputy token, not a credential.
  parameters = {
    ExternalId = var.vanta_external_id
  }

  tags = local.default_module_tags
}

resource "aws_cloudformation_stack_set_instance" "vanta_external_id" {
  stack_set_name = aws_cloudformation_stack_set.vanta_external_id.name

  deployment_targets {
    organizational_unit_ids = [data.aws_organizations_organization.current.roots[0].id]
  }
}

data "aws_iam_policy_document" "vanta_sso_permissions" {
  statement {
    effect = "Allow"
    actions = [
      "identitystore:DescribeGroup",
      "identitystore:DescribeGroupMembership",
      "identitystore:DescribeUser",
      "identitystore:GetGroupId",
      "identitystore:GetGroupMembershipId",
      "identitystore:GetUserId",
      "identitystore:IsMemberInGroups",
      "identitystore:ListGroupMemberships",
      "identitystore:ListGroupMembershipsForMember",
      "identitystore:ListGroups",
      "identitystore:ListUsers",
    ]
    resources = ["*"]
  }

  statement {
    effect = "Deny"
    actions = [
      "datapipeline:EvaluateExpression",
      "datapipeline:QueryObjects",
      "rds:DownloadDBLogFilePortion",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "vanta_sso_permissions" {
  name   = "VantaManagementAccountPermissions"
  policy = data.aws_iam_policy_document.vanta_sso_permissions.json

  tags = local.default_module_tags
}

resource "aws_iam_role_policy_attachment" "vanta_sso_permissions" {
  role       = var.vanta_auditor_role_name
  policy_arn = aws_iam_policy.vanta_sso_permissions.arn
}
