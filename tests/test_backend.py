"""Offline safety tests. These do not replace live Aurora/Proxy acceptance tests."""

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import ssl
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bootstrap import handler as bootstrap
from orders import handler as orders
from products import handler as products
from shared import db
from shared.http import ApiError, MAX_BODY_BYTES, body
from support import handler as support

PRODUCT = "11111111-1111-4111-8111-111111111111"
ORDER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TICKET = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
ITEMS = [{"product_id": PRODUCT, "quantity": 2}]


def event(path="/api/orders", method="POST", payload=None, authenticated=True, key="request-key-123"):
    result = {"rawPath": path, "requestContext": {"http": {"method": method}}, "headers": {"Idempotency-Key": key}}
    if authenticated:
        result["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": "customer-a"}}}
    if payload is not None:
        result["body"] = json.dumps(payload)
    return result


def decoded(result):
    return json.loads(result["body"])


class Cursor:
    """Small scripted database boundary with assertions on security-critical SQL."""
    def __init__(self, results):
        self.results = iter(results)
        self.description = []
        self.values = []
        self.statements = []

    def execute(self, sql, parameters=None):
        self.statements.append((" ".join(sql.split()), parameters))
        columns, self.values = next(self.results)
        self.description = [(column,) for column in columns]
        return self

    def fetchone(self):
        return self.values.pop(0) if self.values else None

    def fetchall(self):
        values, self.values = self.values, []
        return values


def connection(results):
    cursor = Cursor(results)
    value = Mock()
    value.cursor.return_value = cursor
    return value, cursor


def product_result(stock=10):
    return (["id", "name", "price", "currency", "stock"], [(PRODUCT, "Speaker", Decimal("29.99"), "USD", stock)])


class RequestTests(unittest.TestCase):
    def test_invalid_json_rejected(self):
        for raw in ("[1,2]", "not json", "null", '{"x":NaN}'):
            with self.subTest(raw=raw), self.assertRaises(ApiError):
                body({"body": raw})

    def test_body_length_is_bounded(self):
        with self.assertRaises(ApiError) as error:
            body({"body": "x" * (MAX_BODY_BYTES * 2 + 1)})
        self.assertEqual(error.exception.status, 413)

    def test_invalid_base64_rejected(self):
        with self.assertRaises(ApiError):
            body({"body": "%%%", "isBase64Encoded": True})

    def test_order_requires_auth_before_database_access(self):
        with patch.object(db, "connect") as connect:
            result = orders.handler(event(authenticated=False, payload={"items": ITEMS}), None)
        self.assertEqual(result["statusCode"], 401)
        connect.assert_not_called()

    def test_support_requires_auth(self):
        result = support.handler(event(path="/api/support", authenticated=False, payload={"message": "Help"}), None)
        self.assertEqual(result["statusCode"], 401)

    def test_order_requires_idempotency_key_before_database(self):
        with patch.object(db, "connect") as connect:
            result = orders.handler(event(payload={"items": ITEMS}, key=""), None)
        self.assertEqual(result["statusCode"], 400)
        connect.assert_not_called()

    def test_quantity_validation_rejects_bool_fraction_negative_and_text(self):
        for quantity in (True, 0, -1, 1.5, "2", 101):
            with self.subTest(quantity=quantity), self.assertRaises(ApiError):
                orders.normalize_items({"items": [{"product_id": PRODUCT, "quantity": quantity}]})

    def test_item_order_is_canonical_and_duplicates_combined(self):
        second = "22222222-2222-4222-8222-222222222222"
        self.assertEqual(orders.normalize_items({"items": [
            {"product_id": second, "quantity": 1}, {"product_id": PRODUCT, "quantity": 2},
            {"product_id": PRODUCT, "quantity": 3}]}), [
            {"product_id": PRODUCT, "quantity": 5}, {"product_id": second, "quantity": 1}])

    def test_aggregate_quantity_bounded(self):
        with self.assertRaises(ApiError):
            orders.normalize_items({"items": [{"product_id": PRODUCT, "quantity": 60}] * 2})

    def test_safe_exception_does_not_leak_details(self):
        with patch.object(db, "connect", side_effect=RuntimeError("password=do-not-leak")):
            result = products.handler(event(path="/api/products", method="GET", authenticated=False), None)
        self.assertEqual(result["statusCode"], 503)
        self.assertNotIn("do-not-leak", result["body"])
        self.assertEqual(result["headers"]["cache-control"], "no-store")


