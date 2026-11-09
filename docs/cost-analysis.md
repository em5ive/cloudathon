# Cost and quantified business case

All amounts are USD. Company invoices and AWS account pricing were unavailable on November 7, 2026. No company cost or realized saving is asserted. Separate the small application POC budget from the fleet business case; multiplying the POC's two-instance database cost by every VM would be misleading.

## Representative application budget

Planning assumptions: `us-west-2`, 730 hours/month, two continuously available Aurora instances at 0.5 ACU each, maximum 4 ACUs each, 10 GB Aurora storage, light demo traffic, two secrets, and optional Bedrock Runtime endpoints in two AZs. Temporary Secrets Manager endpoints serve bootstrap and are removed by the second reviewed plan. Exclude credits, tax, negotiated discounts and any assumption that the workshop is free. Rates below are editable **planning estimates**, not a verified Oregon quote. Refresh AWS Pricing Calculator or the public price list before approval.

| Component | Planning calculation | Monthly estimate |
| --- | --- | ---: |
| Aurora compute at configured minimum | `2 × 0.5 × 730 × $0.12/ACU-hour` | $87.60 |
| RDS Proxy | Budget 8–16 billable ACUs at `$0.015/ACU-hour × 730`; confirm minimum/instance aggregation in quote | $87.60–$175.20 |
| Optional Bedrock Runtime endpoints, steady state | `1 service × 2 AZs × 730 × $0.01/endpoint-AZ-hour` | $14.60 |
| Aurora storage, I/O, backup overage | Allowance; volume/retained snapshots change it | $5–$15 |
| Secrets, requests and optional rotation | Allowance | $1–$3 |
| Lambda + HTTP API | Low-volume allowance; memory, duration, concurrency and calls drive cost | $1–$5 |
| S3 + CloudFront + transfer | Light static-content allowance; remote-region and internet bytes matter | $2–$10 |
| CloudWatch logs, metrics, alarms, dashboard | Allowance; retention and detailed metrics matter | $5–$15 |
| Cognito and optional Bedrock usage | Allowance; tier/model/MAUs/tokens unverified | $5–$20 |
| **Planning total at DB minimum, with AI endpoints** | Sum; round for review | **about $210–$350/month** |

