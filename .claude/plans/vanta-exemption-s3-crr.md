# Plan: Vanta per-test exemption reconciler (S3 CRR)

**Linear ticket:** INF-1539
**Module:** terraform-aws-org-governance
**Current version:** 0.7.1
**Submodule path:** `modules/vanta_exemption/s3_crr/`

## Context

`terraform-aws-s3-bucket` stamps `vanta-exempt:<test-slug> = <reason>` tags on
buckets that should be exempt from a specific Vanta test. This submodule deploys
a Lambda reconciler that reads those tags and calls the Vanta per-test
deactivation API to align Vanta's state with the declared intent in AWS.

First target: `aws-s3-cross-region-replication-enabled` (244 failing entities,
~143 should be exempt). The pattern is designed so that future Vanta tests get
their own submodule under `modules/vanta_exemption/`.

## API surface (confirmed live)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/tests/{testId}/entities` | GET | List entities; paginate with `pageSize` + `pageCursor`; default returns FAILING only |
| `/v1/tests/{testId}/entities/{entityId}/deactivate` | POST | Body: `{"deactivateReason": "..."}` (required, min 1 char). Returns 202 |
| `/v1/tests/{testId}/entities/{entityId}/reactivate` | POST | No body. Returns 202 |
| `/v1/integrations/aws/resource-kinds/S3/resources` | GET | Lists all S3 resources with `account`, `displayName`, etc.; pagination only, no filters |

**Entity matching:** Vanta entity `displayName` = S3 bucket name. S3 names are
globally unique, so `displayName` is an unambiguous join key. Entity IDs are
Vanta-internal MongoDB ObjectIDs (e.g., `S3-69fe5fd15485099121bce1b8`) -- stable
across test runs (confirmed by deactivating `tinyfish-tempo-traces-sandbox` and
re-running the test; entity kept its ID and DEACTIVATED status).

**Entity status filtering:** The default `list_test_entities` call returns FAILING
entities only. Deactivated entities require a separate query with
`entityStatus=DEACTIVATED` (not exposed in the MCP connector but available in the
REST API).

## Reconciliation logic (Vanta-first)

```
Phase 1: Build lookup tables
  1a. Paginate GET /v1/tests/{TEST_ID}/entities (FAILING)
      -> dict: bucket_name -> entity_id  (for deactivation candidates)
  1b. Paginate GET /v1/tests/{TEST_ID}/entities?entityStatus=DEACTIVATED
      -> filter to entries where deactivatedReason starts with MANAGED_PREFIX
      -> dict: bucket_name -> entity_id  (for reactivation candidates)
  1c. Paginate GET /v1/integrations/aws/resource-kinds/S3/resources
      -> dict: bucket_name -> account_id  (for AWS tag lookups)

Phase 2: Check AWS tags, deactivate
  For each failing bucket_name:
    - Look up account_id from 1c
    - Assume role into that account
    - s3:GetBucketTagging -> check for tag key "vanta-exempt:{TEST_SLUG}"
    - If tagged: POST /deactivate with reason = "{MANAGED_PREFIX} {tag_value}"

Phase 3: Check AWS tags, reactivate (drift correction)
  For each managed-deactivated bucket_name:
    - Look up account_id from 1c
    - Assume role into that account
    - s3:GetBucketTagging -> check for tag key "vanta-exempt:{TEST_SLUG}"
    - If tag absent: POST /reactivate

Phase 4: Report
  Log counts: deactivated, reactivated, errors, skipped (manual deactivations)
```

**Constants:**
- `TEST_ID = "aws-s3-cross-region-replication-enabled"`
- `TEST_SLUG = "aws-s3-cross-region-replication-enabled"`
- `TAG_PREFIX = "vanta-exempt:"`
- `MANAGED_PREFIX = "[managed-by:org-governance]"`

**Scale per run:**
- ~4 API calls to paginate integration_resources (309 S3 resources)
- ~3 API calls to paginate test entities (244 entities at 100/page)
- ~1-3 API calls to paginate deactivated entities
- 1 `GetBucketTagging` call per failing + managed-deactivated entity
- 1 deactivate/reactivate call per entity that needs state change

