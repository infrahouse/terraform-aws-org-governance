# Configuration

All variables for the `terraform-aws-org-governance` module.

## Required Variables

### `alarm_emails`

List of email addresses to receive Lambda alarm notifications.

- **Type**: `list(string)`
- **Required**: yes

```hcl
alarm_emails = ["security@example.com", "ops@example.com"]
```

## Optional Variables

### `enforce_log_retention`

Enable the scheduled Lambda that enforces minimum CloudWatch log group retention
across all organization accounts.

- **Type**: `bool`
- **Default**: `true`

Set to `false` to disable the feature without removing the module:

```hcl
enforce_log_retention = false
```

### `cloudwatch_retention_days`

Desired retention in days for CloudWatch log groups created implicitly by AWS
services. The Lambda will set retention to this value on any matching log group.

- **Type**: `number`
- **Default**: `365`
- **Valid values**: 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545,
  731, 1096, 1827, 2192, 2557, 2922, 3288, 3653

```hcl
# ISO 27001 / SOC 2 default
cloudwatch_retention_days = 365

# Shorter retention for non-production
cloudwatch_retention_days = 90
```

### `enforce_log_retention_prefixes`

Log group name prefixes to target for retention enforcement. Only log groups
matching these prefixes will be updated.

- **Type**: `list(string)`
- **Default**:
    ```hcl
    [
      "/aws/lambda/aws-controltower-",
      "/aws/guardduty/",
      "StackSet-AWSControlTowerBP-",
    ]
    ```

Add custom prefixes to extend coverage:

```hcl
enforce_log_retention_prefixes = [
  "/aws/lambda/aws-controltower-",
  "/aws/guardduty/",
  "StackSet-AWSControlTowerBP-",
  "/aws/containerinsights/",
]
```

### `enforce_log_retention_schedule`

EventBridge schedule expression for the log retention enforcement Lambda.

- **Type**: `string`
- **Default**: `"rate(1 day)"`

```hcl
# Run every 6 hours
enforce_log_retention_schedule = "rate(6 hours)"

# Run at midnight UTC daily
enforce_log_retention_schedule = "cron(0 0 * * ? *)"
```

### `enforce_log_retention_role_name`

Name of the cross-account IAM role the Lambda assumes in each member account.
The role must exist in every scanned account and trust the management account
root.

- **Type**: `string`
- **Default**: `"InfraHouseGovernance"`

The default targets the `InfraHouseGovernance` role provisioned by
[terraform-aws-iso27001](https://github.com/infrahouse/terraform-aws-iso27001)
>= 2.2.0, which carries permissions for both log-group retention/tagging and
Lambda function tagging. The variable name retains the historical
`log_retention` prefix for backward compatibility; a future major release will
rename it.

### `vanta_exclude_prefixes`

Log group name prefixes to tag with `VantaNoAlert=true`. Used for log groups
where retention cannot be changed to satisfy a Vanta test (e.g., Control Tower
managed log groups blocked by `GRLOGGROUPPOLICY`).

- **Type**: `list(string)`
- **Default**:
    ```hcl
    [
      "/aws/lambda/aws-controltower-",
      "StackSet-AWSControlTowerBP-",
    ]
    ```

### `vanta_exclude_lambda_prefixes`

Lambda function name prefixes to tag with `VantaNoAlert=true`. Used for Lambdas
where Vanta findings (e.g., "Serverless function error rate monitored (AWS)")
cannot be remediated because the Lambda is managed by AWS itself —
`aws-controltower-NotificationForwarder` is deployed into every governed
account/region, and we cannot add CloudWatch alarms without StackSet drift.

- **Type**: `list(string)`
- **Default**:
    ```hcl
    [
      "aws-controltower-",
    ]
    ```

### `vanta_exclude_tag_value`

Value to write for the `VantaNoAlert` tag on newly tagged resources. Vanta only
checks key presence, so the value can document the exclusion reason.
Pre-existing values are never overwritten.

- **Type**: `string`
- **Default**: `"true"`
