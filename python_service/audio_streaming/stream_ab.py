"""Phase 1b ingest + delivery: A/B variant watermark + AES-128 + signed HLS.

INGEST (extends the P1a job)
  mastered PCM -> split into HLS segments -> embed A/B carrier (v0=+sign, v1=-sign)
  -> AES-128 encrypt each variant with a PER-ASSET key -> store v0/ v1/ in MediaStore.
  Personalization (which variant per segment) happens at DELIVERY, not here, so the two
  variant files are shared across all listeners and CDN-cacheable.

DELIVERY (per listener, cacheable)
  POST /v1/stream-sessions  -> auth + entitlement (track-only) -> returns a session id.
  GET  /v1/streams/{sid}/playlist.m3u8 -> derive listener id -> build A/B manifest ->
       signed segment URLs + signed AES key URL.
  GET  /v1/streams/{sid}/segments/{seq}.ts -> signed serve (LocalFSStore /cdn route).
  GET  /v1/streams/{sid}/keys/main -> signed serve of the per-asset AES key (short TTL).

This is access control + traceability, NOT DRM. State plainly.
"""

from __future__ import annotations

import asyncio
import math
import os
import secrets
import struct
import time
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from . import store
from .media import encode_aac_transport_stream
from .security import Principal
from .store import MediaStore, URLSigner
from .watermark_ab import WatermarkEngineSettings, build_manifest


SEGMENT_SECONDS = 2.0
TARGET_LUFS = -16.0
# RS-encoded codeword is 80 bits; clips shorter than this many segments lose full
# leak attribution (the asset is no longer padded to the codeword length at ingest).
MIN_SEGMENTS_FOR_FULL_ID = 80


@dataclass
class StreamAssetRecord:
    asset_id: str
    creator_id: str | None
    n_segments: int
    # one EXTINF length per segment (last may be trimmed to the true content length)
    segment_durations: list[float]
    # per-asset AES-128 key (server-only, never in playlist)
    aes_key: bytes
    aes_iv: bytes
    created_at: int


@dataclass
class StreamSession:
    session_id: str
    asset_id: str
    listener_id: int
    principal_subject: str
    created_at: int
    expires_at: int