## Terraform structure

```
modules/vanta_exemption/s3_crr/
  handler.py            # Lambda code
  variables.tf          # Inputs
  main.tf               # Lambda module, EventBridge, IAM
  outputs.tf            # Lambda ARN, function name
```

### variables.tf

```hcl
variable "alarm_emails" {
  description = "Email addresses for Lambda alarm notifications."
  type        = list(string)
}

variable "vanta_secret_arn" {
  description = <<-EOT
    ARN of the Secrets Manager secret containing Vanta API credentials.
    The secret value must be a JSON object with keys:
      client_id     - Vanta OAuth2 client ID
      client_secret - Vanta OAuth2 client secret
  EOT
  type = string
}

variable "assume_role_name" {
  description = <<-EOT
    Name of the cross-account IAM role the Lambda assumes in each
    member account to read S3 bucket tags. Must have s3:GetBucketTagging.
  EOT
  type    = string
  default = "InfraHouseGovernance"
}

variable "schedule" {
  description = "EventBridge schedule expression for the reconciler."
  type        = string
  default     = "rate(1 hour)"
}

variable "tags" {
  description = "Tags to apply to all resources."
  type        = map(string)
  default     = {}
}
```

### main.tf

Uses the existing `infrahouse/lambda-monitored/aws` module pattern (same as
`enforce_log_retention`):

```hcl
module "vanta_s3_crr_reconciler" {
  source  = "registry.infrahouse.com/infrahouse/lambda-monitored/aws"
  version = "1.1.0"

  function_name     = "vanta-s3-crr-reconciler"
  lambda_source_dir = "${path.module}/lambda"
  handler           = "handler.handler"
  source_code_files = ["handler.py"]
  timeout           = 900
  memory_size       = 256

  alarm_emails                         = var.alarm_emails
  memory_utilization_threshold_percent = 80

  environment_variables = {
    VANTA_SECRET_ARN = var.vanta_secret_arn
    ASSUME_ROLE_NAME = var.assume_role_name
  }

  additional_iam_policy_arns = [
    aws_iam_policy.vanta_s3_crr.arn,
  ]

  tags = var.tags
}
```

### IAM policy

```hcl
data "aws_iam_policy_document" "vanta_s3_crr" {
  # Read Vanta API credentials from Secrets Manager
  statement {
    sid       = "ReadVantaSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.vanta_secret_arn]
  }

  # Assume role in member accounts for s3:GetBucketTagging
  statement {
    sid       = "AssumeRoleInMemberAccounts"
    effect    = "Allow"
    actions   = ["sts:AssumeRole"]
    resources = ["arn:aws:iam::*:role/${var.assume_role_name}"]
  }
}

resource "aws_iam_policy" "vanta_s3_crr" {
  name_prefix = "vanta-s3-crr-reconciler-"
  description = "Vanta S3 CRR reconciler: read secret + assume cross-account role"
  policy      = data.aws_iam_policy_document.vanta_s3_crr.json
  tags        = var.tags
}
```

### EventBridge

```hcl
resource "aws_cloudwatch_event_rule" "vanta_s3_crr" {
  name_prefix         = "vanta-s3-crr-"
  description         = "Hourly Vanta S3 CRR exemption reconciliation"
  schedule_expression = var.schedule
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "vanta_s3_crr" {
  rule = aws_cloudwatch_event_rule.vanta_s3_crr.name
  arn  = module.vanta_s3_crr_reconciler.lambda_function_arn
}

resource "aws_lambda_permission" "vanta_s3_crr" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.vanta_s3_crr_reconciler.lambda_function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.vanta_s3_crr.arn
}
```

### Parent module wiring (org-governance root)

New file `vanta_s3_crr.tf` at the module root:

