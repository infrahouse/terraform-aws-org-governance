import json
import random
from os import path as osp, remove
from shutil import rmtree
from textwrap import dedent

import botocore.config
import pytest
from infrahouse_core.aws import get_session
from infrahouse_core.aws.cloudwatch_log_group import CloudWatchLogGroup
from pytest_infrahouse import terraform_apply

from tests.conftest import (
    LOG,
    TERRAFORM_ROOT_DIR,
)

TEST_LOG_GROUP = "/aws/lambda/aws-controltower-test-retention"

# Valid CloudWatch retention values excluding 365 (the usual default)
VALID_RETENTION_DAYS = [
    1,
    3,
    5,
    7,
    14,
    30,
    60,
    90,
    120,
    150,
    180,
    400,
    545,
    731,
    1096,
    1827,
    2192,
    2557,
    2922,
    3288,
    3653,
]


@pytest.mark.parametrize("aws_provider_version", ["~> 6.0"], ids=["aws-6"])
def test_module(
    test_role_arn,
    keep_after,
    aws_region,
    aws_provider_version,
    boto3_session,
):
    terraform_module_dir = osp.join(TERRAFORM_ROOT_DIR, "org-governance")
    state_files = [
        osp.join(terraform_module_dir, ".terraform"),
        osp.join(terraform_module_dir, ".terraform.lock.hcl"),
    ]

    for state_file in state_files:
        try:
            if osp.isdir(state_file):
                rmtree(state_file)
            elif osp.isfile(state_file):
                remove(state_file)
        except FileNotFoundError:
            pass

    target_retention = random.choice(VALID_RETENTION_DAYS)
    LOG.info("Target retention for this run: %d days", target_retention)

    with open(osp.join(terraform_module_dir, "terraform.tfvars"), "w") as fp:
        fp.write(dedent(f"""
                    region = "{aws_region}"
                    cloudwatch_retention_days = {target_retention}
                    """))
        if test_role_arn:
            fp.write(dedent(f"""
                    role_arn = "{test_role_arn}"
                    """))

    with open(osp.join(terraform_module_dir, "terraform.tf"), "w") as fp:
        fp.write(dedent(f"""
                terraform {{
                  required_version = "~> 1.5"
                  //noinspection HILUnresolvedReference
                  required_providers {{
                    aws = {{
                      source  = "hashicorp/aws"
                      version = "{aws_provider_version}"
                    }}
                  }}
                }}
                """))

    with terraform_apply(
        terraform_module_dir,
        destroy_after=not keep_after,
        json_output=True,
    ) as tf_output:
        LOG.info("%s", json.dumps(tf_output, indent=4))

        function_name = tf_output["enforce_log_retention_function_name"]["value"]

        # Pick a member account (not the management account)
        org_accounts = tf_output["organization_accounts"]["value"]
        mgmt_account_id = boto3_session.client("sts").get_caller_identity()["Account"]
        member_account_id = next(
            acct_id
            for acct_id, acct in org_accounts.items()
            if acct_id != mgmt_account_id and acct["status"] == "ACTIVE"
        )
        LOG.info(
            "Using member account %s (%s) for test",
            member_account_id,
            org_accounts[member_account_id]["name"],
        )

        # Assume AWSControlTowerExecution in the member account
        ct_role_arn = (
            f"arn:aws:iam::{member_account_id}" ":role/AWSControlTowerExecution"
        )
        ct_session = get_session(
            role_arn=ct_role_arn,
            region=aws_region,
        )
        ct_logs = ct_session.client("logs")
        # Use a retention different from the target so the Lambda
        # must update it
        initial_retention = 14 if target_retention != 14 else 7
        ct_logs.create_log_group(logGroupName=TEST_LOG_GROUP)
        ct_logs.put_retention_policy(
            logGroupName=TEST_LOG_GROUP,
            retentionInDays=initial_retention,
        )
        try:
            lg = CloudWatchLogGroup(TEST_LOG_GROUP, session=ct_session)
            assert lg.retention_in_days == initial_retention
            LOG.info(
                "Before: %s has %d-day retention",
                TEST_LOG_GROUP,
                lg.retention_in_days,
            )

            # Invoke the Lambda (may take minutes scanning all regions)
            LOG.info("Invoking %s", function_name)
            config = botocore.config.Config(
                read_timeout=900,
            )
            lambda_client = boto3_session.client("lambda", config=config)
            invoke_response = lambda_client.invoke(
                FunctionName=function_name,
                InvocationType="RequestResponse",
            )
            payload = json.loads(invoke_response["Payload"].read().decode())
            LOG.info("Lambda response: %s", payload)
            assert invoke_response["StatusCode"] == 200
            assert "FunctionError" not in invoke_response

            # Verify retention was updated to target
            assert lg.retention_in_days == target_retention
            LOG.info(
                "After: %s has %d-day retention",
                TEST_LOG_GROUP,
                lg.retention_in_days,
            )
        finally:
            # Clean up the test log group
            LOG.info("Cleaning up %s", TEST_LOG_GROUP)
            ct_logs.delete_log_group(logGroupName=TEST_LOG_GROUP)
