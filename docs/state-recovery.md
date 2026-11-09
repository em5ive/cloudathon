# Recovery against the existing deployment

The deployment is being completed from its existing local state. No state migration, import, resource deletion, or apply is part of this recovery work.

**Fresh plan reviewed: `reports/retry.tfplan` — 1 addition, 0 changes, 0 deletions, and no replacements.** The only action is attaching `aws_sns_topic_policy.operations` to the existing SNS topic. All 114 existing managed resources remain unchanged. Team approval is required before applying this plan.

## What the investigation established

The actual state is `terraform/terraform.tfstate`, under the implicit **local backend** and **default workspace**. It contains **114 managed instances and 3 data instances**, not 117 managed resources. Its serial is `116`, lineage is `63898c23-df79-bbe8-2583-c2dc39531dfe`, and SHA-256 is `b359091f3b5bd6a4da8d221c446226aa82007d9c2255ca2c5d28219fec11181b`.

Aurora, both database instances, RDS Proxy, four Lambda functions, CloudFront, and the remaining deployed resources are already tracked. The only missing original resource address is `aws_sns_topic_policy.operations`; its SNS topic already exists.

The available saved plans explain the apparent full rebuild:

| Existing file | Embedded state | Managed actions |
| --- | --- | --- |
| `reports/review.tfplan` | Original empty deployment; no prior managed resources | 115 creates |
| `reports/review.tfretry` | Correct deployed state; 114 managed and 3 data instances | 1 SNS policy create, 1 CloudFront update, 113 unchanged |

No file named `retry.tfplan` existed anywhere in this workspace during investigation. Therefore the reported all-create retry file and its original invocation cannot be diagnosed conclusively without its path. The only all-create archive found is the used, historical `review.tfplan`. Neither that plan nor the earlier retry should be used for the new recovery attempt.

The current configuration contains no backend block. There is no cached backend override or workspace selection file, and the inspected execution process has no `TF_*` state-selection overrides. Read-only `workspace show` and `state pull` select the same existing state. This establishes the current selection, rather than assuming how another terminal was previously configured.

## Process correction

`scripts/prepare-retry-plan.ps1` now:

