"""End-to-end verification of the CDN-cacheable A/B variant streaming path.

These tests exercise the real production flow: multipart ingest through ffmpeg at 48 kHz
stereo, publication of two encrypted variants per segment, a personalized manifest, signed
CDN retrieval, AES-128 decryption, AAC decode, and forensic recovery of the listener's
32-bit attribution id from the decoded audio.
"""

from __future__ import annotations

import base64
import io
import re
import subprocess
import wave

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from audio_streaming.app import create_app
from audio_streaming.config import Settings
from audio_streaming.hls import decrypt_segment
from audio_streaming.ingest import asset_content_key
from audio_streaming.security import issue_identity
from audio_streaming.storage import sign_object_url, verify_object_url
from audio_streaming.variant_watermark import CODEWORD_BITS, VariantWatermarker, bit_slot_permutation


SAMPLE_RATE = 48_000
CHANNELS = 2
SEGMENT_SECONDS = 1.0
FRAME_SAMPLES = 4_096


def settings_for(tmp_path) -> Settings:
    return Settings(
        environment="test",
        data_dir=tmp_path / "runtime",
        database_path=tmp_path / "runtime" / "streaming.db",
        auth_secret=b"test-auth-secret-which-is-longer-than-thirty-two-bytes",
        capability_secret=b"test-capability-secret-which-is-longer-than-32-bytes",
        watermark_secret=b"test-watermark-secret-which-is-longer-than-32-bytes",
        segment_key_secret=b"test-segment-key-secret-which-is-longer-than-32-bytes",
        worker_concurrency=2,
        variant_sample_rate=SAMPLE_RATE,
        variant_channels=CHANNELS,
        variant_frame_samples=FRAME_SAMPLES,
        variant_segment_seconds=SEGMENT_SECONDS,
        variant_watermark_strength=0.02,
    )


def bearer(settings: Settings, subject: str, role: str = "listener") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_identity(settings.auth_secret, subject, role=role, ttl_seconds=3600)}"}


def source_wav(duration_seconds: float = 70.0) -> bytes:
    """A tonal stereo fixture: real spectral content so the AAC codec behaves realistically."""

    count = int(SAMPLE_RATE * duration_seconds)
    axis = np.arange(count, dtype=np.float32) / SAMPLE_RATE
    rng = np.random.default_rng(11)
    left = 0.30 * np.sin(2 * np.pi * 220 * axis) + 0.10 * np.sin(2 * np.pi * 1_480 * axis)
    right = 0.28 * np.sin(2 * np.pi * 233 * axis) + 0.09 * np.sin(2 * np.pi * 990 * axis)
    noise = 0.01 * rng.standard_normal((count, 2)).astype(np.float32)
    stereo = np.stack([left, right], axis=1).astype(np.float32) + noise
    buffer = io.BytesIO()
    sf.write(buffer, stereo, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def watermarker_for(settings: Settings, asset_id: str = "founder-ep-01") -> VariantWatermarker:
    return VariantWatermarker(
        settings.watermark_secret, asset_id, settings.variant_frame_samples, settings.variant_watermark_strength
    )


def ingest(client: TestClient, settings: Settings, asset_id: str = "founder-ep-01", listeners=("listener-a",)) -> dict:
    response = client.post(
        "/v1/variant-assets",
        headers=bearer(settings, "operator", "admin"),
        data={"asset_id": asset_id, "title": "Founder Story 01"},
        files={"upload": ("source.wav", source_wav(), "audio/wav")},
    )
    assert response.status_code == 201, response.text
    for user_id in listeners:
        granted = client.put(
            f"/v1/variant-assets/{asset_id}/entitlements",
            headers=bearer(settings, "operator", "admin"),
            json={"user_id": user_id, "allowed": True},
        )
        assert granted.status_code == 200, granted.text
    return response.json()


def decode_ts_to_pcm(payload: bytes) -> np.ndarray:
    """Decode an AAC/MPEG-TS segment back to float32 PCM, exactly as forensic analysis would."""

    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "mpegts", "-i", "pipe:0",
         "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "-c:a", "pcm_f32le", "-f", "wav", "pipe:1"],
        input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=120,
    )
    samples, rate = sf.read(io.BytesIO(result.stdout), dtype="float32", always_2d=True)
    assert rate == SAMPLE_RATE
    return samples


