# Terraform plan ready for review

**Historical initial plan — already used by the team's partial apply. Do not apply `reports/review.tfplan` again.** State now records 114 managed resources. Use the newly generated `reports/review.tfretry` and [retry review](retry-plan-review.md). The remainder of this document describes the original pre-apply review, not current deployment status.

**115 additions, 0 changes, 0 deletions. Nothing has been applied.**

The authenticated terminal created `reports/review.tfplan` at **2026-11-07 19:49:08 UTC** using Terraform 1.17.0 and the locked AWS provider 6.72.0. The readable plan is `reports/review-plan.txt`; machine-readable details and configuration checks are `reports/review-plan.json` and `reports/plan-review.json`. These artifacts are intentionally ignored by Git.

| Selection | Reviewed value |
| --- | --- |
| Account / role | `708661874787` / `WSParticipantRole` |
| Region | `us-west-2` explicitly; host default Ohio is overridden |
| Namespace | `uh-retail-poc` |
| Aurora PostgreSQL | `17.11`, freshly checked against Serverless offerings and documented Proxy support |
| AZs | `us-west-2a`, `us-west-2b` |
| Aurora capacity | 0.5–4 ACUs per instance, two instances |
| Bootstrap stage | Enabled; runtime DB authentication not yet initialized |
| Reserved concurrency | Products 3, Orders 3, Support 2, bootstrap 1: nine total |
| Remaining unreserved capacity | Fresh read: 110 before, 101 after the proposed reservations |
| Bedrock | Disabled in this initial plan; no model selected or inference invoked |
| Plan SHA-256 | `ac1cfd323a62023cefa604f2085359fdba9095106134a3f1ff7c4c66a9948078` |

## What will be created

- One VPC, four private subnets, isolated route tables, four security groups and six explicit tier-to-tier rules. No public subnet, internet gateway, NAT, EC2 web server or load balancer.
- One encrypted Aurora PostgreSQL cluster and two private Serverless v2 instances in separate AZs; seven-day backups, deletion protection and final-snapshot safeguards. Database SSL is forced.
- One TLS-required RDS Proxy with IAM client authentication and PostgreSQL SCRAM-backed secret authentication. This stage has only bootstrap/master Proxy authentication and an empty application-secret resource.
- Products, Orders, Support and temporary bootstrap Lambda functions; three stable application aliases; five IAM roles and five scoped inline policies. Normal functions are configured for the application DB identity. The four plan hashes match the current fixed ZIP artifacts.
- HTTP API Gateway with eight routes and Cognito JWT authorization on private routes. Cognito uses its AWS-hosted sign-in domain and PKCE frontend flow.
- A private encrypted S3 frontend, six objects, signed OAC and one CloudFront distribution with its default certificate and HTTP-to-HTTPS redirect. The browser calls the default API Gateway HTTPS endpoint directly. No ACM certificate, Route 53 record or custom API domain is planned.
- A temporary two-AZ Secrets Manager interface endpoint, 18 alarms, four metric filters, five log groups, one dashboard, database-event routing and an SNS operations topic. No email subscription is configured.

Sixteen checks against the actual saved plan passed. This confirms planned configuration; it does not confirm deployed TLS, application functionality, runtime authorization, failover or rollback. Values such as endpoint URLs, ARNs and part of the Lambda environment map remain unknown until resource creation. Source/mocked tests cover those configuration dependencies, and live checks remain required.

## Bootstrap impact and remaining gates

This is the **initial infrastructure stage**, not a working customer application yet. After an approved apply, a separately authorized bootstrap invocation initializes schema, fictional products, `retail_app` credentials and the new immutable support-request receipts. A second reviewed plan sets `database_bootstrapped = true` and `enable_bootstrap = false`, enabling runtime authentication while removing privileged bootstrap access and its temporary endpoints. Only then run approved application write tests.

The fresh preflight at **19:47:54 UTC** reports `ready_for_authenticated_terraform_plan = true`. Eight `servicequotas:ListServiceQuotas` denials remain **UNVERIFIED warnings**, with original errors and follow-up details preserved. They are permission restrictions on quota visibility, not evidence of exhausted quotas. No IAM permissions were changed or bypassed. Actual resource-creation permissions and unobserved quota/usage limits remain unverified; inspect any real creation/quota error if apply is later authorized. A successful plan does not grant or demonstrate create permission.

Bedrock conversational support is implemented and checked with local model fixtures, but model access/invocation is not tested. A separately reviewed model selection and enabled-AI plan are needed to create the Bedrock endpoint and allow paid inference. HTTPS, Cognito journeys, Proxy TLS, explicit escalation, failover, independent releases and monitoring still need the [live acceptance checklist](live-acceptance-checklist.md).

## Cost review

Retain the **$250–$400/month low-use planning allowance** pending a current Oregon quote. This is an estimate, not a cap. Aurora compute and the RDS Proxy billing floor dominate idle costs; backups, storage/I/O, CloudWatch and traffic add usage costs. The temporary Secrets Manager endpoint costs approximately $14.60/month under the documented assumed rate if left for a full month, and is removed after bootstrap. The current plan has no Bedrock endpoint or inference cost; enabling AI later adds endpoint and model-usage charges. See [cost-analysis.md](cost-analysis.md) for assumptions and sensitivity. Two DB instances at maximum capacity cost materially more than the minimum-capacity allowance.

## Review command

```powershell
Set-Location 'C:\Users\15kda\Documents\cloudathon'
terraform -chdir=terraform show -no-color '..\reports\review.tfplan'
Get-FileHash -Algorithm SHA256 '.\reports\review.tfplan'
```

Review the exact saved artifact, cost assumptions, IAM scope and bootstrap sequence before authorizing any apply. If configuration, variables, packages, provider selection or relevant account conditions change, generate a fresh plan. No apply or destroy command was run, and no existing state was imported, migrated or edited.
