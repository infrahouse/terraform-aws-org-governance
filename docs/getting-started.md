# Getting Started

## Prerequisites

- **Terraform** >= 1.5
- **AWS Provider** >= 6.0, < 7.0
- Access to the **AWS Organizations management account**
- The `InfraHouseLogRetention` role must exist in member accounts,
  provisioned by [terraform-aws-iso27001](https://github.com/infrahouse/terraform-aws-iso27001)
  **>= 2.0.1**. Earlier versions of iso27001 grant only
  `logs:PutRetentionPolicy` / `logs:DescribeLogGroups`, which is not
  enough for the Vanta-exclusion tagging pass — the daily run will
  fail with `AccessDeniedException` on `logs:ListTagsForResource` /
  `logs:TagResource` / `logs:UntagResource`.

## First Deployment

1. Add the module to your management account Terraform configuration:

    ```hcl
    module "org_governance" {
      source  = "registry.infrahouse.com/infrahouse/org-governance/aws"
      version = "0.5.1"

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
      `InfraHouseLogRetention` in each member account
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
