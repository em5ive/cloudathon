"""One-time, separately approved database initialization; never API-invoked.

The master identity is available only to this temporary Lambda. Secrets are
created at runtime and never returned or written into Terraform state.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets

from shared import db

LOG = logging.getLogger("retail.bootstrap")
APP_USER = "retail_app"


def scram_verifier(password):
    """Build PostgreSQL's SCRAM verifier without sending a raw password in SQL.

    Bootstrap generates printable ASCII passwords, so SASLprep is the identity
    transform. Reject other input rather than generating an incompatible verifier.
    The format follows PostgreSQL SCRAM-SHA-256 and RFC 7677.
    """
    if not isinstance(password, str) or not 24 <= len(password) <= 128 or not all(33 <= ord(char) <= 126 for char in password):
        raise RuntimeError("Application password must be 24 to 128 printable ASCII characters")
    salt = secrets.token_bytes(16)
    iterations = 4096
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("ascii"), salt, iterations)
    client_key = hmac.digest(salted, b"Client Key", "sha256")
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.digest(salted, b"Server Key", "sha256")
    encoded = lambda value: base64.b64encode(value).decode("ascii")
    return f"SCRAM-SHA-256${iterations}:{encoded(salt)}${encoded(stored_key)}:{encoded(server_key)}"


def application_credentials(client, secret_arn):
    try:
        value = json.loads(client.get_secret_value(SecretId=secret_arn)["SecretString"])
        password = value.get("password")
        if value.get("username") != APP_USER or not isinstance(password, str) or not 24 <= len(password) <= 128 or not all(33 <= ord(char) <= 126 for char in password):
            raise RuntimeError("Existing application secret has an invalid format; manual review required")
        return value
    except client.exceptions.ResourceNotFoundException:
        password = client.get_random_password(PasswordLength=48, ExcludeCharacters="'\"\\", IncludeSpace=False)["RandomPassword"]
        value = {"username": APP_USER, "password": password}
        # Write first. If initialization fails, the next approved invocation
        # reuses this same password and converges the DB role to that value.
        client.put_secret_value(SecretId=secret_arn, SecretString=json.dumps(value))
        return value


def initialize(connection, credentials):
    cursor = connection.cursor()
    cursor.execute("""SELECT r.rolsuper, r.rolcreatedb, r.rolcreaterole, r.rolreplication, r.rolbypassrls,
                      EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.member = r.oid)
                      FROM pg_roles r WHERE r.rolname = %s""", (APP_USER,))
    attributes = cursor.fetchone()
    if attributes is None:
        # PostgreSQL defaults exclude elevated privileges. Do not specify
        # NOSUPERUSER/NOREPLICATION in ALTER ROLE: changing those properties can
        # require a true PostgreSQL superuser, which the RDS master is not.
        cursor.execute("CREATE ROLE retail_app LOGIN")
    elif any(attributes):
        raise RuntimeError("Existing application role has elevated attributes or memberships; manual review required")
    # ALTER ROLE cannot bind its password literal. Pass only a SCRAM verifier as
    # a bound parameter into a transaction-local setting, then use format(%L)
    # inside a fixed block. The plaintext password never enters SQL. Terraform
    # also disables statement/bind-value logging; the exception handler prevents
    # dynamic SQL containing verifier material from reaching normal error logs.
    cursor.execute("SELECT set_config('retail.bootstrap_verifier', %s, true)", (scram_verifier(credentials["password"]),))
    cursor.execute("""DO $retail_bootstrap$
        BEGIN
            EXECUTE format('ALTER ROLE retail_app WITH LOGIN PASSWORD %L',
                           current_setting('retail.bootstrap_verifier'));
        EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION 'Unable to configure application role password';
        END; $retail_bootstrap$""")
    cursor.execute("ALTER ROLE retail_app SET statement_timeout = '8s'")
    cursor.execute("ALTER ROLE retail_app SET lock_timeout = '5s'")
    cursor.execute("ALTER ROLE retail_app SET idle_in_transaction_session_timeout = '20s'")
    # Do not grant rds_iam: standard IAM is client->proxy, while the proxy uses
    # the app secret for password authentication to Aurora PostgreSQL.
    for filename in ("schema.sql", "seed.sql"):
        cursor.execute((Path(__file__).resolve().parents[1] / "database" / filename).read_text(encoding="utf-8"))
    cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    cursor.execute("GRANT USAGE ON SCHEMA public TO retail_app")
    cursor.execute("GRANT SELECT ON products, inventory, customers, orders, order_items, support_tickets, support_requests TO retail_app")
    cursor.execute("GRANT INSERT ON customers, orders, order_items, support_tickets, support_requests TO retail_app")
    cursor.execute("GRANT UPDATE (quantity) ON inventory TO retail_app")


def handler(event, context):
    if event != {"operation": "initialize"}:
        raise ValueError("Only the explicit initialize operation is supported")
    import boto3
    client = boto3.client("secretsmanager")
    try:
        credentials = application_credentials(client, os.environ["APP_SECRET_ARN"])
        with db.transaction() as connection:
            initialize(connection, credentials)
        return {"initialized": True, "application_user": APP_USER}
    except Exception as error:
        # Do not log SQL/exception messages, which could contain credentials.
        LOG.error(json.dumps({"event": "bootstrap_failed", "type": type(error).__name__}))
        raise RuntimeError("Database initialization failed; inspect safe bootstrap logs and retry after review") from None
