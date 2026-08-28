"""Cryptographic derivation and compact signed-capability helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any


class SecurityError(ValueError):
    """Raised when a signed identity or capability cannot be trusted."""


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign(secret: bytes, payload: dict[str, Any]) -> str:
    return _b64_encode(hmac.new(secret, _canonical(payload), hashlib.sha256).digest())


def issue_signed_token(secret: bytes, claims: dict[str, Any], ttl_seconds: int) -> str:
    """Create a stateless, expiration-bound HMAC capability or identity token."""

    payload = {**claims, "exp": int(time.time()) + ttl_seconds, "v": 1}
    body = _b64_encode(_canonical(payload))
    return f"{body}.{_sign(secret, payload)}"


def verify_signed_token(secret: bytes, token: str, required_kind: str | None = None) -> dict[str, Any]:
    """Verify signature, expiry, and optionally a purpose-bound token kind."""

    try:
        body, supplied_signature = token.split(".", 1)
        payload = json.loads(_b64_decode(body))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecurityError("malformed signed token") from exc
    expected_signature = _sign(secret, payload)
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise SecurityError("invalid signed token")
    if not isinstance(payload.get("exp"), int) or payload["exp"] < int(time.time()):
        raise SecurityError("expired signed token")
    if required_kind is not None and payload.get("kind") != required_kind:
        raise SecurityError("signed token scope mismatch")
    return payload


def derive_watermark_id(secret: bytes, user_id: str, asset_id: str, session_id: str) -> int:
    """Derive the opaque 32-bit attribution value; mapping remains server-side."""

    message = "\x1f".join(("wm-id-v1", user_id, asset_id, session_id)).encode("utf-8")
    return int.from_bytes(hmac.new(secret, message, hashlib.sha256).digest()[:4], "big")


def derive_key(secret: bytes, purpose: str, *parts: str, length: int = 32) -> bytes:
    """Domain-separated HMAC key derivation for carriers, segment keys, and IVs."""

    message = "\x1f".join((purpose, *parts)).encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).digest()[:length]


def stable_hash(value: str) -> str:
    """Use a correlation-safe short audit identifier instead of a raw account value."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str


def issue_identity(secret: bytes, subject: str, role: str = "listener", ttl_seconds: int = 3600) -> str:
    """Test/development identity issuer; production should delegate to an identity provider."""

    return issue_signed_token(secret, {"kind": "identity", "sub": subject, "role": role}, ttl_seconds)


def verify_identity(secret: bytes, token: str) -> Principal:
    claims = verify_signed_token(secret, token, required_kind="identity")
    subject, role = claims.get("sub"), claims.get("role")
    if not isinstance(subject, str) or not subject or not isinstance(role, str):
        raise SecurityError("invalid identity claims")
    return Principal(subject=subject, role=role)

