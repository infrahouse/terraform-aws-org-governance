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


