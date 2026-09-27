# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Helpers for signed backend-to-Hypatia requests."""

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.parse import urlunparse


def add_query_params(url, **params):
    """Return one URL with extra query parameters merged in."""
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value is None:
            continue
        query[str(key)] = str(value)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query),
            parsed.fragment,
        )
    )


def request_path_with_query(url):
    """Return the request path and query string for signing."""
    parsed = urlparse(url)
    request_path = parsed.path or "/"
    if parsed.query:
        request_path = f"{request_path}?{parsed.query}"
    return request_path


def build_canonical_payload(method, request_path, field_lines, timestamp, nonce):
    """Return the canonical payload string used for HMAC signing."""
    lines = [method.upper(), request_path]
    lines.extend(str(line) for line in field_lines)
    lines.append(f"timestamp={timestamp}")
    lines.append(f"nonce={nonce}")
    return "\n".join(lines)


def sign_payload(secret, payload):
    """Return the lowercase HMAC-SHA256 hex digest for one payload."""
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def signed_request_headers(secret, method, request_url, field_lines, timestamp=None, nonce=None):
    """Return signed request headers for one outbound Hypatia call."""
    timestamp = str(timestamp or int(datetime.now(timezone.utc).timestamp()))
    nonce = nonce or secrets.token_urlsafe(12)
    request_path = request_path_with_query(request_url)
    payload = build_canonical_payload(method, request_path, field_lines, timestamp, nonce)
    signature = sign_payload(secret, payload)
    return {
        "User-Agent": "MatF-App/1.0",
        "X-Request-Timestamp": timestamp,
        "X-Request-Nonce": nonce,
        "X-Request-Signature": signature,
    }
