"""Vanta S3 CRR exemption reconciler.

Reads vanta-exempt:* tags from S3 buckets and reconciles with the
Vanta per-test deactivation API. Buckets tagged with the exemption
key are deactivated in Vanta; buckets where the tag was removed are
reactivated (drift correction).
"""

import logging
import os
from collections import defaultdict
from typing import Optional

import boto3
import requests
from botocore.exceptions import ClientError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from infrahouse_core.aws import S3Bucket, Secret, get_session
from infrahouse_core.logging import setup_logging

LOG = logging.getLogger(__name__)
setup_logging(LOG)

TEST_ID = "aws-s3-cross-region-replication-enabled"
TAG_KEY = f"vanta-exempt:{TEST_ID}"
MANAGED_PREFIX = "[managed-by:org-governance]"
VANTA_BASE_URL = "https://api.vanta.com/v1"


def _vanta_session() -> requests.Session:
    """Create a requests session with retry-on-429 backoff.

    :return: Configured session.
    :rtype: requests.Session
    """
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429],
        respect_retry_after_header=True,
        allowed_methods=["GET", "POST"],
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _get_vanta_token(secret_arn: str, session: requests.Session) -> str:
    """Fetch Vanta OAuth2 bearer token using client credentials.

    :param secret_arn: ARN of the Secrets Manager secret.
    :type secret_arn: str
    :param session: Requests session with retry configuration.
    :type session: requests.Session
    :return: Bearer access token.
    :rtype: str
    """
    secret = Secret(secret_arn).value
    resp = session.post(
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


def _paginate_vanta(
    url: str,
    headers: dict,
    session: requests.Session,
    params: Optional[dict] = None,
) -> list:
    """Paginate a Vanta API endpoint, return all data items.

    :param url: Full API endpoint URL.
    :type url: str
    :param headers: HTTP headers including Authorization.
    :type headers: dict
    :param session: Requests session with retry configuration.
    :type session: requests.Session
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
        resp = session.get(url, headers=headers, params=p, timeout=30)
        resp.raise_for_status()
        body = resp.json()["results"]
        items.extend(body["data"])
        if not body["pageInfo"]["hasNextPage"]:
            break
        cursor = body["pageInfo"]["endCursor"]
    return items


def _get_bucket_tag(bucket_name: str, session: boto3.Session) -> Optional[str]:
    """Check if bucket has the exemption tag.

    :param bucket_name: S3 bucket name.
    :type bucket_name: str
    :param session: Boto3 session with credentials for the bucket's account.
    :type session: boto3.Session
    :return: Tag value if present, None otherwise. A deleted bucket
        (``NoSuchBucket``) is treated as having no exemption tag.
    :rtype: Optional[str]
    """
    try:
        return S3Bucket(bucket_name, session=session).tags.get(TAG_KEY)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NoSuchBucket":
            return None
        raise


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

    http = _vanta_session()
    token = _get_vanta_token(secret_arn, http)
    headers = {"Authorization": f"Bearer {token}"}

    # Phase 1a: failing entities
    failing = _paginate_vanta(
        f"{VANTA_BASE_URL}/tests/{TEST_ID}/entities", headers, http
    )
    failing_map = {e["displayName"]: e["id"] for e in failing}
    LOG.info("Phase 1a: %d failing entities", len(failing_map))

    # Phase 1b: managed-deactivated entities
    deactivated = _paginate_vanta(
        f"{VANTA_BASE_URL}/tests/{TEST_ID}/entities",
        headers,
        http,
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
        http,
    )
    bucket_account = {r["displayName"]: r["account"] for r in resources}
    LOG.info("Phase 1c: %d S3 resources in Vanta", len(bucket_account))

    # Build per-account bucket lists for Phases 2 and 3
    failing_by_account = defaultdict(list)
    for bucket_name, entity_id in failing_map.items():
        failing_by_account[bucket_account[bucket_name]].append(
            (bucket_name, entity_id)
        )
    deactivated_by_account = defaultdict(list)
    for bucket_name, entity_id in managed_deactivated.items():
        deactivated_by_account[bucket_account[bucket_name]].append(
            (bucket_name, entity_id)
        )
    all_accounts = set(failing_by_account) | set(deactivated_by_account)
    LOG.info("Scanning %d accounts", len(all_accounts))

    # Phase 2 & 3: one STS session per account
    deactivated_count = 0
    reactivated_count = 0
    for account_id in all_accounts:
        role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
        session = get_session(role_arn=role_arn)

        for bucket_name, entity_id in failing_by_account.get(account_id, []):
            tag_value = _get_bucket_tag(bucket_name, session)
            if tag_value:
                reason = f"{MANAGED_PREFIX} {tag_value}"
                http.post(
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

        for bucket_name, entity_id in deactivated_by_account.get(
            account_id, []
        ):
            # A deleted bucket reports no tag, so the stale managed-deactivated
            # entity is reactivated here and drains out on the next run.
            tag_value = _get_bucket_tag(bucket_name, session)
            if tag_value is None:
                http.post(
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
