# Predeployment fixes and readiness

The existing Option B architecture is preserved. All six requested local fix areas are addressed. **The account-specific initial plan is ready: 115 additions, 0 changes, 0 deletions. Nothing has been applied.** The authenticated terminal created it at `2026-11-07T19:49:08Z` in account `708661874787`, `us-west-2`, using freshly verified Aurora PostgreSQL `17.11`. The host default region is `us-east-2`; explicit Oregon arguments/provider configuration override it. Earlier sandbox/no-credential and host/expired-session observations did not describe the user's working terminal; that terminal successfully generated the plan. See [terraform-plan-review.md](terraform-plan-review.md) and the ignored `reports/review.tfplan`, text and JSON.

`servicequotas:ListServiceQuotas` AccessDenied results are now **UNVERIFIED warnings**, not quota exhaustion or a block on validation/plan preparation. The fresh report at `2026-11-07T19:47:54.109462+00:00` retains eight exact denials and follow-up requirements and reports planning readiness. The older 19:28 report is preserved separately. Confirmed failures and missing required capabilities still block progression. Sixteen checks against the actual saved plan passed; unknown post-creation values and live behavior remain unverified.

No `terraform apply`, `terraform destroy`, state import/migration/edit, AWS provisioning, paid inference, Git commit or GitHub push was performed. Existing source, previous architecture references and state remain preserved.

## Changes

1. **Proxy authentication:** a `bootstrap`/`runtime` map supplies plan-known identities, while values remain computed secret ARNs. The IAM secret-resource list derives from the same map. TLS, PostgreSQL SCRAM, client IAM authentication and the two-stage credential separation remain intact. New mocked plans keep resource values unknown through plan and cover bootstrap, intentional overlap and runtime-only modes. This refactor addresses the planning risk; no account-specific reproduction of the earlier suspected failure is claimed.
2. **Conversational support:** Converse generates actual contextual prose, basic selected-product troubleshooting and follow-up questions. The application validates bounded JSON output, rejects controlled fact/unsafe-action claims and Unicode obfuscation, and renders DB facts separately. No model SQL, tools or authorization decisions are permitted. Normal chat returns `ticket: null`; a separate explicit action creates a persistent ticket. Model failure does not escalate automatically.
3. **Transaction isolation from inference:** read and authorize facts, close the connection, invoke the model, then open a short write transaction. Immutable customer/key receipts and a lock/recheck protect replay and concurrent ticket creation. Ticket plus receipt commit atomically. Concurrent duplicate chat can spend inference twice, but returns the first committed receipt; replayed facts retain their snapshot timestamp. Product context remains available through the owned ticket/receipt join.
4. **AWS preflight:** authentication failure, actual read denial, connectivity failure and untested capabilities are distinct. Service Quotas visibility denials become documented `UNVERIFIED` warnings and do not prevent a plan; other required read failures and actual incompatibilities remain blocking. The historical account has 110 unreserved Lambda slots: the former 14-slot request would leave 96 and fail AWS's required floor. Configurable defaults now reserve nine initial slots (3/3/2 + bootstrap 1), which would leave 101 against that snapshot; fresh headroom is checked before planning. Existing reservations are counted incrementally. Catalog/STS success never proves deployment or Converse permission; no secret values or paid invocation are requested.
5. **Deployment/acceptance:** the initial bootstrap creates the additive `support_requests` table and SELECT/INSERT grants without raw passwords in Terraform state. The reviewed runtime phase removes bootstrap/master access and temporary Secrets Manager endpoints. Existing deployed databases need an approved additive schema/grant migration before the new Support release. The [live checklist](live-acceptance-checklist.md) covers all ten requested categories.
6. **Repository/package safety:** generated paths, profiles and cookie/login databases are ignored. A read-only checker reports paths/rule names without secret values. The Git index currently has zero tracked files, so no generated artifacts are already tracked. Packaging now allows only Python source and reviewed CA files from backend directories; incidental text notes and hidden artifacts are excluded. Public CA files retain byte-exact fingerprints across Git checkouts.

