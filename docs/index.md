# terraform-aws-org-governance

Centralized AWS Organizations governance module deployed in the management account.

## Overview

Certain compliance and governance tasks can only be performed from the AWS Organizations
management account -- they require cross-account role assumption into member accounts, or
AWS Organizations API calls restricted to the management account.

This module provides a centralized deployment model for those tasks.

## Features

- **CloudWatch Log Retention Enforcement** -- A scheduled Lambda that scans all organization
  member accounts and enforces minimum log retention on CloudWatch log groups created by AWS
  services (Control Tower, GuardDuty, etc.). Assumes the least-privilege
  `InfraHouseGovernance` role provisioned by
  [terraform-aws-iso27001](https://github.com/infrahouse/terraform-aws-iso27001) >= 2.2.0.
- **Vanta Exclusion Tagging** -- Tags Control Tower-managed log groups and AWS-managed
  Lambda functions (e.g., `aws-controltower-NotificationForwarder`) with
  `VantaNoAlert=true`, so Vanta excludes them from compliance tests we cannot remediate
  (retention blocked by GRLOGGROUPPOLICY; CloudWatch alarms blocked by StackSet drift).
- **Vanta Auditor Role (Management Account)** -- Attaches Identity Store read permissions
  to the `vanta-auditor` role so Vanta can audit IAM Identity Center. Distributes the
  Vanta external ID to all member accounts via a CloudFormation StackSet so that
  [terraform-aws-iso27001](https://github.com/infrahouse/terraform-aws-iso27001) can
  create the `vanta-auditor` role locally without cross-account lookups.
- **ISO 27001 / SOC 2 Compliance** -- Enforces 365-day log retention by default.
- **Multi-Region Support** -- Scans configurable regions across all active member accounts.

## Quick Start

```hcl
module "org_governance" {
  source  = "registry.infrahouse.com/infrahouse/org-governance/aws"
  version = "0.6.0"

  alarm_emails      = ["security@example.com"]
  vanta_external_id = var.vanta_external_id
}
```

Deploy this module in the **management account** where AWS Organizations APIs are available.
