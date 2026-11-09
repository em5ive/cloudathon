# SNS policy fix and partial-apply retry

**Historical review:** this describes the earlier `reports/review.tfretry`. The [current state recovery procedure](state-recovery.md) supersedes it; generate and review the fresh `reports/retry.tfplan` before any approval. The earlier file is preserved as evidence.

**New plan: `reports/review.tfretry` — 1 addition, 1 in-place change, 0 deletions. No replacements or duplicate resources. Nothing was applied during this fix.**

The original `reports/review.tfplan` was used by the team's partial deployment. Do not apply it again. It was preserved unchanged; the new plan was generated from the current local state and the same first-stage variable values, using normal read-only refresh during planning.

## Policy correction

`terraform/monitoring.tf` now replaces the `AccountOwner` action `SNS:*` with:

- `SNS:GetTopicAttributes`
- `SNS:SetTopicAttributes`
- `SNS:AddPermission`
- `SNS:RemovePermission`
- `SNS:DeleteTopic`
- `SNS:Subscribe`
- `SNS:ListSubscriptionsByTopic`
- `SNS:Publish`

These are the standard topic-scoped actions documented in AWS's [SNS policy-action reference](https://docs.aws.amazon.com/sns/latest/dg/sns-access-policy-language-api-permissions-reference.html). The account principal and topic resource remain unchanged. The existing CloudWatch and EventBridge `SNS:Publish` statements, principals, account restriction and source-ARN conditions were preserved. No policy was sent to AWS by this implementation turn; service acceptance and notification delivery await a separately approved apply/test.

## Existing partial-deployment state

Read-only `state list`, local state JSON and the new plan agree:

| Item | Recorded result |
| --- | --- |
| Backend/workspace | Existing local backend, default workspace |
| State file | `terraform/terraform.tfstate` |
| Serial / lineage | `116` / `63898c23-df79-bbe8-2583-c2dc39531dfe` |
| Existing instances | 114 managed resources, plus 3 data resources |
| Missing resource | Only `aws_sns_topic_policy.operations` |
| State SHA-256 before/after | `b359091f3b5bd6a4da8d221c446226aa82007d9c2255ca2c5d28219fec11181b` |
| Tainted/deposed/state-only resources | None found |

The SNS topic, VPC/subnets, Aurora cluster and both DB instances, RDS Proxy and target, four Lambda functions, three aliases, API Gateway, Cognito, private S3/CloudFront and the other monitoring resources are already recorded in state. ARN account/region and project tags match the existing competition deployment. No state entry was removed, imported, rewritten or restored.

## New plan review

The authenticated terminal produced the new plan at **2026-11-07 20:45:45 UTC**, for account `708661874787`, `us-west-2`.

| Action | Resource | Meaning |
| --- | --- | --- |
| Create | `aws_sns_topic_policy.operations` | Attach the corrected policy to the existing SNS topic; does not create another topic |
| Update in place | `aws_cloudfront_distribution.frontend` | Reconcile the existing S3 origin's empty `s3_origin_config` block; a computed timeout is refreshed |
| No change | 113 other managed resources | Existing infrastructure is retained |

**CloudFront warning:** this is an additional, non-destructive change beyond the SNS fix. The source configuration was not altered to conceal it. AWS omitted the empty legacy S3-origin block from the deployed result; Terraform proposes restoring `{origin_access_identity = ""}`. `response_completion_timeout` changes from `0` to a computed value. Distribution identity, OAC, HTTPS, cache policies and frontend files remain unchanged. Review this update before approving the retry. The helper intentionally flags changes beyond the missing SNS policy for review; Terraform planning itself succeeded.

The first-stage inputs are semantically identical to the used plan: Aurora PostgreSQL `17.11`, `database_bootstrapped = false`, `enable_bootstrap = true`, reservations `3/3/2` plus bootstrap `1`, and Bedrock disabled. No bootstrap invocation or second-stage transition was performed.

| Validation | Result |
| --- | --- |
| Terraform formatting | PASS |
| Terraform validation | PASS |
| Mocked plan tests | PASS — eight runs, including explicit SNS actions and preserved publishers |
| Binary retry plan vs JSON | PASS — equal |
| Deletions/replacements/duplication | None |
| Current state bytes | Unchanged |
| Used original binary plan | Unchanged; not executed again |

New plan SHA-256: `60b2f97eec4233f5ca56aa1a778acae989692e284eb3bd43722b7deb80b1ee8d`.

Review artifacts:

- `reports/review.tfretry` — new binary plan.
- `reports/review-retry-plan.txt` — readable plan.
- `reports/review-retry-plan.json` — machine-readable plan.
- `reports/retry.inputs.tfvars.json` — copied nonsecret original input values; ignored by Git.
- `reports/retry-state-before.json` — state identity/hash metadata; ignored by Git.

```powershell
terraform -chdir=terraform show -no-color '..\reports\review.tfretry'
```

The new plan requires explicit team approval before any apply. No `apply`, `destroy`, `state rm`, `import`, standalone refresh or targeted recovery command was run. Existing resources continue to run and incur costs while the policy retry awaits approval. Quota visibility remains unverified; no IAM permissions were changed or bypassed.
