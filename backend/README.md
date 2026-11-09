# Retail Lambda services

Python 3.13 with the pure Python `pg8000` driver. `boto3` and `botocore` come from
the AWS Lambda runtime; pinning them in a future layer is an operational choice.
No SDK clients or database connections are created at import time.

Every database connection uses a verified SSL context with hostname verification,
TLS 1.2 or newer, the system CA trust store for Proxy's ACM-issued certificate,
and the packaged regional AWS RDS CA bundle. Missing CA files fail closed. IAM
tokens authenticate Lambda to RDS Proxy; Proxy uses a Secrets Manager password to
authenticate to Aurora. Application functions have no master-secret access.

`products`, `orders`, and `support` deploy separately. Currency amounts are JSON
strings to preserve decimal precision. Customer IDs always come from the verified
API Gateway JWT `sub`. All responses use `Cache-Control: no-store`.

Orders and support POSTs require `Idempotency-Key` (8–128 safe characters).
Keep the same key when retrying an uncertain network result. A key reused with
different normalized input returns 409. Per-customer advisory transaction locks
and database unique constraints prevent duplicate creation. Inventory rows are
locked in sorted product order; price comes from PostgreSQL. No payment occurs.
The client may retry a failed order with the same key; the server never blindly
retries a transaction whose commit result is uncertain.

Bedrock Converse now generates actual conversational replies, low-risk product
troubleshooting and follow-up questions. The model receives only the selected
authorized order reference/status and product description, plus bounded untrusted
conversation text. It has no SQL, tool access, customer list, payment data or
authority to create tickets. Private order ownership is checked before inference.
History cannot authorize a record or override instructions. Native model-specific
structured output is not assumed: the application strictly parses and validates
a portable JSON reply, steps and follow-up schema. It rejects numerical,
financial, fulfillment, stock, ETA/tracking and unsafe repair claims; invalid,
truncated, unavailable or failed model output produces deterministic fallback.
Generated prose and server-authored database facts are separate response fields.
Generated English text is compatibility-normalized; unsupported control, combining
and mixed-script characters fail closed so obfuscation cannot trivially bypass
the claim checks. Customer messages and history still accept Unicode.
These conservative content filters can reject helpful prose as well as unsafe
claims; a live model evaluation is required before broader production support.

`POST /api/support` accepts `message`, optional `order_id` / `product_id`, optional
`history` (at most six `{role: "user"|"assistant", content: "..."}` entries, at most
2,000 characters each and 6,000 combined), and `escalate` (boolean, false by
default). A normal conversation returns HTTP 200 with `ticket: null`. Only an
explicit `escalate: true` request creates an Aurora ticket (HTTP 201); escalation
uses deterministic confirmation and does not require a second model invocation.
An unavailable model does not automatically open a ticket. Use a **new key** for
escalation: changing an existing request's escalation flag with the same key is a
409 conflict. Response fields are `answer`, `order`, `product`, `ticket`,
`ai_available`, `replayed`, and `facts_as_of` (UTC capture timestamp).

The support workflow first reads a customer-scoped response receipt and authorizes
selected facts in a short transaction. The connection is committed and closed
**before** Bedrock client creation/inference. Then a separate short transaction
rechecks receipt/ownership, optionally inserts the explicit ticket, and inserts an
immutable `support_requests` response receipt atomically. A customer/key advisory
transaction lock plus database uniqueness selects one winning response and ticket
for concurrent retries. Simultaneous requests can spend inference twice; they
return the first committed response and create at most one ticket. Chat also
persists a receipt to preserve answers after uncertain network/commit results;
it does not create a support ticket. No long-lived connection, processing row,
lease or database lock is held during AI. A retry must retain its original key
and normalized message/context. Prior-version ticket replay remains protected.

Returned facts are snapshots labeled `facts_as_of`, not a promise of the current
state after inference. A replay returns the exact saved snapshot even if order
status or stock later changes; send a new question/key to refresh. Authorization
is rechecked before persistence if an order was selected. The selected product
snapshot survives explicit escalation in the receipt and is exposed by the
customer-scoped ticket list/detail join. The model cannot set ticket status or
priority. Response receipts store bounded answers/facts, not full request history;
production requires a defined data-retention policy for tickets and receipts.

The new receipt table is an additive `CREATE TABLE IF NOT EXISTS` schema change.
Fresh bootstrap grants only SELECT/INSERT for it; normal Lambda functions have no
UPDATE/DELETE/DDL privileges on receipts. An already initialized deployment needs
a separately approved schema/grant migration before deploying this support code.
Do not rebuild Aurora or silently re-enable master access to apply an update.

Bootstrap is a temporary, privileged Lambda with no API route. Its only accepted
payload is `{"operation":"initialize"}`. Deploy the initial proxy with only its
managed master secret, invoke bootstrap only after explicit approval, then plan
and approve the second Terraform phase that enables the application secret and
removes bootstrap/master proxy authentication. Initialization reads or creates an
application password in Secrets Manager, then applies schema, seed, role password
and grants in one database transaction. A failure after secret creation is
recoverable: rerunning reuses the current secret value and completes the role
transaction. Never rotate this password by changing only one side; design a
separate tested rotation process first. Seed preserves existing stock and prices.
Bootstrap derives a SCRAM-SHA-256 verifier locally, passes it as a bound parameter,
and sets the role through a fixed block. Raw passwords never enter SQL. Disable
statement logging and bind-parameter logging during bootstrap; verifier material
also requires protection. Generated passwords are 48 printable ASCII characters.
New roles use PostgreSQL's defaults for restricted privileges. Existing roles with
elevated attributes or any role memberships fail for manual review, rather than
attempting superuser-only attribute changes that an RDS master cannot perform.

The database grants permit only current API operations. A production system should
consider dedicated DB roles per service and row-level security as defense in depth.
Current customer isolation is enforced by parameterized application queries and
the API JWT authorizer; live acceptance testing remains required.
