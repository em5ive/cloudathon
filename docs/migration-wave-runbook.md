# Executable MGN wave runbook

This is a future enterprise operator runbook, **not an executed migration or authorization**. This POC has not performed live MGN source-server discovery or migration; only the local CSV sample has run. Authenticated application-infrastructure discovery and Terraform planning are separate evidence. MGN test launch, lifecycle changes, cutover, replication setup, DNS changes and finalization all change resources and require separate explicit approval. Finalization deletes replication resources, so it has an additional irreversible impact to review.

## 1. Prepare the application move group

Have the migration owner, application/data owners, network/security owners and change approver sign a wave record containing inventory export/hash, dependency group, license model, target account/region, Terraform commit/approved plan, source-to-target mapping, maintenance window, write-freeze procedure, business checks, rollback owner and retention date. Confirm target landing zone, IAM roles, KMS, subnets/SGs, monitoring, restore points, supported source OS, source credentials/agent installation process, bandwidth and quotas. Agent installation and MGN initialization/replication are separately authorized preparatory actions; this runbook does not automate or silently perform them.

Copy these JSON request templates into an ignored `reports/approved-wave/` directory and replace every placeholder with approved IDs. CLI request field names were verified against the installed AWS CLI's local `--generate-cli-skeleton input`; no API request is sent by skeleton generation. Use `--help` and the official references again if the CLI/service changes.

`describe.json`:

```json
{"filters":{"sourceServerIDs":["REPLACE_WITH_APPROVED_SOURCE_SERVER_ID"],"isArchived":false}}
```

`launch.json` (used for both test and cutover):

```json
{"sourceServerIDs":["REPLACE_WITH_APPROVED_SOURCE_SERVER_ID"]}
```

`ready.json` (one approved server at a time):

```json
{"sourceServerID":"REPLACE_WITH_APPROVED_SOURCE_SERVER_ID","lifeCycle":{"state":"READY_FOR_CUTOVER"}}
```

`finalize.json`:

```json
{"sourceServerID":"REPLACE_WITH_APPROVED_SOURCE_SERVER_ID"}
```

The placeholders deliberately fail validation until replaced. Keep real source metadata and generated reports private. Do not put source passwords or secrets in these files.

## 2. Inspect replication: read-only

```powershell
aws sts get-caller-identity --no-cli-pager
aws mgn describe-source-servers --region us-west-2 --cli-input-json 'file://reports/approved-wave/describe.json' --no-cli-pager
aws mgn describe-jobs --region us-west-2 --no-cli-pager
```

Verify the returned account/role, exact source-server set, replication state, lag, disk backlog, lifecycle, launch template and dependency connectivity. Wait for full synchronization and test readiness; a successful API call does not prove a healthy workload. Proposed **example** go/no-go criteria, to be replaced by signed business objectives: replication lag ≤60 seconds for 15 minutes before write freeze, no disk backlog after final synchronization, successful restore rehearsal, zero critical security/data-integrity failures and full application-owner sign-off. For a zero-loss cutover, freeze writes and wait for the required fully synchronized state rather than treating a 60-second lag as zero RPO.

Read-only command reference: [describe source servers](https://docs.aws.amazon.com/cli/latest/reference/mgn/describe-source-servers.html).

## 3. Launch and validate a test: approval required

After approval of source IDs, target placement and temporary costs:

```powershell
aws mgn start-test --region us-west-2 --cli-input-json 'file://reports/approved-wave/launch.json' --no-cli-pager
aws mgn describe-jobs --region us-west-2 --no-cli-pager
```

Record the returned job ID and inspect every server's launch status, not only the top-level job status. Test in an isolated target environment that cannot run duplicate production schedules or write to production dependencies. Validate login, critical application journeys, inventory/order reconciliation, interfaces, TLS, restore, license activation, monitoring and representative load. Record baseline and target p95/error rates. Terminating test instances is a separate approved cleanup action, not an implicit command here. See [start test](https://docs.aws.amazon.com/cli/latest/reference/mgn/start-test.html).

After successful test acceptance, an approved lifecycle change marks each applicable server ready:

```powershell
aws mgn change-server-life-cycle-state --region us-west-2 --cli-input-json 'file://reports/approved-wave/ready.json' --no-cli-pager
```

See [lifecycle change](https://docs.aws.amazon.com/cli/latest/reference/mgn/change-server-life-cycle-state.html). Do not force readiness to bypass failed tests or replication errors.

## 4. Cut over: approval and controlled writes required

Confirm the change window and rollback deadline, lower applicable DNS TTL in advance, drain scheduled jobs and transactions, freeze source writes, take the agreed recovery point, and wait for final synchronization. Record application-consistent order counts, inventory totals and last committed transaction markers. Keep the source available under the signed rollback/contract policy.

Only after go/no-go approval:

```powershell
aws mgn start-cutover --region us-west-2 --cli-input-json 'file://reports/approved-wave/launch.json' --no-cli-pager
aws mgn describe-jobs --region us-west-2 --no-cli-pager
```

Verify per-server launch and dependencies, then change traffic through the separately approved application/DNS procedure. `start-cutover` launches instances; it does not perform the company's DNS switch or business validation. Enable target writes only after the designated owner accepts the target. Proposed example rollback triggers: any lost/duplicate committed business transaction, critical authorization failure, failed critical workflow, or p95 latency >20% above the approved baseline for 15 minutes. These thresholds are planning examples, not observed service levels. See [start cutover](https://docs.aws.amazon.com/cli/latest/reference/mgn/start-cutover.html).

## 5. Recover a failed cutover

Before target writes: keep source frozen during diagnosis, verify the source remains authoritative and unchanged, approve routing back, resume source writes/jobs, and retain evidence. After target writes: freeze both sides, export committed target changes with transaction identifiers, reconcile into the source or use a pretested reverse-replication mechanism, confirm no missing/duplicate transactions, then approve a traffic/write-owner switch. MGN's forward replication alone is not a generic application-aware reverse-replication or rollback mechanism. If safe reconciliation is unavailable, continue target recovery rather than redirecting to stale data.

The owner records incident timing, downtime, data-loss assessment and corrective actions. Target/test instance cleanup, lifecycle reset and subsequent retest are separate reviewed changes. Do not leave two writers active, finalize cutover during an unresolved rollback, or delete source disks to conceal a failed migration.

## 6. Finalize, decommission and close license costs

After the agreed observation period and owner acceptance, review whether MGN replication is still required. **Finalization terminates MGN replication resources and uninstalls its agent; it does not delete launched target EC2 instances.** Obtain approval for that impact before running:

```powershell
aws mgn finalize-cutover --region us-west-2 --cli-input-json 'file://reports/approved-wave/finalize.json' --no-cli-pager
```

See [finalize cutover](https://docs.aws.amazon.com/cli/latest/reference/mgn/finalize-cutover.html). Retain necessary source/recovery data under the signed retention policy. Source VM deletion, host/cluster retirement, hardware disposal, contract termination and facility handback are separate approvals with evidence. Close a wave only after the cost ledger records source charges that actually stopped, continuing AWS/license charges, and procurement's cancellation acknowledgment.
