# Vanta integration for the management account.
#
# Implements steps from Vanta's "Connect AWS" wizard:
#   - "Management account > Policy creation" — VantaManagementAccountPermissions
#     (Identity Store read + data-exfiltration deny list)
#   - "Management account > Role Creation" — the vanta-auditor role is created
#     by terraform-aws-iso27001; this module only attaches the management-account
#     policy to it
#   - "IAM Identity Center" — Identity Store permissions let Vanta audit SSO
#     users and groups (only meaningful in the management account)
#
# The external ID (from "AWS accounts > Role Creation") is distributed to
# member accounts via a CloudFormation StackSet so terraform-aws-iso27001
# can read it locally and configure the trust policy.
#
# All resources are gated on var.vanta_external_id being set.

locals {
  vanta_enabled = var.vanta_external_id != null
}

resource "aws_ssm_parameter" "vanta_external_id" {
  count = local.vanta_enabled ? 1 : 0
  name  = "/vanta/external_id"
  type  = "SecureString"
  value = var.vanta_external_id

  tags = local.default_module_tags
}

resource "aws_cloudformation_stack_set" "vanta_external_id" {
  count            = local.vanta_enabled ? 1 : 0
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
  count          = local.vanta_enabled ? 1 : 0
  stack_set_name = aws_cloudformation_stack_set.vanta_external_id[0].name

  deployment_targets {
    organizational_unit_ids = [data.aws_organizations_organization.current.roots[0].id]
  }
}

# Vanta "Management account > Policy creation" step.
# Identity Store actions are management-account-only (IAM Identity Center).
# Deny statements are required by Vanta to block data-exfiltration actions
# on the auditor role.
data "aws_iam_policy_document" "vanta_sso_permissions" {
  count = local.vanta_enabled ? 1 : 0

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
  count  = local.vanta_enabled ? 1 : 0
  name   = "VantaManagementAccountPermissions"
  policy = data.aws_iam_policy_document.vanta_sso_permissions[0].json

  tags = local.default_module_tags
}

# Vanta "Management account > Role Creation" step — attach to the role
# created by terraform-aws-iso27001.
resource "aws_iam_role_policy_attachment" "vanta_sso_permissions" {
  count      = local.vanta_enabled ? 1 : 0
  role       = var.vanta_auditor_role_name
  policy_arn = aws_iam_policy.vanta_sso_permissions[0].arn
}
