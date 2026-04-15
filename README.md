# terraform-aws-org-governance

[![Need Help?](https://img.shields.io/badge/Need%20Help%3F-Contact%20Us-0066CC)](https://infrahouse.com/contact)
[![Docs](https://img.shields.io/badge/docs-github.io-blue)](https://infrahouse.github.io/terraform-aws-org-governance/)
[![Registry](https://img.shields.io/badge/Terraform-Registry-purple?logo=terraform)](https://registry.terraform.io/modules/infrahouse/org-governance/aws/latest)
[![Release](https://img.shields.io/github/release/infrahouse/terraform-aws-org-governance.svg)](https://github.com/infrahouse/terraform-aws-org-governance/releases/latest)
[![AWS Organizations](https://img.shields.io/badge/AWS-Organizations-orange?logo=amazonaws)](https://aws.amazon.com/organizations/)
[![AWS Lambda](https://img.shields.io/badge/AWS-Lambda-orange?logo=awslambda)](https://aws.amazon.com/lambda/)
[![AWS CloudWatch](https://img.shields.io/badge/AWS-CloudWatch-orange?logo=amazoncloudwatch)](https://aws.amazon.com/cloudwatch/)
[![Security](https://img.shields.io/github/actions/workflow/status/infrahouse/terraform-aws-org-governance/vuln-scanner-pr.yml?label=Security)](https://github.com/infrahouse/terraform-aws-org-governance/actions/workflows/vuln-scanner-pr.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Centralized AWS Organizations governance module deployed in the management account. It handles
compliance and governance tasks that require management-account-level access, such as assuming
cross-account roles into member accounts or calling AWS Organizations APIs.

## Features

- **CloudWatch Log Retention Enforcement** -- A Lambda function that enforces log retention
  policies across all member accounts. It lists accounts via `organizations:ListAccounts`,
  assumes the `InfraHouseLogRetention` role (provisioned in each member account by
  [terraform-aws-iso27001](https://github.com/infrahouse/terraform-aws-iso27001)) across all
  enabled regions, and sets retention on CloudWatch log groups matching configurable prefixes
  (e.g., `aws-controltower` groups locked by Control Tower's mandatory SCP).
- **Management Account Deployment** -- Designed to run from the management account where
  AWS Organizations APIs are available.
- **ISO 27001 Compliance** -- Enforces 365-day log retention to meet ISO 27001 and SOC 2
  requirements.

## Planned Features

- Custom Service Control Policies (SCPs)
- Tag Policies for consistent tagging across accounts
- Backup Policies at the organization level
- Delegated administrator registration (Security Hub, GuardDuty, Config, etc.)
- Organization Config aggregator and conformance packs
- Account lifecycle automation via EventBridge
- Cost Anomaly Detection monitors

## Quick Start

```hcl
module "org_governance" {
  source  = "registry.infrahouse.com/infrahouse/org-governance/aws"
  version = "0.4.0"

  alarm_emails = ["security@example.com"]
}
```

## Documentation

Full documentation is available on
[GitHub Pages](https://infrahouse.github.io/terraform-aws-org-governance/).

## Usage

<!-- BEGIN_TF_DOCS -->

## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | ~> 1.5 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | ~> 6.0 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_aws"></a> [aws](#provider\_aws) | ~> 6.0 |

## Modules

| Name | Source | Version |
|------|--------|---------|
| <a name="module_enforce_log_retention"></a> [enforce\_log\_retention](#module\_enforce\_log\_retention) | registry.infrahouse.com/infrahouse/lambda-monitored/aws | 1.1.0 |

## Resources

| Name | Type |
|------|------|
| [aws_cloudwatch_event_rule.enforce_log_retention](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_rule) | resource |
| [aws_cloudwatch_event_target.enforce_log_retention](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_target) | resource |
| [aws_iam_policy.enforce_log_retention](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_policy) | resource |
| [aws_lambda_permission.enforce_log_retention](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_permission) | resource |
| [aws_iam_policy_document.enforce_log_retention](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_organizations_organization.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/organizations_organization) | data source |
| [aws_region.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/region) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_alarm_emails"></a> [alarm\_emails](#input\_alarm\_emails) | List of email addresses to receive Lambda alarm notifications. | `list(string)` | n/a | yes |
| <a name="input_cloudwatch_retention_days"></a> [cloudwatch\_retention\_days](#input\_cloudwatch\_retention\_days) | Desired retention in days for CloudWatch log groups created<br/>implicitly by AWS services. The Lambda will set retention to<br/>this value on any matching log group. | `number` | `365` | no |
| <a name="input_control_tower_home_region"></a> [control\_tower\_home\_region](#input\_control\_tower\_home\_region) | AWS region where the Control Tower landing zone is configured<br/>(its "home" region). Control Tower APIs are regional and only<br/>return the landing zone in its home region. Defaults to null,<br/>in which case the Lambda's own region is used — set this only<br/>when the Lambda runs in a different region than Control Tower. | `string` | `null` | no |
| <a name="input_enforce_log_retention"></a> [enforce\_log\_retention](#input\_enforce\_log\_retention) | Enable the scheduled Lambda that enforces minimum CloudWatch<br/>log group retention across all organization accounts. | `bool` | `true` | no |
| <a name="input_enforce_log_retention_excluded_accounts"></a> [enforce\_log\_retention\_excluded\_accounts](#input\_enforce\_log\_retention\_excluded\_accounts) | List of AWS account IDs to skip during log retention<br/>enforcement. Use this for accounts that are part of the<br/>organization but intentionally not managed by this module<br/>(e.g., accounts owned by external parties, sandbox accounts<br/>with no compliance requirement). Excluded accounts are<br/>skipped in addition to any account that is not enrolled in<br/>Control Tower. | `list(string)` | `[]` | no |
| <a name="input_enforce_log_retention_prefixes"></a> [enforce\_log\_retention\_prefixes](#input\_enforce\_log\_retention\_prefixes) | Log group name prefixes to target for retention enforcement.<br/>Only log groups matching these prefixes will be updated. | `list(string)` | <pre>[<br/>  "/aws/lambda/aws-controltower-",<br/>  "/aws/guardduty/",<br/>  "StackSet-AWSControlTowerBP-"<br/>]</pre> | no |
| <a name="input_enforce_log_retention_role_name"></a> [enforce\_log\_retention\_role\_name](#input\_enforce\_log\_retention\_role\_name) | Name of the cross-account IAM role the Lambda assumes in each<br/>member account to enforce log retention. The role must exist in<br/>every scanned account and trust the management account root.<br/>Defaults to InfraHouseLogRetention, provisioned by<br/>terraform-aws-iso27001. | `string` | `"InfraHouseLogRetention"` | no |
| <a name="input_enforce_log_retention_schedule"></a> [enforce\_log\_retention\_schedule](#input\_enforce\_log\_retention\_schedule) | EventBridge schedule expression for the log retention<br/>enforcement Lambda. | `string` | `"rate(1 day)"` | no |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_enforce_log_retention_function_name"></a> [enforce\_log\_retention\_function\_name](#output\_enforce\_log\_retention\_function\_name) | Name of the log retention enforcement Lambda function. |
| <a name="output_enforce_log_retention_role_arn"></a> [enforce\_log\_retention\_role\_arn](#output\_enforce\_log\_retention\_role\_arn) | ARN of the Lambda execution role for log retention enforcement. |
| <a name="output_organization_accounts"></a> [organization\_accounts](#output\_organization\_accounts) | Map of organization account IDs to account details (name, email, status, ARN). |
<!-- END_TF_DOCS -->

## Examples

See the [examples/](examples/) directory for working examples.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

## License

[Apache 2.0](LICENSE)