@dataclass
class ABStreamService:
    """Owns asset + session state and the MediaStore/URLSigner backends."""

    store: MediaStore
    signer: URLSigner
    wm_settings: WatermarkEngineSettings = field(default_factory=WatermarkEngineSettings)
    _assets: dict[str, StreamAssetRecord] = field(default_factory=dict)
    _sessions: dict[str, StreamSession] = field(default_factory=dict)
    _listener_by_subject: dict[str, int] = field(default_factory=dict)

    # ---- ingest ----
    async def ingest_asset(self, asset_id: str, creator_id: str | None,
                           mastered_pcm: bytes, sample_rate: int) -> StreamAssetRecord:
        """Split + embed A/B variants + AES-encrypt + store. Runs off the event loop."""
        import numpy as np
        import soundfile as sf

        def _work() -> StreamAssetRecord:
            audio, _ = sf.read(_buf(mastered_pcm), dtype="float32", always_2d=False)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            sr = sample_rate
            seg_len = int(SEGMENT_SECONDS * sr)
            n_seg = max(1, int(np.ceil(len(audio) / seg_len)))
            key = os.urandom(16)
            iv = os.urandom(16)
            durations: list[float] = []
            for variant in (0, 1):
                durations = []
                for s in range(n_seg):
                    start = s * seg_len
                    chunk = audio[start:start + seg_len]
                    if s == n_seg - 1 and len(chunk) < seg_len:
                        # Trim the tail: pad only to whole AAC frames (1024 samples),
                        # not a full segment, so playback ends at the real content length.
                        padded = int(np.ceil(len(chunk) / 1024.0)) * 1024
                        chunk = np.pad(chunk, (0, padded - len(chunk)))
                    elif len(chunk) < seg_len:
                        chunk = np.pad(chunk, (0, seg_len - len(chunk)))
                    durations.append(len(chunk) / sr)
                    watermarked = _embed_variant(chunk, sr, variant, self.wm_settings)
                    ts = encode_aac_transport_stream(watermarked, None, sr)
                    enc = _aes_encrypt(ts, key, iv)
                    self.store.put(f"assets/{asset_id}/v{variant}/{s:04d}.ts", enc)
            rec = StreamAssetRecord(
                asset_id=asset_id, creator_id=creator_id, n_segments=n_seg,
                segment_durations=durations, aes_key=key, aes_iv=iv,
                created_at=int(time.time()),
            )
            self._assets[asset_id] = rec
            return rec

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _work)

    # ---- delivery ----
    def _listener_id_for(self, subject: str) -> int:
        # Stable 32-bit listener id derived from the account subject (deterministic).
        if subject not in self._listener_by_subject:
            digest = __import__("hashlib").sha256(subject.encode()).digest()
            self._listener_by_subject[subject] = int.from_bytes(digest[:4], "big")
        return self._listener_by_subject[subject]

    async def create_session(self, asset_id: str, principal: Principal,
                             entitlement_ok: bool = True, ttl_s: int = 3600) -> StreamSession:
        if asset_id not in self._assets:
            raise KeyError("unknown asset")
        # Entitlement is track-only during the trial (D1): we check but do not enforce 402.
        if not entitlement_ok:
            # In production this would raise 402; trial records-only.
            pass
        listener_id = self._listener_id_for(principal.subject)
        sid = secrets.token_hex(16)
        now = int(time.time())
        sess = StreamSession(
            session_id=sid, asset_id=asset_id, listener_id=listener_id,
            principal_subject=principal.subject, created_at=now, expires_at=now + ttl_s,
        )
        self._sessions[sid] = sess
        return sess

    def playlist(self, session_id: str, base_url: str = "") -> str:
        """Return an HLS m3u8 with per-listener A/B variant choices + signed URLs."""
        sess = self._sessions.get(session_id)
        if sess is None:
            raise KeyError("unknown session")
        if int(time.time()) > sess.expires_at:
            raise KeyError("session expired")
        rec = self._assets[sess.asset_id]
        manifest = build_manifest(rec.asset_id, sess.listener_id, rec.n_segments, self.wm_settings)
        base = base_url.rstrip("/")
        target = max(2, int(math.ceil(max(rec.segment_durations))))
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{target}",
                 f"#EXT-X-MEDIA-SEQUENCE:0"]
        for s, variant in enumerate(manifest.choices):
            key_url = self.signer.sign(f"streams/{sess.session_id}/keys/main", 60)
            seg_url = self.signer.sign(f"assets/{rec.asset_id}/v{variant}/{s:04d}.ts", 3600)
            lines.append(
                f'#EXT-X-KEY:METHOD=AES-128,URI="{base}/v1/ab/cdn/streams/{sess.session_id}/keys/main?tok={key_url}",'
                f'IV=0x{rec.aes_iv.hex()}'
            )
            lines.append(f"#EXTINF:{rec.segment_durations[s]:.3f},")
            lines.append(f"{base}/v1/ab/cdn/streams/{sess.session_id}/segments/{s:04d}.ts?tok={seg_url}")
        lines.append("#EXT-X-ENDLIST")
        return "\n".join(lines) + "\n"

    async def get_segment(self, asset_id: str, variant: int, seq: int) -> bytes:
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.store.get(f"assets/{asset_id}/v{variant}/{seq:04d}.ts")
        )

    async def get_key(self, session_id: str) -> bytes:
        sess = self._sessions.get(session_id)
        if sess is None:
            raise KeyError("unknown session")
        rec = self._assets[sess.asset_id]
        return rec.aes_key  # served over a signed, short-TTL URL


def _buf(data: bytes):
    import io
    return io.BytesIO(data)


def _embed_variant(chunk: np.ndarray, sr: int, variant: int, settings) -> np.ndarray:
    from .watermark_ab import embed_variant
    return embed_variant(chunk, sr, variant, settings)


def _aes_encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    enc = cipher.encryptor()
    pad = (16 - (len(data) % 16)) % 16
    return enc.update(data + bytes([pad]) * pad) + enc.finalize()