class OrderTests(unittest.TestCase):
    def test_order_uses_server_price_and_commits_inventory_with_order(self):
        conn, cursor = connection([
            ([], []), ([], []), (["id", "request_hash"], []), product_result(),
            (["created_at"], [(NOW,)]), ([], []), ([], []),
        ])
        with patch.object(db, "connect", return_value=conn):
            result = orders.handler(event(payload={"items": ITEMS, "total": "0.01", "customer_id": "victim"}), None)
        self.assertEqual(result["statusCode"], 201)
        order = decoded(result)["order"]
        self.assertEqual(order["total"], "59.98")
        self.assertEqual(order["items"][0]["unit_price"], "29.99")
        inventory_changes = [(sql, params) for sql, params in cursor.statements if sql.startswith("UPDATE inventory")]
        self.assertEqual(inventory_changes[0][1], (2, PRODUCT))
        insert_order = next(params for sql, params in cursor.statements if sql.startswith("INSERT INTO orders"))
        self.assertEqual(insert_order[1], "customer-a")
        self.assertTrue(any("FOR UPDATE OF i" in sql for sql, _ in cursor.statements))
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()
        conn.close.assert_called_once()

    def test_insufficient_stock_rolls_back_without_order_or_inventory_write(self):
        conn, cursor = connection([( [], []), ([], []), (["id", "request_hash"], []), product_result(stock=1)])
        with patch.object(db, "connect", return_value=conn):
            result = orders.handler(event(payload={"items": ITEMS}), None)
        self.assertEqual(result["statusCode"], 409)
        self.assertEqual(decoded(result)["code"], "insufficient_stock")
        self.assertFalse(any(sql.startswith(("UPDATE inventory", "INSERT INTO orders")) for sql, _ in cursor.statements))
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_retry_returns_same_order_without_changing_inventory(self):
        fingerprint = hashlib.sha256(json.dumps(ITEMS, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        conn, cursor = connection([
            ([], []), ([], []), (["id", "request_hash"], [(ORDER, fingerprint)]),
            (["id", "status", "total", "currency", "created_at"], [(ORDER, "received", Decimal("59.98"), "USD", NOW)]),
            (["product_id", "name", "quantity", "unit_price", "line_total"], [(PRODUCT, "Speaker", 2, Decimal("29.99"), Decimal("59.98"))]),
        ])
        with patch.object(db, "connect", return_value=conn):
            result = orders.handler(event(payload={"items": ITEMS}), None)
        self.assertEqual(result["statusCode"], 200)
        self.assertTrue(decoded(result)["replayed"])
        self.assertEqual(decoded(result)["order"]["id"], ORDER)
        self.assertFalse(any(sql.startswith(("UPDATE inventory", "INSERT INTO orders")) for sql, _ in cursor.statements))

    def test_same_key_different_cart_is_conflict(self):
        conn, _ = connection([( [], []), ([], []), (["id", "request_hash"], [(ORDER, "different-hash")])])
        with patch.object(db, "connect", return_value=conn):
            result = orders.handler(event(payload={"items": ITEMS}), None)
        self.assertEqual(result["statusCode"], 409)
        self.assertEqual(decoded(result)["code"], "idempotency_conflict")
        conn.rollback.assert_called_once()

    def test_another_customers_order_is_not_found(self):
        conn, cursor = connection([(["id", "status", "total", "currency", "created_at"], [])])
        with patch.object(db, "connect", return_value=conn):
            result = orders.handler(event(path=f"/api/orders/{ORDER}", method="GET"), None)
        self.assertEqual(result["statusCode"], 404)
        self.assertIn("customer_id = %s", cursor.statements[0][0])
        self.assertEqual(cursor.statements[0][1], (ORDER, "customer-a"))

    def test_read_order_query_scopes_customer(self):
        conn, cursor = connection([(["id", "status", "total", "currency", "created_at"], [])])
        with patch.object(db, "connect", return_value=conn):
            result = orders.handler(event(path="/api/orders", method="GET"), None)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(decoded(result), {"orders": []})
        self.assertEqual(cursor.statements[0][1], ("customer-a",))


class DatabaseSecurityTests(unittest.TestCase):
    def test_tls_requires_hostname_certificate_and_modern_protocol(self):
        context = Mock()
        with patch.object(db.ssl, "create_default_context", return_value=context), patch.object(Path, "is_file", return_value=True), patch.object(Path, "glob", return_value=[]):
            result = db.tls_context()
        self.assertIs(result, context)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertTrue(context.load_verify_locations.called)

    def test_missing_rds_bundle_fails_closed(self):
        with patch.object(Path, "is_file", return_value=False), self.assertRaises(RuntimeError):
            db.tls_context()

    def test_transaction_closes_connection_on_commit_failure(self):
        conn = Mock()
        conn.commit.side_effect = RuntimeError("unknown commit result")
        with patch.object(db, "connect", return_value=conn), self.assertRaises(RuntimeError):
            with db.transaction():
                pass
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    def test_proxy_connection_uses_iam_token_and_verified_ssl_context(self):
        boto3 = ModuleType("boto3")
        client = Mock()
        client.generate_db_auth_token.return_value = "short-lived-token"
        boto3.client = Mock(return_value=client)
        pg8000 = ModuleType("pg8000")
        pg8000.dbapi = ModuleType("pg8000.dbapi")
        pg8000.dbapi.connect = Mock()
        with patch.dict(sys.modules, {"boto3": boto3, "pg8000": pg8000, "pg8000.dbapi": pg8000.dbapi}), \
             patch.dict(os.environ, {"DB_HOST": "proxy.example.amazonaws.com", "DB_USER": "retail_app", "DB_NAME": "retail"}), \
             patch.object(db, "tls_context", return_value="verified-context"):
            db.connect()
        client.generate_db_auth_token.assert_called_once_with(DBHostname="proxy.example.amazonaws.com", Port=5432, DBUsername="retail_app")
        self.assertEqual(pg8000.dbapi.connect.call_args.kwargs["password"], "short-lived-token")
        self.assertEqual(pg8000.dbapi.connect.call_args.kwargs["ssl_context"], "verified-context")


class BootstrapTests(unittest.TestCase):
    def test_existing_secret_is_reused_for_recoverable_bootstrap(self):
        class NotFound(Exception):
            pass
        client = Mock()
        client.exceptions = SimpleNamespace(ResourceNotFoundException=NotFound)
        client.get_secret_value.return_value = {"SecretString": json.dumps({"username": "retail_app", "password": "x" * 48})}
        value = bootstrap.application_credentials(client, "test-secret")
        self.assertEqual(value["password"], "x" * 48)
        client.get_random_password.assert_not_called()
        client.put_secret_value.assert_not_called()

    def test_missing_secret_version_is_written_before_database_work(self):
        class NotFound(Exception):
            pass
        client = Mock()
        client.exceptions = SimpleNamespace(ResourceNotFoundException=NotFound)
        client.get_secret_value.side_effect = NotFound()
        client.get_random_password.return_value = {"RandomPassword": "x" * 48}
        value = bootstrap.application_credentials(client, "test-secret")
        self.assertEqual(value["username"], "retail_app")
        saved = json.loads(client.put_secret_value.call_args.kwargs["SecretString"])
        self.assertEqual(saved, value)

    def test_bootstrap_rejects_arbitrary_operation(self):
        with self.assertRaises(ValueError):
            bootstrap.handler({"operation": "run_sql", "sql": "DROP TABLE orders"}, None)

    def test_role_grants_do_not_include_schema_creation_or_master_privileges(self):
        cursor = Mock()
        cursor.fetchone.return_value = None
        conn = Mock()
        conn.cursor.return_value = cursor
        password = "a'b" * 16
        with patch.object(Path, "read_text", return_value="SELECT 1;"):
            bootstrap.initialize(conn, {"password": password})
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("CREATE ROLE retail_app LOGIN" in sql for sql in statements))
        self.assertFalse(any(sql.startswith("ALTER ROLE") and any(flag in sql for flag in ("SUPERUSER", "REPLICATION")) for sql in statements))
        self.assertFalse(any(password in sql for sql in statements))
        self.assertTrue(any("EXCEPTION WHEN OTHERS" in sql for sql in statements))
        bound = next(call.args[1] for call in cursor.execute.call_args_list if "set_config" in call.args[0])
        self.assertTrue(bound[0].startswith("SCRAM-SHA-256$4096:"))
        self.assertNotIn(password, bound[0])
        self.assertTrue(any("REVOKE CREATE ON SCHEMA public FROM PUBLIC" in sql for sql in statements))
        self.assertFalse(any("GRANT rds_iam" in sql or "GRANT ALL" in sql for sql in statements))

    def test_existing_elevated_database_role_fails_before_setting_password(self):
        cursor = Mock()
        cursor.fetchone.return_value = (False, False, False, False, False, True)
        conn = Mock()
        conn.cursor.return_value = cursor
        with self.assertRaises(RuntimeError):
            bootstrap.initialize(conn, {"password": "strong-printable-password-123"})
        cursor.execute.assert_called_once()

    def test_scram_verifier_uses_unique_salt_and_never_contains_password(self):
        first = bootstrap.scram_verifier("strong-printable-password-123")
        second = bootstrap.scram_verifier("strong-printable-password-123")
        self.assertNotEqual(first, second)
        self.assertNotIn("strong-printable-password-123", first)
        self.assertRegex(first, r"^SCRAM-SHA-256\$4096:[A-Za-z0-9+/]+=*\$[A-Za-z0-9+/]+=*:[A-Za-z0-9+/]+=*$")

    def test_scram_verifier_rejects_incompatible_or_short_passwords(self):
        for password in ("short", "unicode-password-with-\u00e9-12345", "password-with-a-space 12345"):
            with self.subTest(password=password), self.assertRaises(RuntimeError):
                bootstrap.scram_verifier(password)


if __name__ == "__main__":
    unittest.main()
