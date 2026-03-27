# Getting Started

## Prerequisites

- **Terraform** >= 1.5
- **AWS Provider** >= 5.11, < 7.0
- Access to the **AWS Organizations management account** (990466748045)
- The `AWSControlTowerExecution` role must exist in member accounts
  (automatically created by AWS Control Tower)

## First Deployment

1. Add the module to your management account Terraform configuration:

    ```hcl
    module "org_governance" {
      source  = "registry.infrahouse.com/infrahouse/org-governance/aws"
      version = "0.1.0"

      alarm_emails = ["security@example.com"]
    }
    ```

2. Run Terraform:

    ```bash
    terraform init
    terraform plan
    terraform apply
    ```

3. The module creates:
    - A Lambda function (`enforce-log-retention`) that runs daily
    - An EventBridge rule to trigger the Lambda on schedule
    - An IAM role with permissions to list org accounts and assume
      `AWSControlTowerExecution` in each member account
    - CloudWatch alarms for Lambda errors (notifications sent to
      `alarm_emails`)

## Verifying the Deployment

After applying, you can invoke the Lambda manually to verify:

```bash
aws lambda invoke \
  --function-name enforce-log-retention \
  --payload '{}' \
  /dev/stdout
```

Check CloudWatch Logs for the Lambda's output:

```bash
aws logs tail /aws/lambda/enforce-log-retention --follow
```

The Lambda logs which log groups it updates and in which accounts.