1. Resolves the Terraform directory and existing state to absolute paths, independent of the calling directory.
2. Rejects `TF_WORKSPACE`, `TF_DATA_DIR`, and injected `TF_CLI_ARGS*` settings, unexpected backend/cloud configuration, a different cached backend, and any workspace other than `default`. It does not initialize or switch anything.
3. Compares Terraform's effective `state pull` with the existing state, including lineage, serial, resources, outputs and instance counts. Full state JSON stays private in memory.
4. Uses all original first-stage input values from `reports/review-plan.json`, including `enable_bootstrap=true`, `database_bootstrapped=false`, Aurora `17.11`, account `708661874787`, and `us-west-2`.
5. Passes an explicit absolute `-state` path, which Terraform supports for this [local backend](https://developer.hashicorp.com/terraform/cli/commands/plan). Normal refresh reads AWS into the saved plan; it does not persist refreshed state.
6. Creates a fresh `reports/retry.tfplan` and separate review artifacts, refusing to overwrite an existing output. It independently verifies the binary's embedded prior resources and outputs, original variables, and preserved resource addresses. Creates of tracked resources, replacements, deletions, and changes beyond the missing SNS policy fail review.
7. Confirms the state, used original plan and original input record retain their exact hashes. The initial-deployment helper also refuses to overwrite these existing deployment artifacts.

`terraform/frontend.tf` no longer declares an empty legacy `s3_origin_config` alongside OAC. The pinned provider [automatically supplies the empty API configuration and deliberately omits that empty block on readback](https://github.com/hashicorp/terraform-provider-aws/blob/v6.72.0/internal/service/cloudfront/distribution.go#L2209-L2290). Its [official OAC example](https://github.com/hashicorp/terraform-provider-aws/blob/v6.72.0/website/docs/r/cloudfront_distribution.html.markdown#L69-L80) uses the OAC reference alone. This removes the prior retry's unnecessary CloudFront diff while retaining the same private origin, OAC, distribution and HTTPS settings. Only a fresh AWS-refreshed plan can confirm the resulting actions.

## Verification and fresh planning

Read-only state selection can be checked without AWS credentials:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prepare-retry-plan.ps1 -VerifyStateOnly
```

Generate the plan from the authenticated workshop terminal:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prepare-retry-plan.ps1 -ShareCliSession
```

`-ShareCliSession` passes the approved CLI session to the provider in process memory only. It does not print or save credentials, change profiles or IAM, or grant permissions. The helper does not use resource-name collision preflight against its own deployed resources. Service Quotas read restrictions remain unverified warnings in the existing preflight record; they do not imply exhausted quotas.

The expected review files are:

- `reports/retry.tfplan`: fresh binary plan, generated and reviewed.
- `reports/retry.tfplan.txt` and `.json`: readable and machine-readable plan.
- `reports/retry.tfplan.state-check.json`: state-selection identity evidence.
- `reports/retry.tfplan.audit.json`: embedded-state, input and action audit.
- `reports/retry.tfplan.inputs.tfvars.json`: original nonsecret first-stage variables.

The authenticated terminal generated the complete, applyable plan at **2026-11-07 21:10:37 UTC**. Independent review of its binary and JSON confirmed account `708661874787`, `us-west-2`, all 16 original input values, and first-stage bootstrap flags. The embedded prior resources/outputs exactly match the existing state. All 16 archived Terraform files match current source byte-for-byte. The earlier unnecessary CloudFront update is absent.

Plan SHA-256: `3c314edf4d6ae46a8eb2c751aae0fbbce9bc9c87028458bcd7351544d5c2f448` (108,571 bytes). State SHA-256 remains `b359091f3b5bd6a4da8d221c446226aa82007d9c2255ca2c5d28219fec11181b`.

For the designated deployment owner, **only after team approval**, from the project root:

```powershell
terraform -chdir=terraform apply '..\reports\retry.tfplan'
```

This command is documented for a future approved action and was not executed. It completes the missing first-stage infrastructure policy; database bootstrap and the separately reviewed second stage still follow the deployment runbook. No apply command is executed by either verification mode or planning mode.

Checks completed before generating the replacement plan:

| Check | Result |
| --- | --- |
| Actual `workspace show` / effective `state pull` comparison | PASS: local/default, all 117 entries |
| Recovery helper invoked from outside the project directory | PASS: same existing state selected |
| Injected `TF_CLI_ARGS_plan` state override | PASS: rejected before Terraform/AWS |
| Original state, original binary plan and original input preservation | PASS: unchanged bytes |
| Terraform formatting / validation | PASS |
| Mocked Terraform configuration tests | PASS: 8 runs |
| Python tests, including recovery guards | PASS: full suite 90 tests; 25 focused recovery tests after the input-encoding fix |
| Lambda packages | PASS: all four original packages remain current |
| Fresh AWS-refreshed recovery plan | PASS: 1 missing SNS policy create, 114 managed no-ops, no deletions/replacements |

The investigation process reported an expired AWS login, so the authenticated workshop terminal generated the plan. State-only verification and independent review of the resulting saved binary require no AWS credentials and passed. No claim is made that identity checks guarantee every service creation permission; any actual service error remains subject to review if apply is later authorized.

The authenticated terminal's first attempt stopped at JSON parsing before AWS requests or planning. Its diagnostic reported `Cannot parse captured effective state`; the actual state hash and serial remained unchanged. The same failure was reproduced by configuring PowerShell to send a UTF-8 byte-order mark. The guard now reads stdin as bytes and accepts JSON's standard BOM encodings without changing any state comparisons. The exact PowerShell reproduction now passes against all 117 existing entries. The helper also includes the nonsecret rejection reason and diagnostic path in future errors. The subsequent authenticated run successfully generated the reviewed fresh plan.
