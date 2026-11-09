# Deployment, validation and recovery runbook

This runbook contains future operator steps. It is not authorization to run AWS changes. Only authenticated read-only AWS checks and local implementation/validation were authorized. The deployment owner presents each concrete plan, impact and updated cost estimate and receives explicit approval before applying. Bootstrap, test writes, inference, alias changes, failover and decommissioning also require the relevant explicit authorization.

## Preflight and local preparation

Use the competition account's supported temporary-credential or SSO workflow outside chat. Never paste keys, session tokens, passwords or federation URLs into chat or source. Verify identity and region in the same shell used for planning. If credentials expire, rerun identity before continuing.

```powershell
aws sts get-caller-identity --no-cli-pager
aws configure get region
python scripts/aws-preflight.py --region us-west-2 --output reports/aws-preflight.json
python scripts/build-lambdas.py
python -m unittest discover -s tests -v
terraform -chdir=terraform init -backend=false
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate
```

The preflight uses read-only calls to inspect versions/classes, catalog/models, existing resource names and permissions/quotas where accessible. An AccessDenied result is evidence, not a reason to remove a requirement silently. IAM simulation and catalog/model availability are incomplete permission evidence; service-control policies, boundaries, quotas and runtime checks can still block deployment. Do not invoke a paid model during read-only preflight.

For `servicequotas:ListServiceQuotas` specifically, a denied read is an `UNVERIFIED` warning, not evidence of exhausted capacity and not a plan-preparation gate. Exact errors remain in the report. Confirmed incompatibilities and actual headroom failures still block progression; review any real creation/quota errors if an apply is later approved. No IAM changes or permission bypass is part of this process. Current reservations are configurable, defaulting to 3 Products + 3 Orders + 2 Support + 1 temporary bootstrap slot; use matching preflight overrides for custom values.

Choose an available PostgreSQL engine version and matching parameter family only after the RDS checks; confirm `db.serverless` is orderable in both selected AZs and supported by Proxy. Confirm networking/Cognito/CloudFront/Secrets Manager/IAM permissions independently. Refresh the cost assumptions. Copy the example tfvars into an ignored local file and fill account-verified inputs. Do not add raw passwords.

## Review the initial plan before deployment

```powershell
terraform -chdir=terraform plan -input=false '-out=../reports/review.tfplan'
terraform -chdir=terraform show -no-color '../reports/review.tfplan'
```

Store plans securely and do not commit them. Record the account/role, region, Git commit, provider lock, code hashes, variables, requested capacities, all create/change/delete/replace counts and monthly estimate. Review every database destroy/replace and policy that grants broad access. Expected new components are a VPC and private subnets, endpoints, SGs, Aurora/Proxy/secrets, functions/roles/logs, HTTP API/Cognito, S3/CloudFront and monitoring. There should be no EC2 web servers, ALB, NAT gateway, ACM certificate, custom domain, old-project import or old-state reference.

When authentication is unavailable, report **BLOCKED**. `terraform validate`, a mocked plan or `-refresh=false` output cannot substitute for an account-specific plan. Present the plan and costs, then wait for explicit approval. The operator applies the exact approved saved plan only after rechecking identity; changes or expired saved-plan assumptions require a fresh plan. No apply command is executed automatically by repository scripts or CI.

## Bootstrap and close administrative access

The initial plan uses `database_bootstrapped = false` and enables the temporary bootstrap function. RDS Proxy initially has access to the managed master secret, and bootstrap can connect as the master through IAM + verified TLS. Ordinary application functions do not use the master role.

After infrastructure creation, separately review/authorize bootstrap with the exact event `{"operation":"initialize"}`. The event is an operation selector, not proof of approval. Bootstrap initializes schema and sample data, creates or updates `retail_app` and stores its strong password directly in Secrets Manager. Its expected successful payload is `{"initialized":true,"application_user":"retail_app"}`. Invoke from the deployment owner's shell without printing secret payloads, and inspect both the AWS invocation status and function response for failure. Verify initialization and the secret's metadata without retrieving its password into logs or Terraform.

Then set `database_bootstrapped = true` and `enable_bootstrap = false`, produce a second plan, review the addition of app authentication and removal of the bootstrap Lambda/role, Proxy master auth and temporary two-AZ Secrets Manager endpoints, and obtain approval before applying. Proxy's AWS-managed secret retrieval does not depend on those application-side endpoints. Optional Bedrock endpoints remain only when AI is enabled. The app should be tested only after this second phase. A failure between steps is recoverable by inspecting actual role/secret/schema state and rerunning the idempotent bootstrap with explicit authorization, not by recreating Aurora. Do not automatically destroy the database to fix a schema or password problem.

Passwords are not stored in Terraform, but state and plans still contain sensitive resource metadata and must remain private. Before production, separately design and test app-secret rotation: update DB and Secrets Manager coherently, confirm Proxy refreshes credentials, verify existing/new sessions and document reversal. No untested rotation schedule is claimed.

## Acceptance after deployment

Read Terraform outputs for HTTPS URLs; do not invent endpoints. Use the smoke script to check certificate-valid HTTPS, CloudFront HTTP redirect, public products, unauthenticated private-route rejection and optional anonymous S3 denial:

```powershell
terraform -chdir=terraform output
python scripts/smoke-https.py --cloudfront-url 'https://YOUR.cloudfront.net' --api-url 'https://YOUR.execute-api.us-west-2.amazonaws.com' --s3-url 'https://YOUR-BUCKET.s3.us-west-2.amazonaws.com/index.html' --output reports/https.json
```

