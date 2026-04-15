#!/usr/bin/env bash
#
# Trace who changed the retention on a CloudWatch log group via
# CloudTrail. Useful for debugging "something keeps resetting my
# retention" scenarios (e.g., Control Tower baselines fighting the
# enforce-log-retention Lambda).
#
# Requires AWS credentials for the target account already in env/profile.
# Run from the account that owns the log group.

set -euo pipefail

LOG_GROUP="${LOG_GROUP:-/aws/lambda/aws-controltower-NotificationForwarder}"
REGION="${REGION:-us-west-2}"
START="${START:-2026-04-15T04:00:00Z}"
END="${END:-2026-04-15T18:00:00Z}"

echo "Log group: ${LOG_GROUP}"
echo "Region:    ${REGION}"
echo "Window:    ${START} → ${END}"
echo

{
  printf 'TIME\tRETENTION\tTYPE\tPRINCIPAL\tSESSION_ISSUER\tSOURCE_IP\n'
  aws cloudtrail lookup-events \
    --region "${REGION}" \
    --lookup-attributes AttributeKey=EventName,AttributeValue=PutRetentionPolicy \
    --start-time "${START}" \
    --end-time "${END}" \
    --max-results 50 \
    --query 'Events[].CloudTrailEvent' \
    --output json \
  | jq -r --arg lg "${LOG_GROUP}" '
      .[] | fromjson
      | select(.requestParameters.logGroupName == $lg)
      | [ .eventTime,
          (.requestParameters.retentionInDays | tostring),
          .userIdentity.type,
          (.userIdentity.arn // .userIdentity.invokedBy // "?"),
          (.userIdentity.sessionContext.sessionIssuer.arn // "-"),
          (.sourceIPAddress // "-")
        ]
      | @tsv'
} | column -t -s $'\t'
