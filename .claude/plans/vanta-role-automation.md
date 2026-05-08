# Vanta Role Automation Plan

## Problem

Vanta auditor roles are manually provisioned per-account in
`github-control/vanta.tf`. Every new AWS account requires a manual
addition, which is easy to forget. The external ID is hardcoded.

## Solution

Move Vanta role management into the standard governance modules so new
accounts get the role automatically:

- **Management account** role: `terraform-aws-org-governance`
- **Member account** roles: `terraform-aws-iso27001` (already exists)
- **External ID distribution**: CloudFormation StackSet
  (SERVICE_MANAGED) pushes `/vanta/external_id` as an SSM parameter
  to every member account. StackSets use the Organizations service
  trust — no pre-existing role needed in member accounts. With
  `auto_deployment` enabled, new accounts receive the parameter
  automatically when they join the target OU.

## Repos Involved

| Repo | Scope |
|------|-------|
| `terraform-aws-org-governance` | Mgmt-account Vanta extras + StackSet for external ID |
| `terraform-aws-iso27001` | Member-account Vanta role (exists) + SSM read for external ID |
| `github-control` | Deprecate/remove `vanta.tf` and `modules/vanta/` |

---

## Work Breakdown

### 1. terraform-aws-org-governance (this repo)

#### 1a. `vanta.tf` — DONE (needs update)
Current state:
- SSM parameter `/vanta/external_id` in management account
- IAM policy with Identity Store read permissions
- Policy attachment to the `vanta-auditor` role

Changes needed:
- Add `aws_cloudformation_stack_set` (SERVICE_MANAGED) that creates
  `/vanta/external_id` SSM parameter in all member accounts
- Add `aws_cloudformation_stack_set_instance` targeting the org root
  (or specific OUs) with auto-deployment enabled
- Keep the direct `aws_ssm_parameter` for the management account
  (StackSets don't deploy to the management account itself)

#### 1b. Variables — DONE
- `vanta_external_id` (required, string)
- `vanta_auditor_role_name` (default `"vanta-auditor"`)

#### 1c. Lambda changes — REVERT
The Lambda does NOT need to propagate SSM parameters — StackSets
handles distribution. Revert:
- Remove `_ssm_pass()` function from `handler.py`
- Remove Phase 4 from `handler()`
- Remove `VANTA_EXTERNAL_ID` from required env vars in handler
- Remove `VANTA_EXTERNAL_ID` env var from `cloudwatch_log_retention.tf`

The Lambda continues to handle Phases 1–3 (log retention, Vanta
log-group tagging, Vanta Lambda tagging) unchanged.

#### 1d. Lambda IAM — NO CHANGE NEEDED
No SSM permissions needed on the Lambda or InfraHouseGovernance role
since StackSets handles distribution via Organizations service trust.

### 2. terraform-aws-iso27001

#### 2a. InfraHouseGovernance role — NO CHANGE NEEDED
No SSM permissions required — the Lambda no longer writes SSM params.

#### 2b. Vanta role external ID from SSM — TODO
Replace `var.vanta_external_id` with an SSM data source:

```hcl
data "aws_ssm_parameter" "vanta_external_id" {
  name = "/vanta/external_id"
}
```

Use `data.aws_ssm_parameter.vanta_external_id.value` in the trust
policy. Remove `var.vanta_external_id` entirely — no fallback needed
because the StackSet guarantees the parameter exists before iso27001
is ever deployed (auto-deployment fires on OU membership, which
happens during Control Tower enrollment, before any Terraform runs).

#### 2c. Identity Store permissions — TODO (member accounts)
The current `vanta_additional_permissions` policy includes Identity
Store actions. These only work in the management account (where IAM
Identity Center lives). In member accounts they are harmless no-ops
but add noise. Consider splitting or leave as-is (harmless, simpler).

### 3. github-control

#### 3a. Deprecate `vanta.tf` + `modules/vanta/` — TODO (after rollout)
Once all accounts have the role via iso27001:
1. Remove all `module "vanta-*"` blocks and the SSO policy resources
   from `vanta.tf`
2. Remove `modules/vanta/` directory
3. Terraform plan to confirm the roles are not destroyed (they'll be
   managed by iso27001 now — may need `terraform state rm` or import)

### 4. State migration (all accounts)

The vanta-auditor role currently exists in github-control's state.
When iso27001 tries to create it, Terraform will error on the name
conflict. For each account:
- `terraform state rm` the role from github-control state, OR
- `terraform import` the role into iso27001 state

This must be coordinated per-account. Order:
1. Import into iso27001 state
2. Apply iso27001 (no-op on the role, adds tags)
3. Remove from github-control state
4. Apply github-control (no-op, module block already removed)

### 5. Testing

- Deploy org-governance with StackSet, verify SSM params appear in
  member accounts
- Deploy iso27001 in a test account, verify it reads the SSM param
  and creates the vanta-auditor role with correct trust policy
- Create a test account (or use sandbox), confirm StackSet
  auto-deploys the SSM param before iso27001 runs
- Verify Vanta connection check passes

---

## Deployment Order

1. **terraform-aws-org-governance**: deploy vanta.tf with StackSet +
   Identity Store policy. SSM params appear in all member accounts
   immediately (StackSet handles distribution).
2. **terraform-aws-iso27001**: switch vanta.tf to read external ID
   from SSM, remove `var.vanta_external_id`.
3. **github-control**: remove vanta.tf (with state migration per
   account).

No multi-step dependency chain — step 1 is self-contained because
StackSets don't need any role that iso27001 creates.
