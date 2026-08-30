"""Swappable media storage backend.

Phase 1 uses a local filesystem store (no cloud credits yet). When Cloudflare R2
credits arrive, we swap this for an ``R2Store`` with the SAME object-key scheme, so
migration is a config flip -- no change to ingest, manifest, or serving logic.

Object keys are identical across backends so cached/CDN URLs and the A/B variant
scheme (``assets/<id>/v0/<seq>.ts``) survive the migration untouched.

Signed-URL generation is separated into a ``URLSigner`` so local dev (Python HMAC)
and Cloudflare (Worker WebCrypto) are both supported without touching callers.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from abc import ABC, abstractmethod
from pathlib import Path

from .config import Settings


# ---------------------------------------------------------------------------
# Storage backend
# ---------------------------------------------------------------------------
class MediaStore(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    def asset_dir(self, asset_id: str) -> str:
        return f"assets/{asset_id}"


class LocalFSStore(MediaStore):
    """Filesystem-backed store under <data_dir>/objects. Identical keys to R2."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Keys are already slash-separated; keep them as-is under root.
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def put(self, key: str, data: bytes) -> None:
        self._path(key).write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# URL signer (capability) -- local HMAC now, Worker WebCrypto later
# ---------------------------------------------------------------------------
class URLSigner(ABC):
    @abstractmethod
    def sign(self, object_key: str, expires_in_s: int) -> str:
        """Return a signed token string for the given object key."""

    @abstractmethod
    def verify(self, object_key: str, token: str, now: int | None = None) -> bool: ...


class LocalURLSigner(URLSigner):
    """HMAC-SHA256(<object_key>\\n<expires_at>), base64url, padding stripped.

    MUST be byte-identical to the Cloudflare Worker's WebCrypto implementation before
    any production use (cross-language HMAC is where silent mismatches hide).
    """

    def __init__(self, secret: bytes):
        self.secret = secret

    def sign(self, object_key: str, expires_in_s: int) -> str:
        expires_at = int(time.time()) + int(expires_in_s)
        msg = f"{object_key}\n{expires_at}".encode("utf-8")
        sig = hmac.new(self.secret, msg, hashlib.sha256).digest()
        token = f"{expires_at}." + _b64url(sig)
        return token

    def verify(self, object_key: str, token: str, now: int | None = None) -> bool:
        try:
            expires_at_s, sig_b64 = token.split(".", 1)
            expires_at = int(expires_at_s)
        except Exception:
            return False
        if now is None:
            now = int(time.time())
        if expires_at < now:
            return False
        msg = f"{object_key}\n{expires_at}".encode("utf-8")
        expected = hmac.new(self.secret, msg, hashlib.sha256).digest()
        try:
            provided = _unb64url(sig_b64)
        except Exception:
            return False
        return hmac.compare_digest(expected, provided)


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64url(s: str) -> bytes:
    import base64

    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def build_store(settings: Settings) -> MediaStore:
    """Factory: LocalFSStore now; R2Store later (same keys, config flip)."""
    return LocalFSStore(settings.data_dir / "objects")


def build_signer(settings: Settings) -> URLSigner:
    return LocalURLSigner(settings.capability_secret)
