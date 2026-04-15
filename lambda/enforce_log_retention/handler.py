"""Enforce minimum CloudWatch log group retention for compliance.

Deployed in the management account, iterates over all organization
member accounts and regions. Assumes the InfraHouseLogRetention role
(provisioned by terraform-aws-iso27001 in each member account) to
apply retention updates under least-privilege permissions.

Only updates log groups matching configured prefixes — these are
implicitly created by AWS services (Control Tower, ECS Container
Insights, GuardDuty, etc.) and not managed by Terraform.
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import boto3
from infrahouse_core.aws import get_session
from infrahouse_core.aws.cloudwatch_log_group import CloudWatchLogGroup
from infrahouse_core.logging import setup_logging

LOG = logging.getLogger(__name__)
setup_logging(LOG)

MAX_WORKERS = 20


def _get_active_account_ids() -> list[str]:
    """Return account IDs of all ACTIVE organization members."""
    org = boto3.client("organizations")
    account_ids = []
    paginator = org.get_paginator("list_accounts")
    for page in paginator.paginate():
        for account in page["Accounts"]:
            if account["Status"] == "ACTIVE":
                account_ids.append(account["Id"])
    return account_ids


def _get_ct_enrolled_account_ids(home_region: str) -> set[str]:
    """Return account IDs governed by Control Tower baselines.

    An account is "governed" if at least one enabled baseline targets
    it — either directly (e.g., AuditBaseline on the Audit account,
    LogArchiveBaseline on the Log Archive account) or via inheritance
    from its parent OU (AWSControlTowerBaseline on a registered OU
    propagates to each member account as a child baseline, surfaced
    by includeChildren=True). Accounts in the organization but
    outside CT's scope — e.g., externally-owned accounts that were
    never enrolled — have no enabled baselines and are excluded.
    """
    ct = boto3.client("controltower", region_name=home_region)
    enrolled: set[str] = set()
    paginator = ct.get_paginator("list_enabled_baselines")
    for page in paginator.paginate(includeChildren=True):
        for eb in page["enabledBaselines"]:
            target = eb["targetIdentifier"]
            # OU targets are the parents of the per-account children
            # we get via includeChildren — we only want the accounts.
            if ":account/" in target:
                enrolled.add(target.rsplit("/", 1)[-1])
    return enrolled


def _get_governed_regions() -> list[str]:
    """Return region names governed by the Control Tower landing zone.

    Scoping to governed regions (instead of every enabled region in the
    caller account) avoids hitting opt-in regions where STS endpoints
    are unreachable from the Lambda's network.
    """
    # Control Tower APIs are regional — the landing zone is only
    # visible in its home region, which may differ from the Lambda's
    # own region.
    ct = boto3.client(
        "controltower", region_name=os.environ["CONTROL_TOWER_HOME_REGION"]
    )
    landing_zones = ct.list_landing_zones()["landingZones"]
    if not landing_zones:
        raise RuntimeError("No Control Tower landing zone found in this account")
    lz = ct.get_landing_zone(landingZoneIdentifier=landing_zones[0]["arn"])[
        "landingZone"
    ]
    return list(lz["manifest"]["governedRegions"])


def _enforce_in_account_region(
    account_id: str,
    region: str,
    role_name: str,
    prefixes: list[str],
    retention_days: int,
) -> int:
    """Enforce log retention in one account+region. Returns count of updated groups."""
    session = get_session(
        role_arn=f"arn:aws:iam::{account_id}:role/{role_name}",
        region=region,
        session_name="enforce-log-retention",
    )
    updated = 0
    for pfx in prefixes:
        for lg in CloudWatchLogGroup.list_log_groups(prefix=pfx, session=session):
            current = lg.retention_in_days
            if current != retention_days:
                LOG.info(
                    "Account %s %s: updating %s " "retention from %s to %d days",
                    account_id,
                    region,
                    lg.log_group_name,
                    current,
                    retention_days,
                )
                lg.set_retention(retention_days)
                updated += 1
    return updated


def handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    """Scan log groups across all accounts and regions."""
    retention_days = int(os.environ["RETENTION_DAYS"])
    prefixes = json.loads(os.environ["LOG_GROUP_PREFIXES"])
    role_name = os.environ["ASSUME_ROLE_NAME"]
    home_region = os.environ["CONTROL_TOWER_HOME_REGION"]
    excluded = set(json.loads(os.environ.get("EXCLUDED_ACCOUNTS", "[]")))

    active_accounts = set(_get_active_account_ids())
    enrolled_accounts = _get_ct_enrolled_account_ids(home_region)
    unenrolled = active_accounts - enrolled_accounts
    if unenrolled:
        LOG.info(
            "Skipping %d account(s) not enrolled in Control Tower: %s",
            len(unenrolled),
            sorted(unenrolled),
        )
    explicitly_excluded = active_accounts & excluded
    if explicitly_excluded:
        LOG.info(
            "Skipping %d account(s) from excluded_accounts: %s",
            len(explicitly_excluded),
            sorted(explicitly_excluded),
        )

    account_ids = sorted((active_accounts & enrolled_accounts) - excluded)
    regions = _get_governed_regions()
    LOG.info(
        "Scanning %d accounts across %d regions (%d workers)",
        len(account_ids),
        len(regions),
        MAX_WORKERS,
    )

    total_updated = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                _enforce_in_account_region,
                account_id,
                region,
                role_name,
                prefixes,
                retention_days,
            ): (account_id, region)
            for account_id in account_ids
            for region in regions
        }
        for future in as_completed(futures):
            account_id, region = futures[future]
            # Let exceptions propagate — better to crash than mute
            total_updated += future.result()

    LOG.info("Done. Updated %d log group(s).", total_updated)
    return {"updated": total_updated}