Allow **$250–$400/month** pending a verified quote and usage estimate. This is not a spending cap. At eight aggregate DB ACUs continuously, the same assumed DB compute rate becomes `$700.80/month` before Proxy or other services. Concurrency throttles and ACU limits control capacity, while a budget alarm only notifies. RDS Proxy has an eight-ACU minimum for Aurora Serverless according to the [AWS pooling comparison](https://aws.amazon.com/blogs/database/understanding-the-differences-between-pgbouncer-and-amazon-rds-proxy-for-postgresql-connection-pooling/); do not price it as merely one billable ACU because the DB's aggregate minimum is one. The conservative range explicitly reserves room for unresolved billing aggregation.

The [Aurora pricing page](https://aws.amazon.com/rds/aurora/pricing/) describes separate compute, storage and I/O charges. The [RDS Proxy pricing page](https://aws.amazon.com/rds/proxy/pricing/) describes capacity billing and extra endpoint charges. These pages were consulted; their dynamic Oregon rate tables were not extracted or authenticated. An attempted public-price JSON fetch was blocked by execution-network restrictions. Exact rates therefore remain a pre-apply check.

## Endpoints versus two NAT gateways

At the planning rates of `$0.01/endpoint-AZ-hour` and `$0.01/GB`, one two-AZ Bedrock service costs `$14.60/month + processing`. With AI and bootstrap disabled, no paid interface endpoint remains. Temporary two-AZ Secrets Manager endpoints add `$14.60` if retained for a full month, prorated for actual bootstrap hours; they are removed afterward because Proxy retrieves secrets through its AWS-managed integration and normal functions sign IAM tokens locally. Two NAT gateways at an assumed `$0.045/hour` plus two public IPv4 addresses at `$0.005/hour` cost `$73.00/month + NAT processing`, before other data transfer. For a future app with more services, four two-AZ endpoint services cost `$58.40`; six cost `$87.60`, so hourly costs alone can favor NAT as service count grows. Compare actual GB and cross-AZ routes too. See [PrivateLink pricing](https://aws.amazon.com/privatelink/pricing/) and [VPC pricing](https://aws.amazon.com/vpc/pricing/).

This application needs few AWS APIs and no arbitrary internet calls, so endpoint-only routing is simple and cost-appropriate under these assumptions. Do not deploy NAT plus redundant endpoints by default. Bedrock cost is per selected model and actual token/request usage; no model has been verified for this account. See [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/). Two-AZ availability and Proxy are explicit requirements even when a single instance would be cheaper.

## Fleet business case: replace every example with evidence

The following is a **fictional sensitivity example** to make the calculation reviewable. It is not company financial data, an AWS quote or a forecast. Categories are annual recurring cost assumptions normalized to the same scope and service level; labor allocations and annualized hardware are economic costs, not necessarily avoidable cash outlays. Show cash, sunk costs and released staff capacity separately when making a cancellation decision. Count a staffing benefit as cash savings only when an actual expense stops.

| Current annual expense | Illustrative amount |
| --- | ---: |
| Virtualization platform + platform support | $180,000 |
| Guest OS subscriptions/support | $60,000 |
| DB licenses/support | $90,000 |
| Application/middleware licenses | $70,000 |
| Lease, power, facility services | $180,000 |
| Hardware/storage/network maintenance or annualized renewal | $120,000 |
| Operations labor allocated to this scope | $200,000 |
| **Illustrative current annual total** | **$900,000** |

| Future annual expense | Illustrative amount |
| --- | ---: |
| AWS compute, managed DB, storage, network, observability, support | $360,000 |
| Continuing software licenses/support not already in AWS service rates | $80,000 |
| Residual operations labor | $160,000 |
| **Illustrative steady-state annual total** | **$600,000** |

Illustrative transition cash: `$180,000 migration effort + $100,000 refactoring + $10,000 transfer/tooling + $60,000 incremental dual-running = $350,000`. The overlap line is the **extra** cost relative to continuing the source baseline during transition; do not add the full source baseline again. Include replication EC2/EBS, test instances, connectivity, retained source contracts and unexpected licensing in real estimates. Some MGN service usage can be free for a limited per-server period, while its replication and target resources still cost money. See [MGN pricing](https://aws.amazon.com/application-migration-service/pricing/).

`Annual savings = avoidable current annual cost − future annual recurring cost`.

`Simple payback months after full retirement = transition cash ÷ (annual savings ÷ 12)` when savings are positive. In this fictional example, annual saving is `$300,000` (33.3%) and simple payback is **14 months after steady state**. A 25% increase in future annual cost gives `$150,000` annual savings and **28 months**; a 25% decrease gives `$450,000` and **9.3 months**. If future cost equals or exceeds avoidable source cost, no positive simple payback exists. A discounted cash-flow model and monthly ramp are needed for an investment decision.

The actual payback is **unknown** until invoices, rightsizing data, licensing commitments, migration effort and contract termination dates exist. Partial wave savings should be modeled in a monthly ledger: source cash still payable + target usage + one-time work − business-as-usual source baseline. Lease savings cannot be recognized before avoidability, and an unreduced platform renewal cannot be counted as retired. Use `scripts/business-case.py` with evidence-backed inputs; preserve its assumptions with the generated output.

For remaining VMs, first compare rightsized rehosted EC2 (including OS/DB licenses, EBS, backup, support and patching) with source TCO. Then prioritize modernization by engineering effort, licensing exposure and expected recurring savings. Commitments or Savings Plans should follow measured stable usage, not speculative fleet sizes. Standardizing landing zones and migration waves improves migration speed, while modernization creates later opportunities to reduce continuing licenses and operations.
