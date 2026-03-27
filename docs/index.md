# terraform-aws-org-governance

Centralized AWS Organizations governance module deployed in the management account.

## Overview

Certain compliance and governance tasks can only be performed from the AWS Organizations
management account -- they require `AWSControlTowerExecution` role assumption into member
accounts, or AWS Organizations API calls restricted to the management account.

This module provides a centralized deployment model for those tasks.

## Features

- **CloudWatch Log Retention Enforcement** -- A scheduled Lambda that scans all organization
  member accounts and enforces minimum log retention on CloudWatch log groups created by AWS
  services (Control Tower, GuardDuty, etc.). Works around Control Tower's mandatory SCP
  (`GRLOGGROUPPOLICY`) by assuming `AWSControlTowerExecution`.
- **ISO 27001 / SOC 2 Compliance** -- Enforces 365-day log retention by default.
- **Multi-Region Support** -- Scans configurable regions across all active member accounts.

## Quick Start

```hcl
module "org_governance" {
  source  = "registry.infrahouse.com/infrahouse/org-governance/aws"
  version = "0.2.1"

  alarm_emails = ["security@example.com"]
}
```

Deploy this module in the **management account** where AWS Organizations APIs are available.
