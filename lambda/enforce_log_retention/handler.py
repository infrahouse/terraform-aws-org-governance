"""Enforce CloudWatch log group compliance across the organization.

Deployed in the management account, iterates over all organization
member accounts and regions. Assumes the InfraHouseLogRetention role
(provisioned by terraform-aws-iso27001 in each member account) to
apply changes under least-privilege permissions.

Two passes run per account+region:

1. Retention enforcement — for log groups matching
   ``LOG_GROUP_PREFIXES``, set ``retentionInDays`` to the configured
   value. Targets log groups implicitly created by AWS services
   (GuardDuty, ECS, etc.) and not managed by Terraform.

2. Vanta exclusion tagging — for log groups matching
   ``VANTA_EXCLUDE_PREFIXES``, apply ``VantaNoAlert=true`` so Vanta
   marks them out of scope. Used for Control Tower managed log
   groups where the GRLOGGROUPPOLICY guardrail blocks retention
   changes for any principal other than AWSControlTowerExecution.
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import boto3
from botocore.exceptions import ClientError
from infrahouse_core.aws import get_session
from infrahouse_core.aws.cloudwatch_log_group import CloudWatchLogGroup
from infrahouse_core.logging import setup_logging

LOG = logging.getLogger(__name__)
setup_logging(LOG)

# High enough to parallelize across accounts/regions, low enough to stay
# within Lambda's single-vCPU, 1024-fd limit, and STS rate limits.
MAX_WORKERS = 20

VANTA_EXCLUDE_TAG_KEY = "VantaNoAlert"


def _get_active_account_ids() -> list[str]:
    """Return account IDs of all ACTIVE organization members.

    :return: List of 12-digit AWS account ID strings.
    :rtype: list[str]
    """
    org = boto3.client("organizations", region_name="us-east-1")
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

    :param home_region: Control Tower home region.
    :type home_region: str
    :return: Set of 12-digit AWS account ID strings.
    :rtype: set[str]
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

    :return: List of AWS region name strings.
    :rtype: list[str]
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


def _retention_pass(
    account_id: str,
    region: str,
    role_name: str,
    retention_prefixes: list[str],
    retention_days: int,
) -> int:
    """Enforce retention in one account+region.

    :param account_id: 12-digit AWS account ID.
    :type account_id: str
    :param region: AWS region name.
    :type region: str
    :param role_name: IAM role name to assume in the target account.
    :type role_name: str
    :param retention_prefixes: Log group name prefixes to match.
    :type retention_prefixes: list[str]
    :param retention_days: Desired retention period in days.
    :type retention_days: int
    :return: Number of log groups updated.
    :rtype: int
    """
    session = get_session(
        role_arn=f"arn:aws:iam::{account_id}:role/{role_name}",
        region=region,
        session_name="enforce-log-retention",
    )
    updated = 0
    for pfx in retention_prefixes:
        for lg in CloudWatchLogGroup.list_log_groups(prefix=pfx, session=session):
            current = lg.retention_in_days
            if current != retention_days:
                lg.set_retention(retention_days)
                LOG.info(
                    "Account %s %s: updated %s retention from %s to %d days",
                    account_id,
                    region,
                    lg.log_group_name,
                    current,
                    retention_days,
                )
                updated += 1
    return updated


def _vanta_pass(
    account_id: str,
    region: str,
    role_name: str,
    prefixes: list[str],
    tag_value: str,
) -> int:
    """Tag Vanta-excluded log groups in one account+region.

    The assumed role must have ``logs:TagResource`` and
    ``logs:ListTagsForResource`` in addition to the retention
    permissions.

    Checks for *presence* of the ``VantaNoAlert`` key rather than
    value equality: Vanta only cares that the key exists, so any
    pre-existing value is honored and never overwritten.

    :param account_id: 12-digit AWS account ID.
    :type account_id: str
    :param region: AWS region name.
    :type region: str
    :param role_name: IAM role name to assume in the target account.
    :type role_name: str
    :param prefixes: Log group name prefixes to match.
    :type prefixes: list[str]
    :param tag_value: Value to write for new VantaNoAlert tags.
    :type tag_value: str
    :return: Number of log groups tagged.
    :rtype: int
    """
    session = get_session(
        role_arn=f"arn:aws:iam::{account_id}:role/{role_name}",
        region=region,
        session_name="enforce-log-retention-vanta",
    )
    tagged = 0
    for pfx in prefixes:
        for lg in CloudWatchLogGroup.list_log_groups(prefix=pfx, session=session):
            if VANTA_EXCLUDE_TAG_KEY not in lg.tags:
                lg.set_tag(VANTA_EXCLUDE_TAG_KEY, tag_value)
                LOG.info(
                    "Account %s %s: tagged %s with %s=%s",
                    account_id,
                    region,
                    lg.log_group_name,
                    VANTA_EXCLUDE_TAG_KEY,
                    tag_value,
                )
                tagged += 1
    return tagged


def handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    """Scan log groups across all accounts and regions.

    Runs the two passes in separate ThreadPoolExecutor phases so a
    failure in one cannot cancel pending work in the other. Retention
    is the compliance-critical path and keeps fail-fast semantics;
    Vanta tagging is cosmetic (it only hides false positives in
    Vanta's alert feed) and runs best-effort — per-worker exceptions
    are logged and counted, but do not halt the phase.

    :param event: Lambda event payload (unused).
    :type event: dict[str, Any]
    :param context: Lambda runtime context.
    :type context: Any
    :return: Counts of updated, tagged, and errored log groups.
    :rtype: dict[str, int]
    """
    required_vars = [
        "RETENTION_DAYS",
        "LOG_GROUP_PREFIXES",
        "ASSUME_ROLE_NAME",
        "CONTROL_TOWER_HOME_REGION",
        "VANTA_EXCLUDE_TAG_VALUE",
    ]
    missing = [v for v in required_vars if v not in os.environ]
    if missing:
        raise RuntimeError(f"Required environment variable(s) not set: {', '.join(missing)}")

    retention_days = int(os.environ["RETENTION_DAYS"])
    retention_prefixes = json.loads(os.environ["LOG_GROUP_PREFIXES"])
    vanta_exclude_prefixes = json.loads(os.environ.get("VANTA_EXCLUDE_PREFIXES", "[]"))
    vanta_tag_value = os.environ["VANTA_EXCLUDE_TAG_VALUE"]
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
    targets = [(a, r) for a in account_ids for r in regions]
    LOG.info(
        "Scanning %d accounts across %d regions (%d workers)",
        len(account_ids),
        len(regions),
        MAX_WORKERS,
    )

    # Phase 1: retention enforcement — fail fast on any worker error
    # so the operator is alerted and can fix the root cause before
    # the next daily run. Retries are intentionally not implemented.
    total_updated = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                _retention_pass,
                account_id,
                region,
                role_name,
                retention_prefixes,
                retention_days,
            ): (account_id, region)
            for account_id, region in targets
        }
        for future in as_completed(futures):
            try:
                total_updated += future.result()
            except ClientError:
                for f in futures:
                    f.cancel()
                raise

    # Phase 2: Vanta tagging — best-effort. A failure here does not
    # change compliance posture (retention is already enforced), so
    # log and continue instead of aborting the remaining workers.
    total_tagged = 0
    vanta_errors = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                _vanta_pass,
                account_id,
                region,
                role_name,
                vanta_exclude_prefixes,
                vanta_tag_value,
            ): (account_id, region)
            for account_id, region in targets
        }
        for future in as_completed(futures):
            account_id, region = futures[future]
            try:
                total_tagged += future.result()
            except ClientError:
                LOG.exception(
                    "Vanta tagging failed for account %s region %s",
                    account_id,
                    region,
                )
                vanta_errors += 1

    LOG.info(
        "Done. Updated %d log group(s), tagged %d for Vanta exclusion "
        "(%d vanta errors).",
        total_updated,
        total_tagged,
        vanta_errors,
    )
    return {
        "updated": total_updated,
        "tagged": total_tagged,
        "vanta_errors": vanta_errors,
    }
