import io
import json
import random
import time
import zipfile
from os import path as osp, remove
from shutil import rmtree
from textwrap import dedent

import botocore.config
import pytest
from botocore.exceptions import ClientError
from infrahouse_core.aws import get_session
from infrahouse_core.aws.cloudwatch_log_group import CloudWatchLogGroup
from pytest_infrahouse import terraform_apply

from tests.conftest import (
    LOG,
    TERRAFORM_ROOT_DIR,
)

TEST_RETENTION_LOG_GROUP = "/test/retention/enforce-test"
TEST_VANTA_LOG_GROUP = "/aws/lambda/aws-controltower-test-retention"
VANTA_NO_ALERT_TAG = "VantaNoAlert"
LAMBDA_BASIC_EXEC_POLICY_ARN = (
    "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
)

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


def _build_minimal_lambda_zip() -> bytes:
    """Return a zip with a no-op Python handler suitable for create_function."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("handler.py", "def handler(event, context):\n    return {}\n")
    return buf.getvalue()


def _create_test_lambda(ct_session, function_name: str) -> dict:
    """Create a synthetic Lambda function in the member account.

    Returns a dict with the resources to clean up, suitable to pass
    to :func:`_destroy_test_lambda`.
    """
    iam = ct_session.client("iam")
    lam = ct_session.client("lambda")
    role_name = f"{function_name}-exec"
    trust_policy = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
    )
    iam.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=trust_policy,
        Description="Temporary role for terraform-aws-org-governance test",
    )
    iam.attach_role_policy(
        RoleName=role_name,
        PolicyArn=LAMBDA_BASIC_EXEC_POLICY_ARN,
    )
    role_arn = iam.get_role(RoleName=role_name)["Role"]["Arn"]
    # IAM role propagation to Lambda — empirically ~10s; retry with
    # backoff to avoid flakes.
    zip_bytes = _build_minimal_lambda_zip()
    last_err = None
    for attempt in range(6):
        try:
            lam.create_function(
                FunctionName=function_name,
                Runtime="python3.12",
                Role=role_arn,
                Handler="handler.handler",
                Code={"ZipFile": zip_bytes},
                PackageType="Zip",
                Timeout=3,
            )
            break
        except ClientError as err:
            if err.response["Error"]["Code"] != "InvalidParameterValueException":
                raise
            last_err = err
            time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(
            f"Lambda did not see role {role_arn} after retries: {last_err}"
        )
    return {"role_name": role_name, "function_name": function_name}


def _destroy_test_lambda(ct_session, resources: dict) -> None:
    iam = ct_session.client("iam")
    lam = ct_session.client("lambda")
    try:
        lam.delete_function(FunctionName=resources["function_name"])
    except ClientError as err:
        if err.response["Error"]["Code"] != "ResourceNotFoundException":
            LOG.warning("Failed to delete Lambda: %s", err)
    try:
        iam.detach_role_policy(
            RoleName=resources["role_name"],
            PolicyArn=LAMBDA_BASIC_EXEC_POLICY_ARN,
        )
    except ClientError as err:
        if err.response["Error"]["Code"] != "NoSuchEntity":
            LOG.warning("Failed to detach role policy: %s", err)
    try:
        iam.delete_role(RoleName=resources["role_name"])
    except ClientError as err:
        if err.response["Error"]["Code"] != "NoSuchEntity":
            LOG.warning("Failed to delete role: %s", err)


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
        # must update the retention-pass group, and so we can prove
        # the vanta-pass group was left alone.
        initial_retention = 14 if target_retention != 14 else 7

        # Group 1: matches enforce_log_retention_prefixes — the
        # retention pass must rewrite it to target_retention.
        ct_logs.create_log_group(logGroupName=TEST_RETENTION_LOG_GROUP)
        ct_logs.put_retention_policy(
            logGroupName=TEST_RETENTION_LOG_GROUP,
            retentionInDays=initial_retention,
        )
        # Group 2: matches vanta_exclude_prefixes — the vanta pass
        # must tag it with VantaNoAlert, and the retention pass must
        # NOT touch it (regression guard against the two lists
        # cross-contaminating).
        ct_logs.create_log_group(logGroupName=TEST_VANTA_LOG_GROUP)
        ct_logs.put_retention_policy(
            logGroupName=TEST_VANTA_LOG_GROUP,
            retentionInDays=initial_retention,
        )
        # Synthetic Lambda matching vanta_exclude_lambda_prefixes
        # default (``aws-controltower-``). The Vanta Lambda pass must
        # tag this function with VantaNoAlert.
        test_lambda_name = f"aws-controltower-test-vanta-{random.randint(10000, 99999)}"
        lambda_resources = _create_test_lambda(ct_session, test_lambda_name)
        ct_lambda = ct_session.client("lambda")
        try:
            retention_lg = CloudWatchLogGroup(
                TEST_RETENTION_LOG_GROUP, session=ct_session
            )
            vanta_lg = CloudWatchLogGroup(TEST_VANTA_LOG_GROUP, session=ct_session)
            assert retention_lg.retention_in_days == initial_retention
            assert vanta_lg.retention_in_days == initial_retention
            assert VANTA_NO_ALERT_TAG not in vanta_lg.tags
            LOG.info(
                "Before: retention=%d on both %s and %s",
                initial_retention,
                TEST_RETENTION_LOG_GROUP,
                TEST_VANTA_LOG_GROUP,
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

            # Retention pass: rewrote the retention group.
            assert retention_lg.retention_in_days == target_retention
            LOG.info(
                "After retention pass: %s has %d-day retention",
                TEST_RETENTION_LOG_GROUP,
                retention_lg.retention_in_days,
            )

            # Vanta pass: tagged the CT group, and the retention
            # pass did not leak onto it.
            assert VANTA_NO_ALERT_TAG in vanta_lg.tags
            assert vanta_lg.retention_in_days == initial_retention
            LOG.info(
                "After vanta pass: %s has tag %s=%s, retention unchanged at %d",
                TEST_VANTA_LOG_GROUP,
                VANTA_NO_ALERT_TAG,
                vanta_lg.tags[VANTA_NO_ALERT_TAG],
                vanta_lg.retention_in_days,
            )

            # Vanta Lambda pass: tagged the synthetic Lambda matching
            # the aws-controltower- prefix.
            fn_arn = ct_lambda.get_function(FunctionName=test_lambda_name)[
                "Configuration"
            ]["FunctionArn"]
            fn_tags = ct_lambda.list_tags(Resource=fn_arn).get("Tags", {})
            assert VANTA_NO_ALERT_TAG in fn_tags, (
                f"Expected {VANTA_NO_ALERT_TAG} on {test_lambda_name}, "
                f"got tags: {fn_tags}"
            )
            LOG.info(
                "After vanta lambda pass: %s has tag %s=%s",
                test_lambda_name,
                VANTA_NO_ALERT_TAG,
                fn_tags[VANTA_NO_ALERT_TAG],
            )
        finally:
            LOG.info("Cleaning up %s", TEST_RETENTION_LOG_GROUP)
            ct_logs.delete_log_group(logGroupName=TEST_RETENTION_LOG_GROUP)
            LOG.info("Cleaning up %s", TEST_VANTA_LOG_GROUP)
            ct_logs.delete_log_group(logGroupName=TEST_VANTA_LOG_GROUP)
            LOG.info("Cleaning up Lambda %s", test_lambda_name)
            _destroy_test_lambda(ct_session, lambda_resources)