Generated prose filtering is conservative and English-only; it can reject otherwise helpful wording. Live model quality/adversarial checks remain required. Receipts persist bounded answers and fact snapshots, so production also needs a retention policy. The application does not promise exactly-once inference, fresh facts on replay, automatic secret rotation, automatic release rollback or region-wide disaster recovery.

## Validation evidence

Recorded November 7, 2026:

| Check | Status | Result |
| --- | --- | --- |
| `python -m unittest discover -s tests -v` | PASS | 68 tests, including 21 support workflow/model regressions, 17 preflight tests and three repository safety tests |
| `python scripts/test-tools.py` | PASS | Five migration/business-case tests |
| `npm.cmd run check:frontend` | PASS | Syntax, PKCE, support contracts, retry interleavings and bounded history |
| Local Chrome fixture checks | PASS | Desktop 1440px/mobile 390px; normal chat, explicit escalation, retry, safe text and 401 clearing; no live AWS claims |
| `terraform -chdir=terraform fmt -check -recursive` | PASS | Current HCL formatting |
| `terraform -chdir=terraform validate -no-color` | PASS | Initialized AWS provider 6.72.0 schema validation |
| `terraform -chdir=terraform test -no-color` | PASS | Seven mocked plan-only runs; no AWS API calls |
| Lambda build and verification | PASS | Four ZIPs; hash/CRC/source freshness/handler/Python 3.13 syntax/allowed contents |
| Identical-input rebuild | PASS | All four ZIP hashes unchanged across repeats; Products/Orders also retain their pre-fix hashes |
| Repository safety | PASS | Zero tracked generated files; required ignores and recognized credential scan pass |
| Actual Python 3.13/Lambda execution | NOT TESTED | Local interpreter is Python 3.15.2; CI declares 3.13 but was not run here |
| Fresh authenticated discovery | PASS | Workshop-role report: account, Oregon AZs, exact engine 17.11/Serverless options, documented Proxy support, endpoints, inventory and sufficient Lambda headroom |
| Service Quotas visibility | UNVERIFIED | Denied read permission; no exhaustion conclusion and no plan gate |
| Account-specific real plan | PASS | Authenticated terminal saved 115 additions, 0 changes, 0 deletions; sixteen plan-configuration checks and all four current Lambda hash comparisons pass |
| Live HTTPS/auth/DB/Bedrock/failover/release/monitoring | BLOCKED | Initial plan is ready but apply/bootstrap and live acceptance remain unapproved; see the ten-category checklist |

## Files changed or added

The repository has no tracked source baseline yet; this is the implementation file list, not a claim of a committed Git diff. Files outside this list were not intentionally changed by these fixes. Build artifacts and reports are ignored.

| Area | Modified existing files | Added files |
| --- | --- | --- |
| Terraform | `terraform/locals.tf`, `terraform/proxy.tf`, `terraform/variables.tf`, `terraform/terraform.tfvars.example` | `terraform/tests/computed-auth.tftest.hcl` |
| Backend/database | `backend/support/handler.py`, `backend/bootstrap/handler.py`, `backend/README.md`, `database/schema.sql`, `tests/test_backend.py` | `tests/test_support_workflow.py` |
| Frontend | `frontend/app.js`, `frontend/index.html`, `frontend/styles.css`, `scripts/test-frontend.mjs`, `scripts/check-frontend-browser.mjs` | `frontend/support.js` |
| Preflight | `scripts/aws-preflight.py` | `tests/test_preflight.py` |
| Safety/packaging/CI | `.gitignore`, `scripts/build-lambdas.py`, `.github/workflows/validate.yml` | `.gitattributes`, `scripts/check-repository-safety.py`, `scripts/verify-lambda-packages.py`, `scripts/prepare-plan.ps1`, `tests/test_repository_safety.py` |
| Documentation | `README.md`, `docs/acceptance-status.md`, `docs/architecture.md`, `docs/demo-script.md`, `docs/executive-summary.md`, `docs/implementation-plan.md`, `docs/migration-wave-runbook.md`, `docs/operations-runbook.md` | `docs/live-acceptance-checklist.md`, `docs/predeployment-fixes.md`, `docs/terraform-plan-review.md` |

