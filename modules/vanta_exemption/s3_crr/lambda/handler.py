"""Vanta S3 CRR exemption reconciler.

Reads vanta-exempt:* tags from S3 buckets and reconciles with the
Vanta per-test deactivation API. Buckets tagged with the exemption
key are deactivated in Vanta; buckets where the tag was removed are
reactivated (drift correction).
"""

import logging
import os
from typing import Optional

import requests
from infrahouse_core.aws import S3Bucket, Secret
from infrahouse_core.logging import setup_logging

LOG = logging.getLogger(__name__)
setup_logging(LOG)

TEST_ID = "aws-s3-cross-region-replication-enabled"
TAG_KEY = f"vanta-exempt:{TEST_ID}"
MANAGED_PREFIX = "[managed-by:org-governance]"
VANTA_BASE_URL = "https://api.vanta.com/v1"


def _get_vanta_token(secret_arn: str) -> str:
    """Fetch Vanta OAuth2 bearer token using client credentials.

    :param secret_arn: ARN of the Secrets Manager secret.
    :type secret_arn: str
    :return: Bearer access token.
    :rtype: str
    """
    secret = Secret(secret_arn).value
    resp = requests.post(
        "https://api.vanta.com/oauth/token",
        json={
            "client_id": secret["client_id"],
            "client_secret": secret["client_secret"],
            "grant_type": "client_credentials",
            "scope": "vanta-api.all:read vanta-api.all:write",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _paginate_vanta(url: str, headers: dict, params: Optional[dict] = None) -> list:
    """Paginate a Vanta API endpoint, return all data items.

    :param url: Full API endpoint URL.
    :type url: str
    :param headers: HTTP headers including Authorization.
    :type headers: dict
    :param params: Additional query parameters.
    :type params: Optional[dict]
    :return: All data items across pages.
    :rtype: list
    """
    items = []
    cursor = None
    while True:
        p = {"pageSize": 100, **(params or {})}
        if cursor:
            p["pageCursor"] = cursor
        resp = requests.get(url, headers=headers, params=p, timeout=30)
        resp.raise_for_status()
        body = resp.json()["results"]
        items.extend(body["data"])
        if not body["pageInfo"]["hasNextPage"]:
            break
        cursor = body["pageInfo"]["endCursor"]
    return items


def _get_bucket_tag(bucket_name: str, account_id: str, role_name: str) -> Optional[str]:
    """Check if bucket has the exemption tag.

    :param bucket_name: S3 bucket name.
    :type bucket_name: str
    :param account_id: 12-digit AWS account ID.
    :type account_id: str
    :param role_name: IAM role name to assume.
    :type role_name: str
    :return: Tag value if present, None otherwise.
    :rtype: Optional[str]
    """
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    return S3Bucket(bucket_name, role_arn=role_arn).tags.get(TAG_KEY)


def handler(event: dict, context: object) -> dict:
    """Reconcile Vanta S3 CRR exemptions with AWS tags.

    :param event: Lambda event payload (unused).
    :type event: dict
    :param context: Lambda runtime context.
    :type context: object
    :return: Counts of deactivated/reactivated entities.
    :rtype: dict
    """
    secret_arn = os.environ["VANTA_SECRET_ARN"]
    role_name = os.environ["ASSUME_ROLE_NAME"]

    token = _get_vanta_token(secret_arn)
    headers = {"Authorization": f"Bearer {token}"}

    # Phase 1a: failing entities
    failing = _paginate_vanta(f"{VANTA_BASE_URL}/tests/{TEST_ID}/entities", headers)
    failing_map = {e["displayName"]: e["id"] for e in failing}
    LOG.info("Phase 1a: %d failing entities", len(failing_map))

    # Phase 1b: managed-deactivated entities
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
    LOG.info(
        "Phase 1b: %d managed-deactivated entities",
        len(managed_deactivated),
    )

    # Phase 1c: S3 integration resources (bucket -> account)
    resources = _paginate_vanta(
        f"{VANTA_BASE_URL}/integrations/aws/resource-kinds/S3/resources",
        headers,
    )
    bucket_account = {r["displayName"]: r["account"] for r in resources}
    LOG.info("Phase 1c: %d S3 resources in Vanta", len(bucket_account))

    # Phase 2: deactivate failing entities that have the tag
    deactivated_count = 0
    for bucket_name, entity_id in failing_map.items():
        account_id = bucket_account[bucket_name]
        tag_value = _get_bucket_tag(bucket_name, account_id, role_name)
        if tag_value:
            reason = f"{MANAGED_PREFIX} {tag_value}"
            requests.post(
                f"{VANTA_BASE_URL}/tests/{TEST_ID}/entities/{entity_id}/deactivate",
                headers=headers,
                json={"deactivateReason": reason},
                timeout=30,
            ).raise_for_status()
            LOG.info(
                "Deactivated %s (%s): %s",
                bucket_name,
                entity_id,
                reason,
            )
            deactivated_count += 1

    # Phase 3: reactivate managed-deactivated entities whose tag was removed
    reactivated_count = 0
    for bucket_name, entity_id in managed_deactivated.items():
        account_id = bucket_account[bucket_name]
        tag_value = _get_bucket_tag(bucket_name, account_id, role_name)
        if tag_value is None:
            requests.post(
                f"{VANTA_BASE_URL}/tests/{TEST_ID}/entities/{entity_id}/reactivate",
                headers=headers,
                timeout=30,
            ).raise_for_status()
            LOG.info(
                "Reactivated %s (%s): tag removed",
                bucket_name,
                entity_id,
            )
            reactivated_count += 1

    LOG.info(
        "Done. Deactivated: %d, Reactivated: %d, "
        "Failing: %d, Managed-deactivated: %d",
        deactivated_count,
        reactivated_count,
        len(failing_map),
        len(managed_deactivated),
    )
    return {
        "deactivated": deactivated_count,
        "reactivated": reactivated_count,
        "failing_total": len(failing_map),
        "managed_deactivated_total": len(managed_deactivated),
    }
