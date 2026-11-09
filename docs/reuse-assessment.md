# Reference architecture assessment

Reviewed on November 7, 2026. The Cloudathon repository was empty. The six user-named files in `C:\Users\15kda\test-tf` were read as reference only. Its `.terraform/`, saved plan, state, state backup, and backend were not copied or imported. No helpdesk source was available in this repository. Statements in reference documents are context; the user's current requirements govern this implementation.

| Reference | Keep as a design principle | Replace or change in this repository |
| --- | --- | --- |
| `network.tf` | Two AZs, separate application/database subnets, isolated DB routes | Replace hardcoded `us-east-2a/b` with selected `us-west-2` AZs. Use private application and DB subnets. Temporary Secrets Manager endpoints serve bootstrap; optional Bedrock Runtime endpoints serve Support. Omit public subnets, IGW and NAT for this POC. |
| `security_groups.tf` | Explicit tier-to-tier SG references and stateful replies | Replace ALB HTTP/80 and MySQL/3306 paths with Lambda → Proxy → Aurora TCP/5432. Remove unrestricted web egress; permit Lambda HTTPS only to endpoint SGs. |
| `compute.tf` | Independent capacity, health monitoring, staged releases; IMDSv2 was appropriate for EC2 | Replace EC2/Apache launch template, ASG, ALB and EC2 request scaling with S3/CloudFront, HTTP API and three Lambda services. Replace HTTP output with HTTPS service URLs. |
| `iam.tf` | Service roles and managed credential delivery | Replace fixed `ec2_ssm` names, EC2 trust and instance profile with scoped Lambda and Proxy roles. App functions must not connect as DB master. |
| `RDS.tf` | Two private DB instances, failover priorities, encryption, managed master secret, seven-day backups | Create a separate PostgreSQL Serverless v2 cluster. Replace provisioned MySQL configuration and port. Require TLS, add Proxy, protect deletion and retain a final snapshot. Review upgrades explicitly rather than copying `ignore_changes` on engine version. |
| `varibales.tf` | Reusable inputs and backup-retention validation | Correct filename in new code; do not carry over MySQL `8.4.8` or `db.t4g.medium`. Require an authenticated engine/version/class availability check before choosing PostgreSQL inputs. |

Copying the old modules unchanged would retain references to removed ALB/EC2 resources, the wrong region, wrong database engine/port, an unrestricted outbound rule and an HTTP website. An in-place MySQL-to-PostgreSQL conversion is not a supported migration plan. Existing production data would require separate schema conversion, data movement, reconciliation and approved cutover.

Virtualization licensing savings require workload retirement and contract changes. Replacing this representative application's web VMs demonstrates one modernization pattern; it does not prove that the full fleet has migrated or that every license disappears.