```hcl
variable "vanta_s3_crr_enabled" {
  description = "Enable the Vanta S3 CRR exemption reconciler."
  type        = bool
  default     = false
}

variable "vanta_api_secret_arn" {
  description = <<-EOT
    ARN of the Secrets Manager secret containing Vanta API credentials
    (client_id + client_secret). Required when vanta_s3_crr_enabled = true.
  EOT
  type    = string
  default = null
}

variable "vanta_s3_crr_schedule" {
  description = "EventBridge schedule for the S3 CRR reconciler."
  type        = string
  default     = "rate(1 hour)"
}

module "vanta_s3_crr" {
  count  = var.vanta_s3_crr_enabled ? 1 : 0
  source = "./modules/vanta_exemption/s3_crr"

  alarm_emails     = var.alarm_emails
  vanta_secret_arn = var.vanta_api_secret_arn
  assume_role_name = var.enforce_log_retention_role_name
  schedule         = var.vanta_s3_crr_schedule
  tags             = local.default_module_tags
}
```

## Lambda code: handler.py

Python, using `requests` for Vanta API calls and `boto3` for AWS.

### Dependencies

- `boto3` (Lambda runtime)
- `requests` (bundle in Lambda package or use `urllib3` from botocore)
- `infrahouse_core` (already used by enforce_log_retention for `get_session`)

### Pseudocode

```python
"""Vanta S3 CRR exemption reconciler.

Reads vanta-exempt:* tags from S3 buckets and reconciles with the
Vanta per-test deactivation API.
"""

import json
import logging
import os
import boto3
import requests
from infrahouse_core.aws import get_session

LOG = logging.getLogger(__name__)

TEST_ID = "aws-s3-cross-region-replication-enabled"
TAG_KEY = f"vanta-exempt:{TEST_ID}"
MANAGED_PREFIX = "[managed-by:org-governance]"
VANTA_BASE_URL = "https://api.vanta.com/v1"


def _get_vanta_token(secret_arn: str) -> str:
    """Fetch Vanta OAuth2 bearer token using client credentials."""
    sm = boto3.client("secretsmanager")
    secret = json.loads(sm.get_secret_value(SecretId=secret_arn)["SecretString"])
    resp = requests.post(
        "https://api.vanta.com/oauth/token",
        json={
            "client_id": secret["client_id"],
            "client_secret": secret["client_secret"],
            "grant_type": "client_credentials",
            "scope": "vanta-api.all:read vanta-api.all:write",
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _paginate_vanta(url: str, headers: dict, params: dict = None) -> list:
    """Paginate a Vanta API endpoint, return all data items."""
    items = []
    cursor = None
    while True:
        p = {"pageSize": 100, **(params or {})}
        if cursor:
            p["pageCursor"] = cursor
        resp = requests.get(url, headers=headers, params=p)
        resp.raise_for_status()
        body = resp.json()["results"]
        items.extend(body["data"])
        if not body["pageInfo"]["hasNextPage"]:
            break
        cursor = body["pageInfo"]["endCursor"]
    return items


def _get_bucket_tag(bucket_name: str, account_id: str,
                    role_name: str) -> str | None:
    """Check if bucket has the exemption tag, return value or None."""
    session = get_session(
        role_arn=f"arn:aws:iam::{account_id}:role/{role_name}",
        region="us-east-1",  # S3 tagging API is global
        session_name="vanta-s3-crr",
    )
    s3 = session.client("s3")
    try:
        tags = s3.get_bucket_tagging(Bucket=bucket_name)
        for tag in tags.get("TagSet", []):
            if tag["Key"] == TAG_KEY:
                return tag["Value"]
    except s3.exceptions.ClientError as e:
        if "NoSuchTagConfiguration" in str(e):
            return None
        raise
    return None


def handler(event, context):
    secret_arn = os.environ["VANTA_SECRET_ARN"]
    role_name = os.environ["ASSUME_ROLE_NAME"]

    token = _get_vanta_token(secret_arn)
    headers = {"Authorization": f"Bearer {token}"}

    # Phase 1a: failing entities
    failing = _paginate_vanta(
        f"{VANTA_BASE_URL}/tests/{TEST_ID}/entities", headers
    )
    failing_map = {e["displayName"]: e["id"] for e in failing}

    # Phase 1b: deactivated entities (managed by us)
    deactivated = _paginate_vanta(
        f"{VANTA_BASE_URL}/tests/{TEST_ID}/entities",
        headers,
        params={"entityStatus": "DEACTIVATED"},
    )
    managed_deactivated = {
        e["displayName"]: e["id"]
        for e in deactivated
        if e.get("deactivatedReason", "").startswith(MANAGED_PREFIX)
    }

    # Phase 1c: S3 integration resources (bucket -> account)
    resources = _paginate_vanta(
        f"{VANTA_BASE_URL}/integrations/aws/resource-kinds/S3/resources",
        headers,
    )
    bucket_account = {r["displayName"]: r["account"] for r in resources}

    # Phase 2: deactivate failing entities that have the tag
    deactivated_count = 0
    for bucket_name, entity_id in failing_map.items():
        account_id = bucket_account.get(bucket_name)
        if not account_id:
            LOG.warning("No account found for bucket %s, skipping", bucket_name)
            continue
        tag_value = _get_bucket_tag(bucket_name, account_id, role_name)
        if tag_value:
            reason = f"{MANAGED_PREFIX} {tag_value}"
            requests.post(
                f"{VANTA_BASE_URL}/tests/{TEST_ID}/entities/{entity_id}/deactivate",
                headers=headers,
                json={"deactivateReason": reason},
            ).raise_for_status()
            LOG.info("Deactivated %s (%s): %s", bucket_name, entity_id, reason)
            deactivated_count += 1

    # Phase 3: reactivate managed-deactivated entities whose tag was removed
    reactivated_count = 0
    for bucket_name, entity_id in managed_deactivated.items():
        account_id = bucket_account.get(bucket_name)
        if not account_id:
            LOG.warning("No account found for bucket %s, skipping", bucket_name)
            continue
        tag_value = _get_bucket_tag(bucket_name, account_id, role_name)
        if tag_value is None:
            requests.post(
                f"{VANTA_BASE_URL}/tests/{TEST_ID}/entities/{entity_id}/reactivate",
                headers=headers,
            ).raise_for_status()
            LOG.info("Reactivated %s (%s): tag removed", bucket_name, entity_id)
            reactivated_count += 1

    LOG.info(
        "Done. Deactivated: %d, Reactivated: %d, "
        "Failing: %d, Managed-deactivated: %d",
        deactivated_count, reactivated_count,
        len(failing_map), len(managed_deactivated),
    )
    return {
        "deactivated": deactivated_count,
        "reactivated": reactivated_count,
        "failing_total": len(failing_map),
        "managed_deactivated_total": len(managed_deactivated),
    }
```

