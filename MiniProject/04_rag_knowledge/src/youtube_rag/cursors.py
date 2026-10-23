"""Authenticated cursors; offsets carry no authority and unsigned legacy cursors expire."""

import base64
import hashlib
import hmac
import json

from .errors import error


def encode(snapshot, offset, key):
    body = json.dumps(
        {"version": 1, "snapshot": snapshot, "offset": offset}, sort_keys=True
    ).encode()
    signature = hmac.new(key, body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature + body).decode()


def decode(cursor, snapshot, key):
    try:
        if not isinstance(cursor, str) or len(cursor) > 1000:
            raise ValueError
        raw = base64.b64decode(cursor.encode(), altchars=b"-_", validate=True)
        signature, body = raw[:32], raw[32:]
        if not hmac.compare_digest(signature, hmac.new(key, body, hashlib.sha256).digest()):
            raise ValueError
        value = json.loads(body)
        offset = value["offset"]
        if (
            value["version"] != 1
            or value["snapshot"] != snapshot
            or type(offset) is not int
            or offset < 0
        ):
            raise ValueError
        return offset
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise error(
            "invalid_cursor", "Cursor is invalid or its account/scope/index has changed", status=422
        ) from None
