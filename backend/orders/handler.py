"""Owned orders and atomic inventory updates with customer-scoped idempotency."""

from decimal import Decimal
import hashlib
import json
from uuid import uuid4

from shared import db
from shared.http import ApiError, body, customer_id, endpoint, idempotency_key, method, path, response, uuid_value

ORDER_COLUMNS = "id, status, total, currency, created_at"


def normalize_items(payload):
    supplied = payload.get("items")
    if not isinstance(supplied, list) or not 1 <= len(supplied) <= 20:
        raise ApiError(400, "Provide between 1 and 20 order items.")
    quantities = {}
    for item in supplied:
        if not isinstance(item, dict):
            raise ApiError(400, "Each order item must be an object.")
        product_id = uuid_value(item.get("product_id"), "Product ID")
        quantity = item.get("quantity")
        if type(quantity) is not int or not 1 <= quantity <= 100:
            raise ApiError(400, "Item quantities must be whole numbers from 1 to 100.")
        quantities[product_id] = quantities.get(product_id, 0) + quantity
        if quantities[product_id] > 100:
            raise ApiError(400, "The total quantity for one product cannot exceed 100.")
    return [{"product_id": product_id, "quantity": quantities[product_id]} for product_id in sorted(quantities)]


def owned_order(cursor, subject, order_id):
    cursor.execute(f"SELECT {ORDER_COLUMNS} FROM orders WHERE id = %s AND customer_id = %s", (order_id, subject))
    order = db.one(cursor)
    if order is None:
        # Same response for nonexistent and another customer's order.
        raise ApiError(404, "Order not found.", "not_found")
    cursor.execute("""SELECT product_id, product_name AS name, quantity, unit_price,
                      quantity * unit_price AS line_total FROM order_items
                      WHERE order_id = %s ORDER BY product_id""", (order_id,))
    order["items"] = db.rows(cursor)
    return order


def create_order(connection, subject, key, items):
    fingerprint = hashlib.sha256(json.dumps(items, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    # A transaction-scoped lock serializes concurrent retries before checking the
    # durable unique (customer_id, idempotency_key) constraint. It releases on
    # commit/rollback, including when the handler fails.
    lock_id = int.from_bytes(hashlib.sha256((subject + "\0" + key).encode()).digest()[:8], "big", signed=True)
    cursor = connection.cursor()
    db.ensure_customer(cursor, subject)
    cursor.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))
    cursor.execute("SELECT id, request_hash FROM orders WHERE customer_id = %s AND idempotency_key = %s", (subject, key))
    previous = db.one(cursor)
    if previous:
        if previous["request_hash"] != fingerprint:
            raise ApiError(409, "This Idempotency-Key was already used for a different order.", "idempotency_conflict")
        return owned_order(cursor, subject, previous["id"]), True

    lines = []
    total = Decimal("0.00")
    for item in items:  # Stable product order prevents crossed inventory deadlocks.
        cursor.execute("""SELECT p.id, p.name, p.price, p.currency, i.quantity AS stock
                          FROM products p JOIN inventory i ON i.product_id = p.id
                          WHERE p.id = %s FOR UPDATE OF i""", (item["product_id"],))
        product = db.one(cursor)
        if product is None:
            raise ApiError(404, "An ordered product was not found.", "not_found")
        if product["stock"] < item["quantity"]:
            raise ApiError(409, "An ordered product has insufficient stock.", "insufficient_stock")
        if product["currency"] != "USD":
            raise ApiError(409, "The product currency is not supported.", "currency_conflict")
        line_total = product["price"] * item["quantity"]
        total += line_total
        lines.append({"product_id": product["id"], "name": product["name"], "quantity": item["quantity"],
                      "unit_price": product["price"], "line_total": line_total})

    order_id = str(uuid4())
    cursor.execute("""INSERT INTO orders (id, customer_id, status, total, currency, idempotency_key, request_hash)
                      VALUES (%s, %s, 'received', %s, 'USD', %s, %s) RETURNING created_at""",
                   (order_id, subject, total, key, fingerprint))
    created_at = cursor.fetchone()[0]
    for line in lines:
        cursor.execute("UPDATE inventory SET quantity = quantity - %s WHERE product_id = %s", (line["quantity"], line["product_id"]))
        cursor.execute("""INSERT INTO order_items (order_id, product_id, product_name, quantity, unit_price)
                          VALUES (%s, %s, %s, %s, %s)""",
                       (order_id, line["product_id"], line["name"], line["quantity"], line["unit_price"]))
    return {"id": order_id, "status": "received", "total": total, "currency": "USD", "created_at": created_at, "items": lines}, False


@endpoint
def handler(event, context):
    subject = customer_id(event)
    request_path = path(event)
    request_method = method(event)
    if request_path == "/api/orders" and request_method == "POST":
        key = idempotency_key(event)
        items = normalize_items(body(event))
        with db.transaction() as connection:
            order, replayed = create_order(connection, subject, key, items)
        return response(200 if replayed else 201, {"order": order, "replayed": replayed})
    if request_method == "GET":
        with db.transaction() as connection:
            cursor = connection.cursor()
            if request_path == "/api/orders":
                cursor.execute(f"SELECT {ORDER_COLUMNS} FROM orders WHERE customer_id = %s ORDER BY created_at DESC LIMIT 50", (subject,))
                result = {"orders": db.rows(cursor)}
            elif request_path.startswith("/api/orders/"):
                order_id = uuid_value(request_path.removeprefix("/api/orders/"), "Order ID")
                result = {"order": owned_order(cursor, subject, order_id)}
            else:
                raise ApiError(404, "Route not found.", "not_found")
        return response(200, result)
    raise ApiError(405, "Method not allowed.", "method_not_allowed")
