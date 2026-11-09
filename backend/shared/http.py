"""HTTP API v2 parsing, bounded inputs and safe error responses."""

import base64
import binascii
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
import json
import logging
import re
from uuid import UUID

LOG = logging.getLogger("retail")
LOG.setLevel(logging.INFO)
MAX_BODY_BYTES = 16_384


class ApiError(Exception):
    def __init__(self, status, message, code="invalid_request"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def json_default(value):
    if isinstance(value, Decimal):
        return format(value, ".2f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError("Unsupported response value")


def response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
        },
        "body": json.dumps(body, default=json_default, separators=(",", ":")),
    }


def endpoint(function):
    @wraps(function)
    def guarded(event, context):
        try:
            return function(event, context)
        except ApiError as error:
            return response(error.status, {"error": error.message, "code": error.code})
        except Exception as error:
            # Exception messages, SQL, bodies and auth headers can contain secrets/PII.
            LOG.error(json.dumps({"event": "request_failed", "type": type(error).__name__}))
            return response(503, {"error": "Service temporarily unavailable. Retry safely.", "code": "unavailable"})
    return guarded


def method(event):
    return event.get("requestContext", {}).get("http", {}).get("method", "").upper()


def path(event):
    return event.get("rawPath", "").rstrip("/")


def customer_id(event):
    # API Gateway validates JWT signature, issuer, audience and access-token scopes.
    # Never accept customer IDs from the body, query string or arbitrary headers.
    subject = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {}).get("sub")
    if not isinstance(subject, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", subject):
        raise ApiError(401, "Authentication required.", "unauthorized")
    return subject


def body(event):
    raw = event.get("body", "") or ""
    if not isinstance(raw, str) or len(raw) > MAX_BODY_BYTES * 2:
        raise ApiError(413, "Request body is too large.", "body_too_large")
    try:
        decoded = base64.b64decode(raw, validate=True) if event.get("isBase64Encoded") else raw.encode("utf-8")
        if len(decoded) > MAX_BODY_BYTES:
            raise ApiError(413, "Request body is too large.", "body_too_large")
        def reject_nonfinite(value):
            raise ValueError("JSON numbers must be finite")
        value = json.loads(decoded, parse_constant=reject_nonfinite)
    except (ValueError, UnicodeError, binascii.Error):
        raise ApiError(400, "Provide a valid JSON object.") from None
    if not isinstance(value, dict):
        raise ApiError(400, "Provide a valid JSON object.")
    return value


def uuid_value(value, label="ID"):
    if not isinstance(value, str):
        raise ApiError(400, f"{label} must be a UUID.")
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise ApiError(400, f"{label} must be a UUID.") from None


def idempotency_key(event):
    headers = {str(key).lower(): value for key, value in (event.get("headers") or {}).items()}
    value = headers.get("idempotency-key")
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", value):
        raise ApiError(400, "Provide an Idempotency-Key header of 8 to 128 safe characters.")
    return value
