"""Object storage abstraction for CDN-backed variant segments.

Segments are immutable, shared by every listener, and therefore fully cacheable. The
origin never streams bytes on the hot path in production: it hands out signed URLs that
Cloudflare (or the local development endpoint) serves and caches.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import quote, urlencode


class StorageError(RuntimeError):
    """Raised when an object cannot be written to or read from the backing store."""


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def sign_object_url(secret: bytes, key: str, expires_at: int) -> str:
    """Cloudflare-compatible signed query string binding one object key to one deadline."""

    message = f"{key}\n{expires_at}".encode("utf-8")
    signature = _b64(hmac.new(secret, message, hashlib.sha256).digest())
    return urlencode({"exp": expires_at, "sig": signature})


def verify_object_url(secret: bytes, key: str, expires_at: int, signature: str) -> bool:
    """Constant-time verification used by the dev endpoint and mirrored by the Worker."""

    if expires_at < int(time.time()):
        return False
    message = f"{key}\n{expires_at}".encode("utf-8")
    expected = _b64(hmac.new(secret, message, hashlib.sha256).digest())
    return hmac.compare_digest(signature, expected)


class ObjectStore(ABC):
    """Minimal write-once/read-many contract satisfied by both local disk and R2."""

    @abstractmethod
    def put(self, key: str, payload: bytes, content_type: str) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    def public_url(self, base_url: str, key: str) -> str:
        return f"{base_url.rstrip('/')}/{quote(key)}"


class LocalObjectStore(ObjectStore):
    """Development/CI store; writes are atomic so a crashed ingest never publishes a partial segment."""

    def __init__(self, root: Path):
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if key.startswith("/") or ".." in key.split("/"):
            raise StorageError("unsafe object key")
        return self._root / key

    def put(self, key: str, payload: bytes, content_type: str) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, key: str) -> bytes:
        target = self._path(key)
        if not target.is_file():
            raise StorageError(f"object not found: {key}")
        return target.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


class S3ObjectStore(ObjectStore):
    """Cloudflare R2 (S3-compatible) store. boto3 is an optional deployment dependency."""

    def __init__(self, bucket: str, endpoint_url: str, access_key: str, secret_key: str, region: str = "auto"):
        try:
            import boto3  # noqa: PLC0415 - optional deployment dependency
        except ImportError as exc:  # pragma: no cover - exercised only in deployments
            raise StorageError("boto3 is required for R2/S3 object storage") from exc
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    def put(self, key: str, payload: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=payload,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )

    def get(self, key: str) -> bytes:
        try:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except Exception as exc:  # pragma: no cover - deployment path
            raise StorageError(f"object not found: {key}") from exc

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:  # pragma: no cover - deployment path
            return False


def build_object_store(settings) -> ObjectStore:
    """Select a store from configuration; local disk remains the default for dev and CI."""

    if settings.object_store_backend == "s3":
        return S3ObjectStore(
            bucket=settings.object_store_bucket,
            endpoint_url=settings.object_store_endpoint,
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
        )
    return LocalObjectStore(settings.data_dir / "object-store")