Ignored outputs refreshed include `reports/aws-preflight.json`, its historical snapshot, `reports/repository-safety.json`, browser evidence/screenshots, the real binary/text/JSON plan and plan review JSON, and four `artifacts/*.zip` files plus hash manifest. No browser profile, cookie database, credentials, state or plan has been committed or staged.

## Exact next PowerShell steps

The current next step is review of the actual saved artifact:

```powershell
Set-Location 'C:\Users\15kda\Documents\cloudathon'
terraform -chdir=terraform show -no-color '..\reports\review.tfplan'
Get-FileHash -Algorithm SHA256 '.\reports\review.tfplan'
```

Do not apply yet. If the configuration/artifacts/account conditions change, regenerate and review a fresh plan. The remaining commands describe how to regenerate it, not additional work required to claim the current plan exists.

For regeneration, authenticate using the competition's approved CLI setup **outside chat**. The appropriate login mechanism depends on the workshop; a federation console URL is not CLI credentials. Then run:

```powershell
Set-Location 'C:\Users\15kda\Documents\cloudathon'
aws sts get-caller-identity --region us-west-2 --no-cli-pager
if ($LASTEXITCODE -ne 0) { throw 'AWS authentication is unavailable. Stop here.' }
aws configure get region
python scripts/aws-preflight.py --region us-west-2 --project-name uh-retail-poc --output reports/aws-preflight.json
```

If the working credentials are scoped to a terminal that this agent cannot inherit, run this from that terminal. Version `17.11` appears in the saved Oregon Serverless offerings; the helper rechecks its exact availability and Proxy compatibility before planning, rather than assuming the saved evidence is current:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prepare-plan.ps1 -ExpectedAccountId 708661874787 -EngineVersion 17.11 -ShareCliSession
```

This initial-plan helper saves the binary plan and readable text/JSON under ignored `reports/`, and never applies. It temporarily shares the CLI's existing session with the provider in process memory, then restores the environment; no credential values are printed, saved or supplied to Terraform variables. AWS documents [CLI credential export](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html). No IAM permissions are changed or bypassed. The plan's Bedrock inference remains disabled until a specific model and its requirements are verified.

The first discovery pass intentionally cannot report plan-ready without verified account/version selections. Read the report, compare STS with the independently supplied competition account ID, and select an exact engine version supported by the returned orderable options and published Proxy table. Do not invent these inputs. Optional AI additionally needs an eligible regional Converse model and its reviewed exact ARN.

After that review, these commands prompt only for nonsecret selections and generate a plan:

```powershell
$expectedAccountId = Read-Host 'Independently verified competition account ID'
$engineVersion = Read-Host 'Aurora PostgreSQL version verified by preflight'
python scripts/aws-preflight.py --region us-west-2 --project-name uh-retail-poc --expected-account-id $expectedAccountId --engine-version $engineVersion --output reports/aws-preflight.json
if ($LASTEXITCODE -ne 0) { throw 'Resolve the preflight findings before planning.' }
terraform -chdir=terraform init -backend=false -input=false -lockfile=readonly
if ($LASTEXITCODE -ne 0) { throw 'Provider initialization failed.' }
terraform -chdir=terraform plan -input=false "-var=expected_account_id=$expectedAccountId" "-var=aurora_engine_version=$engineVersion" '-out=../reports/review.tfplan'
if ($LASTEXITCODE -ne 0) { throw 'Terraform plan failed. Do not apply.' }
terraform -chdir=terraform show -no-color '../reports/review.tfplan'
```

These commands apply to the current local-only backend configuration, under exclusive deployment ownership. If an approved remote backend is introduced, use its reviewed initialization procedure instead of `-backend=false`; do not migrate existing state implicitly. Keep Bedrock disabled until model/endpoint/permission review; if enabling it, rerun preflight with the selected `--model-id` and include the matching Terraform model inputs in the reviewed plan. Match `--project-name` to any chosen Terraform namespace.

Present the resulting account-specific plan, replacement/deletion impact and updated costs for explicit authorization. The existing $250–$400/month low-use allowance remains an unverified planning estimate, not a cap. No apply/destroy command is authorized or automated by this runbook. Bootstrap invocation and the second runtime-auth plan require their own concrete review and approval.