Use actual values in place of placeholders. Confirm the redirect's `Location` points to the same HTTPS distribution host. Inspect API responses for `Cache-Control: no-store`, and an OPTIONS request from the exact CloudFront origin for allowed `Authorization`, `Content-Type` and `Idempotency-Key` headers. An unapproved origin must not receive a permissive CORS header. No API origin is configured in CloudFront in this design, so authenticated responses do not traverse its static cache behavior.

With approved fictional users A and B, create an order as A; repeat the exact request/key and confirm the same order and stock result. Reuse the key with changed items and expect conflict. Request A's order/ticket as B and expect a non-disclosing rejection. Attempt insufficient stock and confirm the entire transaction rolls back. Compare order totals to DB prices; caller-supplied prices must not be authoritative. These tests create records and require approval.

For support, follow the ten-part [live acceptance checklist](live-acceptance-checklist.md). Chat uses generated contextual assistance plus separate authorized facts; a normal reply must have no ticket. Only an explicit escalation creates one. The `support_requests` receipt and optional ticket commit atomically after inference, with no open DB connection during the model call. Replay/concurrency tests must verify one durable ticket and the original fact snapshot. Duplicate inference can occur before the winning receipt commits. The new receipt table and SELECT/INSERT grants are additive bootstrap changes; any already deployed database needs a separately approved schema/grant migration before the new Support version receives traffic.

Inspect both DB instances' AZs/private setting, Proxy subnets/target health, application VPC subnet IDs, route tables, SG source references, `require_tls`, and the effective `rds.force_ssl` setting. For an approved diagnostic running through the deployed VPC path, perform a normal verified connection and inspect `SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()` for the database-side connection where supported. PostgreSQL SSL session variables through Proxy do not prove the Lambda-to-Proxy handshake. Separately confirm client certificate/hostname checking rejects a deliberately invalid CA or mismatched hostname; do not disable verification to make the positive test pass. Remove any temporary diagnostic after review. Code inspection alone cannot confirm a live TLS handshake.

Record check results as PASS/FAIL/BLOCKED/NOT TESTED with timestamps and evidence. Keep JWTs, secret values and customer text out of committed reports. Measure remote static timing, p95 API latency, Lambda errors/throttles, DB ACUs and Proxy borrow/pinning metrics before performance claims. No unapproved fault injection is part of basic smoke testing.

## Independent Lambda releases and rollback

Use backward-compatible schema expansion first, then application code; remove old schema only after all consumers are updated. Build deterministic per-service artifacts and check the plan: a Support-only source change must not alter Products/Orders code hashes or replace DB resources.

For a gradual release, first pin each `live` alias to its currently observed numbered version in `lambda_live_versions` (for example `{ products = "1", orders = "1", support = "1" }`; use actual versions). Publish a candidate without moving live traffic, inspect its version/configuration and run approved candidate tests. Set `lambda_canary_versions = { support = { version = "2", weight = 0.05 } }` only with the stable Support version explicitly pinned and after review. Observe at least the agreed error/latency window and alarm state, then promote by changing Support's live pin and clearing its canary entry, or roll back by clearing the canary and retaining the stable pin. Every apply still requires authorization. See [weighted aliases](https://docs.aws.amazon.com/lambda/latest/dg/configuring-alias-routing.html). Do not use `$LATEST` as a weighted version.

Rollback means move that alias fully to the recorded stable version and clear additional routing weights, then verify errors and customer workflows. Do not roll back a DB schema by dropping customer data. Preserve old versions through the observation period. If an authorized operator changes the alias outside Terraform for an incident, immediately reconcile the declared version before the next apply so Terraform cannot silently undo the recovery. CodeDeploy automatic canary/rollback is not configured by default; alarms without an operator/runbook are not an automatic rollback mechanism.

## Incidents and recovery

| Symptom | First read-only diagnostics | Recovery decision |
| --- | --- | --- |
| API 5xx or high latency | Per-function errors/duration/throttles, request IDs, Proxy target/borrow metrics, Aurora load/ACUs | Isolate function failure; approved alias rollback if release-correlated; avoid retry storms |
| DB connection failures | Proxy target health/authentication, IAM resource/user mapping, effective TLS settings, SGs and endpoint DNS | Fix the actual configuration through reviewed change; never bypass TLS or make DB public |
| Support model failure | Bounded error category and fallback metric; Bedrock permission/quota/model state | Keep factual ticket workflow operational; enable/change a model only after approval |
| Unexpected bill | Billing/usage breakdown, DB ACUs, log growth, endpoint inventory, retained snapshots | Review capacity/retention and unused resources; approved changes only; do not delete recovery data blindly |
| Suspected data/authorization incident | Audit metadata and request IDs with restricted access | Contain affected access through approved incident action; preserve evidence; notify designated owners |

Aurora failover is a separate approved exercise: establish a synthetic workload with unique idempotency keys, record writer identity and baseline errors, invoke approved failover, measure recovery, verify no duplicate/missing accepted orders and restore normal monitoring. Do not claim the failover was lossless or within an RTO before checking evidence. Backup restore requires a separately approved target environment and reconciliation; a backup-retention setting is not a successful restore test.

The design tolerates individual resource/AZ failures through managed multi-AZ components; a full-region outage is outside the implemented recovery scope. Document workload-specific future secondary-region backups/global replication and DNS/API/identity recovery before promising regional DR.

Decommission requires explicit approval, accepted workload evidence, expired rollback retention, backup/retention decisions and contract/asset closure. Never run `terraform destroy` against the old project or shared infrastructure as part of this POC. A workshop cleanup plan must identify exactly which new resources and retained snapshots it affects, with costs and data-loss implications, before authorization.