## Cross-account IAM

The Lambda reuses the existing `InfraHouseGovernance` role (provisioned by
`terraform-aws-iso27001 >= 2.2.0`). That role needs `s3:GetBucketTagging`
added to its policy. This is a change in `terraform-aws-iso27001`, not in
this module.

## Secrets Manager

The Vanta API credentials (client_id + client_secret) must be stored in a
Secrets Manager secret before enabling this submodule. The secret ARN is
passed via `vanta_api_secret_arn`. The secret JSON format:

```json
{
  "client_id": "...",
  "client_secret": "..."
}
```

This secret should be created manually or via a separate Terraform resource
(not in this module) since the credentials come from the Vanta dashboard.

## Error handling

- Vanta API errors: `raise_for_status()` on every call. A single failed
  deactivation/reactivation halts the Lambda and triggers the CloudWatch
  alarm. This is intentional -- partial state is visible in logs, and the
  next run is idempotent.
- AWS `GetBucketTagging` errors: `NoSuchTagConfiguration` (bucket has no
  tags) is treated as "no exemption tag" -- not an error. Other S3 errors
  propagate.
- Missing account mapping: logged as warning, bucket skipped. This can
  happen if Vanta's integration_resources lags behind AWS (new bucket not
  yet synced).

## Future submodules

When a new Vanta test needs the same pattern:

1. Create `modules/vanta_exemption/<test_short_name>/`
2. Copy the handler, change `TEST_ID` and `TAG_KEY`
3. Adjust the AWS API call if the resource type is not S3
4. Add a new `vanta_<test>_enabled` variable at the module root
5. Add the test slug to `known_vanta_test_slugs` in `terraform-aws-s3-bucket`

## Version bump

Minor version bump (0.8.0) -- new opt-in submodule, no breaking changes.
