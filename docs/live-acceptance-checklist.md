# Live AWS acceptance checklist

Current live deployment status: **BLOCKED pending approval and apply**. The real initial plan is ready with 115 additions, 0 changes and 0 deletions; fresh authenticated Oregon preflight succeeded. The host default region is Ohio, overridden by explicit Oregon arguments/provider settings. Eight denied Service Quotas reads are `UNVERIFIED` warnings and did not gate the plan. No deployment, bootstrap, inference or failover is claimed. A plan and local mocks never satisfy the live checks below.

The deployment owner records the verified account/role, region, source revision or source hashes, reviewed plan, approvals, test users, UTC timestamp and redacted evidence for each check. Use only PASS, FAIL, BLOCKED or NOT TESTED. A configured control is not a measured outcome. Never put JWTs, passwords, cookies, workshop credentials or customer messages in committed evidence.

| # | Live test | Status | Required steps and acceptance evidence |
| --- | --- | --- | --- |
| 1 | HTTPS and private S3 | BLOCKED | Read actual CloudFront/API outputs; run `scripts/smoke-https.py`. Require certificate-valid HTTPS, HTTP redirect to the same CloudFront host, anonymous S3 object denial and exact-origin CORS. Inspect static caching separately. No custom domain or ACM resource. |
| 2 | Customer authentication and authorization | BLOCKED | Use two approved fictional Cognito accounts. Anonymous private requests fail; ID tokens without access scopes fail. Account B cannot read A's order, ticket or support context, including guessed IDs. Product queries remain public; support always requires a scoped access token. |
| 3 | Product listing | BLOCKED | GET `/api/products` and a returned product ID. Compare price/stock with approved seeded DB evidence and confirm no-store API headers. Repeat through the frontend. |
| 4 | Orders and inventory | BLOCKED | With approval for test writes, record stock, create an order, replay the same key/body and compare one order/one stock deduction. Concurrent duplicates also create one order. Changed body with the same key returns 409; insufficient stock rolls back every line. Totals come from DB prices. |
| 5 | RDS Proxy TLS and two-stage bootstrap | BLOCKED | Review initial bootstrap plan, separately approve initialization, then review/approve runtime-only plan. Inspect healthy Proxy targets, required TLS, effective `rds.force_ssl`, both AZs and SG paths. Verify a hostname/certificate-checked connection and rejection of an invalid trust configuration. Database-side `pg_stat_ssl` alone does not prove the client handshake. No normal Lambda uses the master secret. |
| 6 | Bedrock conversational support | BLOCKED | Approve bounded paid inference for an available regional Converse model. Ask an authorized order question and selected-product troubleshooting follow-up. Confirm generated conversational prose, separately rendered DB facts and an explicit facts snapshot timestamp. Inject attempts to invent prices/status/ETA; unsafe or malformed output must fall back. Confirm no SQL/tool access or open DB transaction during inference. Model failure must leave support usable. |
| 7 | Explicit ticket escalation | BLOCKED | A normal chat returns `ticket: null` and creates no ticket. Choose the explicit ticket action; verify one persistent owned ticket. Replay and concurrent duplicate submissions produce the same ticket. Changing escalation/message/context with a reused key returns 409. Model recommendations, user prose and inference errors cannot create tickets without the explicit request flag. |
| 8 | Aurora failover | BLOCKED | Obtain separate fault-injection approval. Verify private instances in distinct AZs, record writer and baseline, run a synthetic idempotent workload, fail over to the reader, and measure recovery/errors. Reconcile accepted orders/stock; report measured RTO/RPO and any gaps. Retain evidence and return to normal operations. |
| 9 | Independent Lambda deployment and rollback | BLOCKED | Approve a Support candidate with current live versions pinned. Plan must preserve Products/Orders and DB resources. Observe authorized canary metrics, promote or return Support to the recorded stable alias, and verify customer journeys. A successful offline alias assertion is not a live release/rollback exercise. |
| 10 | CloudWatch monitoring | BLOCKED | Verify logs redact secrets/prompts, request IDs correlate API errors, and API/Lambda/application-failure, fallback, Proxy and ACU metrics appear. Confirm SNS subscription if configured. Under approved synthetic failures, observe the expected alarm and recovery notification. No alarm state is assumed from Terraform creation alone. |

## Read-only preparation

Authenticate through the competition's approved workflow outside chat. Then, in the same PowerShell terminal:

```powershell
aws sts get-caller-identity --region us-west-2 --no-cli-pager
aws configure get region
python scripts/aws-preflight.py --region us-west-2 --output reports/aws-preflight.json
```

Supply the preflight's optional account/model/engine inputs only after independently verifying them. Review each service's result: a successful STS call proves identity only. Bedrock catalog and entitlement checks do not establish that the exact Converse call will succeed. Do not invoke a model as part of the read-only preflight.

After approved deployment and both bootstrap phases, use real outputs, not fabricated hostnames:

```powershell
$cloudfrontUrl = terraform -chdir=terraform output -raw cloudfront_url
$apiUrl = terraform -chdir=terraform output -raw api_url
$frontendBucket = terraform -chdir=terraform output -raw frontend_bucket
python scripts/smoke-https.py --cloudfront-url $cloudfrontUrl --api-url $apiUrl --s3-url "https://$frontendBucket.s3.us-west-2.amazonaws.com/index.html"
```

Set optional `ANYCO_ACCESS_TOKEN` only in the operator's local environment to enable a private-response read check. No script in this checklist retrieves or prints tokens. Order/chat/escalation write tests, paid inference, alias changes and failover need their own applicable authorization; these examples do not grant it.

## Support retry and snapshot checks

Use a new key for each new normalized request, including a separate explicit escalation action. A retry after a network timeout must reuse the original body and key. Assert that the receipt and optional ticket commit together. The model may run more than once during a race or failed persistence; that can add inference cost, but it must not create duplicate tickets. Replays return the committed snapshot, which can be older than the latest order state. A new question/key obtains fresh facts.

The additive `support_requests` table is required for immutable chat/escalation receipts. Fresh deployments receive it during the approved bootstrap. An already deployed database needs a separately reviewed schema/grant migration; never delete Aurora or blindly re-enable master access to update application code. Roll back application aliases with backward-compatible schema retained. Apply an agreed retention policy to stored support messages and snapshots before production use.