def test_ingest_publishes_two_variants_per_segment(tmp_path) -> None:
    """Ingest is the only codec pass: it must emit exactly 2 immutable objects per segment."""

    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        payload = ingest(client, settings)
    assert payload["sample_rate"] == SAMPLE_RATE
    assert payload["channels"] == CHANNELS
    assert payload["segment_count"] >= CODEWORD_BITS // 8
    assert payload["published_objects"] == payload["segment_count"] * 2
    root = settings.data_dir / "object-store" / "assets" / "founder-ep-01"
    assert len(list((root / "v0").glob("*.ts"))) == payload["segment_count"]
    assert len(list((root / "v1").glob("*.ts"))) == payload["segment_count"]


def test_manifest_selects_the_codeword_variant_sequence(tmp_path) -> None:
    """The listener's manifest must spell out their own codeword, and differ between listeners."""

    settings = settings_for(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        ingest(client, settings, listeners=("listener-a", "listener-b"))
        manifests = {}
        for user in ("listener-a", "listener-b"):
            created = client.post("/v1/variant-streams", headers=bearer(settings, user), json={"asset_id": "founder-ep-01"})
            assert created.status_code == 201, created.text
            session_id = created.json()["session_id"]
            manifest = client.get(created.json()["manifest_url"], headers=bearer(settings, user))
            assert manifest.status_code == 200, manifest.text
            record = __import__("asyncio").run(app.state.repository.get_variant_session(session_id))
            variants = [int(match) for match in re.findall(r"/v(\d)/\d{6}\.ts", manifest.text)]
            marker = watermarker_for(settings)
            expected = [marker.variant_for(record.watermark_id, index) for index in range(len(variants))]
            assert variants == expected
            manifests[user] = variants
        assert manifests["listener-a"] != manifests["listener-b"]


def test_cdn_urls_are_signed_cacheable_and_expire(tmp_path) -> None:
    """Segment bytes come from signed immutable CDN objects; a tampered or expired signature is refused."""

    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        ingest(client, settings)
        created = client.post("/v1/variant-streams", headers=bearer(settings, "listener-a"), json={"asset_id": "founder-ep-01"})
        manifest = client.get(created.json()["manifest_url"], headers=bearer(settings, "listener-a")).text
        segment_url = next(line for line in manifest.splitlines() if "/v1/cdn/" in line)

        served = client.get(segment_url)
        assert served.status_code == 200
        assert served.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert len(served.content) > 0

        tampered = re.sub(r"sig=[^&]+", "sig=aaaabbbbccccdddd", segment_url)
        assert client.get(tampered).status_code == 403
        stale = re.sub(r"exp=\d+", "exp=1", segment_url)
        assert client.get(stale).status_code == 403

    key = b"k" * 32
    expires = 2_000_000_000
    query = sign_object_url(key, "assets/a/v0/000000.ts", expires)
    signature = dict(part.split("=", 1) for part in query.split("&"))["sig"]
    assert verify_object_url(key, "assets/a/v0/000000.ts", expires, signature) is True
    assert verify_object_url(key, "assets/a/v1/000000.ts", expires, signature) is False


def test_end_to_end_playback_decrypts_and_forensically_attributes_the_listener(tmp_path) -> None:
    """The full chain: manifest -> signed CDN bytes -> AES-128 -> AAC decode -> codeword -> user."""

    settings = settings_for(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        ingest(client, settings)
        created = client.post("/v1/variant-streams", headers=bearer(settings, "listener-a"), json={"asset_id": "founder-ep-01"})
        assert created.status_code == 201
        session_id = created.json()["session_id"]
        owner = bearer(settings, "listener-a")
        manifest_response = client.get(created.json()["manifest_url"], headers=owner)
        assert manifest_response.status_code == 200
        manifest = manifest_response.text

        key_uri = re.search(r'URI="([^"]+)"', manifest).group(1)
        key_response = client.get(key_uri, headers=owner)
        assert key_response.status_code == 200
        content_key = key_response.content
        assert content_key == asset_content_key(settings.segment_key_secret, "founder-ep-01")
        assert len(content_key) == 16

        ivs = [bytes.fromhex(value) for value in re.findall(r"IV=0x([0-9a-f]+)", manifest)]
        segment_urls = [line for line in manifest.splitlines() if "/v1/cdn/" in line]
        assert len(segment_urls) == len(ivs)

        recovered_segments: list[tuple[int, np.ndarray]] = []
        for sequence, (url, iv) in enumerate(zip(segment_urls, ivs)):
            response = client.get(url)
            assert response.status_code == 200
            transport_stream = decrypt_segment(response.content, content_key, iv)
            assert transport_stream.startswith(b"G"), "decrypted payload must be a valid MPEG-TS"
            recovered_segments.append((sequence, decode_ts_to_pcm(transport_stream)))

        session = __import__("asyncio").run(app.state.repository.get_variant_session(session_id))
        watermarker = VariantWatermarker(
            settings.watermark_secret, "founder-ep-01", settings.variant_frame_samples, settings.variant_watermark_strength
        )
        mismatches = []
        for sequence, samples in recovered_segments:
            detected, confidence = watermarker.detect_bit(samples, sequence * settings.variant_segment_samples)
            if detected != watermarker.variant_for(session.watermark_id, sequence):
                mismatches.append((sequence, confidence))
        # Per-segment detection after a lossy AAC round trip is allowed to be imperfect; the
        # codeword's redundancy and CRC are what must make the final attribution exact.
        assert len(mismatches) <= len(recovered_segments) // 10, f"too many bit errors: {mismatches}"

        payload = {
            "asset_id": "founder-ep-01",
            "segments": [
                {"sequence": sequence, "samples_b64": base64.b64encode(np.ascontiguousarray(samples, dtype="<f4").tobytes()).decode()}
                for sequence, samples in recovered_segments
            ],
        }
        verified = client.post("/v1/variant-attribution/verify", headers=bearer(settings, "operator", "admin"), json=payload)
        assert verified.status_code == 200, verified.text
        body = verified.json()
        assert body["crc_valid"] is True
        assert body["watermark_id"] == session.watermark_id
        assert body["matched"] is True
        assert body["session_id"] == session_id
        assert body["user_audit_hash"] != "listener-a"


def test_authorization_isolation_and_revocation(tmp_path) -> None:
    """Sessions are owner-bound, unentitled users are refused, and revocation stops manifest issuance."""

    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        ingest(client, settings)
        refused = client.post("/v1/variant-streams", headers=bearer(settings, "stranger"), json={"asset_id": "founder-ep-01"})
        assert refused.status_code == 403

        created = client.post("/v1/variant-streams", headers=bearer(settings, "listener-a"), json={"asset_id": "founder-ep-01"})
        manifest_url = created.json()["manifest_url"]
        assert client.get(manifest_url, headers=bearer(settings, "listener-b")).status_code == 403
        assert client.get(manifest_url, headers=bearer(settings, "listener-a")).status_code == 200
        assert client.get(f"/v1/variant-streams/{created.json()['session_id']}/playlist.m3u8?cap=short").status_code == 422

        revoked = client.delete(f"/v1/variant-streams/{created.json()['session_id']}", headers=bearer(settings, "listener-a"))
        assert revoked.status_code == 204
        assert client.get(manifest_url, headers=bearer(settings, "listener-a")).status_code == 404


def test_manifest_generation_does_no_media_work(tmp_path) -> None:
    """Scaling claim: many concurrent manifests must not invoke any codec or per-listener encode."""

    settings = settings_for(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        ingest(client, settings, listeners=tuple(f"listener-{index}" for index in range(8)))
        urls = []
        for index in range(8):
            user = f"listener-{index}"
            created = client.post("/v1/variant-streams", headers=bearer(settings, user), json={"asset_id": "founder-ep-01"})
            assert created.status_code == 201, created.text
            urls.append((created.json()["manifest_url"], bearer(settings, user)))

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            statuses = list(executor.map(lambda item: client.get(item[0], headers=item[1]).status_code, urls))
        assert statuses == [200] * 8, statuses

        legacy = client.get("/v1/operations/metrics", headers=bearer(settings, "operator", "admin")).json()
        assert legacy["segment_builds"] == 0, "no per-listener segment was built"
        variant_metrics = client.get("/v1/variant-operations/metrics", headers=bearer(settings, "operator", "admin")).json()
        assert variant_metrics["manifests_issued"] == 8
        assert variant_metrics["sessions_created"] == 8


def test_ingest_rejects_undecodable_and_duplicate_assets(tmp_path) -> None:
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        admin = bearer(settings, "operator", "admin")
        garbage = client.post(
            "/v1/variant-assets", headers=admin,
            data={"asset_id": "broken-asset", "title": "Broken"},
            files={"upload": ("source.wav", b"not audio at all", "audio/wav")},
        )
        assert garbage.status_code == 422, garbage.text

        ingest(client, settings)
        duplicate = client.post(
            "/v1/variant-assets", headers=admin,
            data={"asset_id": "founder-ep-01", "title": "Duplicate"},
            files={"upload": ("source.wav", source_wav(2.0), "audio/wav")},
        )
        assert duplicate.status_code == 409, duplicate.text
