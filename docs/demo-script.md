# Competition demonstration: approximately eight minutes

Use [acceptance-status.md](acceptance-status.md) to choose the honest demonstration mode. With no deployment, demonstrate local source/tests, the inventory workflow and the plan procedure; do not display fabricated URLs or prerecorded output as a live deployment.

| Time | Demonstration | Evidence and business explanation |
| --- | --- | --- |
| 0:00–0:45 | State rising platform licenses, hundreds of VMs, small team and Q4 2027 lease deadline | One application illustrates modernization. Fleet exit requires discovery, waves, rehosting and retirement. |
| 0:45–1:45 | Open `architecture.drawio`; follow browser → CloudFront/S3 and browser → API/Lambda → Proxy/Aurora | Default HTTPS avoids certificate management; OAC hides origin; private two-AZ data path reduces host/AZ dependence. Explain maintained DB cost floor. |
| 1:45–3:15 | If deployed: open HTTPS storefront, list products, sign in, submit an order and view it | Record order ID and stock before/after. Repeat the same idempotency key with the same payload; show one order. Demonstrate account B cannot read account A's order. Use fictional identities only. |
| 3:15–4:15 | Ask Support about that order, follow up on a selected product, then explicitly request a ticket | Show conversational assistance beside authorized timestamped facts. Normal chat creates no ticket; the separate escalation action creates one retry-safe ticket. Identify the approved model if configured; show local fallback/lifecycle test output. No DB connection is held during inference. |
| 4:15–5:15 | Show HTTPS smoke report and CloudWatch dashboard | HTTP at CloudFront redirects to HTTPS; direct S3 is denied; unauthenticated private API returns 401/403. State whether TLS handshake/failover was actually measured. |
| 5:15–6:00 | Show per-service artifacts, published version and stable alias strategy | A Support-only release can preserve Products/Orders; explain reviewed canary and rollback. A runbook is not a completed live rollback test. |
| 6:00–7:00 | Run sample inventory normalization and view proposed dependency groups | Use `python scripts/discover-inventory.py --inventory migration/inventory.example.csv --dependencies migration/dependencies.example.csv --output reports/migration-waves.csv`. Show assumptions and human review flags. It does not scan the company or migrate VMs. |
| 7:00–8:00 | Show cost sensitivity, licensing register and dated roadmap | Keep platform/OS/DB/application licenses separate. Cutovers by Aug 31, September buffer/retirement; cancellation and final invoice prove savings. |

Read-only evidence commands after deployment, with actual output values:

```powershell
terraform -chdir=terraform output
python scripts/smoke-https.py --cloudfront-url 'https://YOUR.cloudfront.net' --api-url 'https://YOUR.execute-api.us-west-2.amazonaws.com' --output reports/https.json
python scripts/business-case.py --input migration/business-case.example.json
```

Do not run apply, bootstrap, order creation, alias changes, model invocation, failover or destructive cleanup merely because they appear in a demo script. A live demonstration that creates records or incurs inference usage needs the corresponding approval. Use local tests for failure injection when no live approval exists.

Closing statement: “The POC demonstrates a reusable application pattern. The business program pairs it with dependency-aware VM migration and verified contract retirement. Our evidence distinguishes what works locally, what has run in AWS, and what still needs approval or measurement.”
