"""Public catalog; no customer data is returned."""

from shared import db
from shared.http import ApiError, endpoint, method, path, response, uuid_value

SELECT = """SELECT p.id, p.name, p.description, p.price, p.currency, i.quantity AS stock
            FROM products p JOIN inventory i ON i.product_id = p.id"""


@endpoint
def handler(event, context):
    if method(event) != "GET":
        raise ApiError(405, "Method not allowed.", "method_not_allowed")
    request_path = path(event)
    with db.transaction() as connection:
        cursor = connection.cursor()
        if request_path == "/api/products":
            cursor.execute(SELECT + " ORDER BY p.name LIMIT 100")
            return response(200, {"products": db.rows(cursor)})
        if request_path.startswith("/api/products/"):
            product_id = uuid_value(request_path.removeprefix("/api/products/"), "Product ID")
            cursor.execute(SELECT + " WHERE p.id = %s", (product_id,))
            product = db.one(cursor)
            if product is None:
                raise ApiError(404, "Product not found.", "not_found")
            return response(200, {"product": product})
    raise ApiError(404, "Route not found.", "not_found")
