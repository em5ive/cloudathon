# Acceptance evidence register

Evidence recorded November 7, 2026. PASS requires direct evidence; BLOCKED identifies a missing prerequisite; NOT TESTED means no execution evidence exists. Update this file with command, date, artifact and result after each check. Source definitions alone do not prove deployed behavior.

| Check | Status | Evidence or next prerequisite |
| --- | --- | --- |
| Six named reference Terraform files inspected read-only | PASS | `compute.tf`, `iam.tf`, `network.tf`, `RDS.tf`, `security_groups.tf`, `varibales.tf`; reuse assessment recorded |
| Previous project's state/backend/provider cache preserved | PASS | No copy/import/migration/deployment performed |
| Fresh authenticated identity | PASS | Report at 19:47:54 UTC: account 708661874787, WSParticipantRole/Participant; authenticated terminal also generated the real plan |
| Default region | NOT TESTED | Host default is `us-east-2`; all preflight requests and provider explicitly use `us-west-2` |
| Fresh engine/class/AZ discovery | PASS | Aurora PostgreSQL 17.11, Serverless class and `us-west-2a/b` checked by the successful preflight |
| Bedrock model/account access and service permissions | BLOCKED | Catalog visibility alone will not prove invocation permission; bounded invoke needs approval |
| Saved namespace inventory | PASS | No matching namespace conflicts in saved inventory; does not reserve names or prove current availability |
| Service Quotas visibility | UNVERIFIED | WSParticipantRole lacks ListServiceQuotas read permission. Exact denials retained as warnings; not quota exhaustion and not a Terraform plan gate |
| Observed Lambda reservation headroom | PASS | Fresh 110 unreserved slots minus proposed 9 leaves 101, above required 100; values can change before apply |
| Actual provisioning permissions and unknown quotas | NOT TESTED | No create or mutation attempted. Service Quotas uncertainty remains documented; review any actual resource/quota error if creation is later approved |
| Terraform formatting | PASS | Root ran `terraform fmt`/format check successfully with current local files |
| Terraform provider/schema validation | PASS | `terraform validate`; signed HashiCorp AWS provider 6.72.0 initialized; new project lockfile |
| Offline Terraform safety plans | PASS | `terraform test`: seven mocked plan-only runs. Three keep secret ARNs unknown through plan for bootstrap/overlap/runtime; four cover security, two-AZ placement, scoped authentication, Support canary and invalid configuration rejection. No AWS API calls or deployment state |
| Account-specific Terraform plan | PASS | `reports/review.tfplan`: 115 additions, 0 changes, 0 deletions at 19:49:08 UTC. Sixteen plan checks passed; four ZIP hashes match. No apply or live behavior implied |
| Python unit tests | PASS | 68 tests across backend, support workflow, preflight and repository safety. Includes genuine concurrent threads against a DB double, quota-warning regressions, ownership, Unicode output checks and closed connections before inference. Mocks do not prove PostgreSQL integration |
| Packaging and CA certificate validation | PASS | Four ZIPs rebuilt and verified for SHA-256, CRC, current source, handlers, Python 3.13 syntax and allowed contents. Five AWS PEM files parsed. Products/Orders hashes are unchanged from the previous implementation; live handshake remains blocked |
| Repeated identical-input package build | PASS | The current four ZIP SHA-256 hashes matched across repeated builds after these fixes; `artifacts/manifest.json` records hashes. Actual Lambda execution remains untested |
| Target Python 3.13 execution | NOT TESTED | Local Python is 3.15.2. CI declares Python 3.13, but this turn did not run GitHub Actions or a Lambda runtime |
| Frontend authentication and support helpers | PASS | PKCE state/S256/single-use/expiry; ticket:null, explicit escalation, unresolved retry keys, bounded Unicode history and context isolation |
| Local frontend browser interactions | PASS | Installed Chrome at 1440px and 390px with fictional fixtures: catalog/cart/search, chat without ticket, explicit escalation, simulated 503 retry, safe text rendering and private data cleared on 401. No overflow/runtime exceptions. AWS/CORS/Cognito/TLS not tested |
| Live Cognito hosted UI | NOT TESTED | Deployed HTTPS callback/configuration and test accounts required |
| Product list/details against Aurora | BLOCKED | Approved deployment/bootstrap required |
| Order stock transaction and concurrent idempotency | BLOCKED | Local behavioral tests plus real DB integration needed |
| Cross-user order/ticket access denied | BLOCKED | Two authorized fictional test users and live JWTs required |
| Local Bedrock fallback behavior | PASS | Offline model failure/fallback and persisted-ticket boundary tests passed with mocked DB/client |
| Support DB/inference lifecycle and escalation | PASS | No open connection during mocked inference; short read/write transactions, immutable receipts, explicit tickets only, atomic rollback, concurrent duplicate submissions converge to one receipt/ticket |
| Live support persistence and Bedrock invocation | BLOCKED | Actual Aurora persistence/model invocation requires deployment, available model permissions and approval |
| Verified TLS Lambda → Proxy and forced TLS Proxy → Aurora | BLOCKED | Inspect deployed settings, complete successful verified connection, reject invalid trust, inspect DB SSL |
| CloudFront HTTPS and HTTP redirect | BLOCKED | No distribution or HTTPS URL deployed |
| Direct anonymous S3 origin access denied | BLOCKED | No deployed bucket/policy |
| Precise API CORS, auth headers and no-store responses | BLOCKED | Actual CloudFront/API URL and preflight/request evidence needed |
| Two-AZ private placement and SG paths | BLOCKED | Deployed account descriptions/route tables and plan review needed |
| Static cache behavior | BLOCKED | Repeat deployed static asset request and record headers |
| Independent service deployment and alias rollback | NOT TESTED | Approved release exercise with version/alias and alarms evidence needed |
| Aurora failover / backup restore / observed RTO-RPO | NOT TESTED | Separate approval, test fixture and measured recovery needed |
| Local inventory sample workflow and business-case formulas | PASS | Eight fictional VMs produced four candidate waves; five migration/payback tests passed. Fictional $900k/$600k/$350k case gave 14-month payback. No live discovery or actual savings claim |
| Editable architecture diagram structure | PASS | XML parsed with 45 unique cells and valid edge endpoints; AWS4 stencil identifiers checked against primary JGraph source. Visual export not tested |
| Company financial savings and license retirement | NOT TESTED | Requires actual invoices, contracts and approved migration outcomes |
| Repository artifacts and recognized credentials | PASS | Git index contains zero tracked files; no generated artifacts already tracked. Required ignore probes pass; current eligible source scan found no recognized credential literals. No browser profiles/cookies are staged. This is not a complete history/secret-format audit |

No AWS resource has been created, modified, deleted, imported or deployed by this implementation turn. No secret credentials were requested or stored in source. Live BLOCKED rows remain until the prerequisites are satisfied. The temporary local preview server was stopped after browser checks.

See [predeployment-fixes.md](predeployment-fixes.md) for changed files, commands, exact plan blocker and deployment readiness. All ten live acceptance categories remain in [live-acceptance-checklist.md](live-acceptance-checklist.md); none are passed by these offline results.
