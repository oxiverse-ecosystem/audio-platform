"""End-to-end and component tests for the secure personalized streaming MVP."""

from __future__ import annotations

import base64
import io
import re
from dataclasses import replace

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from audio_streaming.app import create_app
from audio_streaming.config import Settings
from audio_streaming.hls import decrypt_segment
from audio_streaming.security import derive_watermark_id, issue_identity
from audio_streaming.watermark import SegmentSafeWatermarker


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
        session_cache_max_bytes=8 * 1024 * 1024,
    )


def audio_b64(sample_rate: int = 16_000, duration_seconds: float = 6.3) -> str:
    """Build a small legal controlled fixture with varied content for endpoint processing."""

    count = int(sample_rate * duration_seconds)
    rng = np.random.default_rng(7)
    axis = np.arange(count, dtype=np.float32) / sample_rate
    waveform = (0.14 * np.sin(2 * np.pi * 440 * axis) + 0.03 * np.sin(2 * np.pi * 1270 * axis) + 0.005 * rng.standard_normal(count)).astype(np.float32)
    output = io.BytesIO()
    sf.write(output, waveform, sample_rate, format="WAV", subtype="PCM_16")
    return base64.b64encode(output.getvalue()).decode("ascii")


def bearer(settings: Settings, subject: str, role: str = "listener") -> dict[str, str]:
    token = issue_identity(settings.auth_secret, subject, role=role, ttl_seconds=3600)
    return {"Authorization": f"Bearer {token}"}


def register_fixture(client: TestClient, settings: Settings) -> None:
    response = client.post(
        "/v1/assets",
        headers=bearer(settings, "operator", "admin"),
        json={"asset_id": "fixture-audio", "title": "Controlled fixture", "audio_b64": audio_b64(), "entitled_user_ids": ["listener-a"]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["segment_count"] >= 3


def create_listener_session(client: TestClient, settings: Settings) -> dict[str, object]:
    response = client.post("/v1/stream-sessions", headers=bearer(settings, "listener-a"), json={"asset_id": "fixture-audio"})
    assert response.status_code == 201, response.text
    return response.json()


def relative_uri(manifest: str, match: str) -> str:
    line = next(value for value in manifest.splitlines() if match in value)
    quoted = re.search(r'URI="([^"]+)"', line)
    return quoted.group(1) if quoted else line


def test_authorization_isolation_encrypted_delivery_and_attribution(tmp_path) -> None:
    """A second identity cannot reuse a session capability, while the owner can decrypt its HLS segment."""

    settings = settings_for(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        register_fixture(client, settings)
        session_payload = create_listener_session(client, settings)
        session_id = session_payload["session_id"]
        owner_headers = bearer(settings, "listener-a")
        intruder_headers = bearer(settings, "listener-b")

        denied = client.get(session_payload["playlist_url"], headers=intruder_headers)
        assert denied.status_code == 403

        playlist_response = client.get(session_payload["playlist_url"], headers=owner_headers)
        assert playlist_response.status_code == 200, playlist_response.text
        assert "#EXT-X-KEY:METHOD=AES-128" in playlist_response.text
        segment_uri = relative_uri(playlist_response.text, "/segments/")
        key_uri = relative_uri(playlist_response.text, "/keys/main")

        capability_only_playlist = client.get(session_payload["playlist_url"])
        assert capability_only_playlist.status_code == 200

        key_response = client.get(key_uri)
        segment_response = client.get(segment_uri)
        assert key_response.status_code == 200
        assert len(key_response.content) == 16
        assert segment_response.status_code == 200
        assert segment_response.headers["content-type"].startswith("video/MP2T")
        assert not segment_response.content.startswith(b"G")

        server_session = __import__("asyncio").run(app.state.repository.get_session(session_id))
        assert server_session is not None
        key_metadata = __import__("asyncio").run(app.state.repository.encryption_key_metadata(session_id))
        assert key_metadata is not None
        assert key_metadata["key_purpose"] == "hls-segment-aes128"
        assert key_metadata["derivation_version"] == "hls-aes128-v1"
        assert key_metadata["key_reference"] not in key_response.content.hex()
        assert key_metadata["rotation_status"] == "active"
        first_iv = bytes.fromhex(re.search(r"IV=0x([0-9a-f]+)", playlist_response.text).group(1))
        plaintext = decrypt_segment(segment_response.content, key_response.content, first_iv)
        assert plaintext.startswith(b"G")

        verified = client.post(
            "/v1/attribution/verify",
            headers=bearer(settings, "operator", "admin"),
            json={"asset_id": "fixture-audio", "watermark_id": server_session.watermark_id},
        )
        assert verified.status_code == 200
        assert verified.json()["matched"] is True
        assert verified.json()["session_id"] == session_id
        assert verified.json()["user_audit_hash"] != "listener-a"


def test_token_mapping_determinism_and_exact_controlled_recovery(tmp_path) -> None:
    """The identifier derivation is deterministic and a 32-bit ID recovers exactly on a controlled fixture."""

    settings = settings_for(tmp_path)
    same = derive_watermark_id(settings.watermark_secret, "user", "asset", "session")
    assert same == derive_watermark_id(settings.watermark_secret, "user", "asset", "session")
    assert same != derive_watermark_id(settings.watermark_secret, "other-user", "asset", "session")

    watermarker = SegmentSafeWatermarker(settings, settings.watermark_secret, "asset")
    expected_id = 0x2A7F00C1
    samples = np.zeros(settings.frame_samples // 2 + settings.frame_samples * 160, dtype=np.float32)
    marked = watermarker.embed(samples, expected_id, absolute_start=0)
    recovered = watermarker.recover(marked)
    assert recovered.crc_valid is True
    assert recovered.watermark_id == expected_id


def test_segment_boundary_continuity_and_concurrent_single_flight(tmp_path) -> None:
    """Segment rendering follows the same carrier timeline as a single stream and shares duplicate work."""

    settings = settings_for(tmp_path)
    watermarker = SegmentSafeWatermarker(settings, settings.watermark_secret, "asset")
    expected_id = 0x11223344
    source = np.zeros(settings.segment_samples * 2, dtype=np.float32)
    whole = watermarker.embed(source, expected_id, 0)
    first = watermarker.embed(source[: settings.segment_samples], expected_id, 0)
    second = watermarker.embed(source[settings.segment_samples :], expected_id, settings.segment_samples)
    assert np.allclose(whole, np.concatenate((first, second)), atol=1e-7)

    app = create_app(settings)
    with TestClient(app) as client:
        register_fixture(client, settings)
        session_payload = create_listener_session(client, settings)
        owner_headers = bearer(settings, "listener-a")
        playlist_response = client.get(session_payload["playlist_url"], headers=owner_headers)
        segment_uri = relative_uri(playlist_response.text, "/segments/")

        import concurrent.futures

        def request_same_segment() -> bytes:
            response = client.get(segment_uri, headers=owner_headers)
            assert response.status_code == 200, response.text
            return response.content

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(lambda _: request_same_segment(), range(6)))
        assert len({result for result in results}) == 1
        metrics = client.get("/v1/operations/metrics", headers=bearer(settings, "operator", "admin"))
        assert metrics.status_code == 200
        assert metrics.json()["segment_builds"] == 1


def test_concurrent_cold_personalization_applies_backpressure(tmp_path) -> None:
    """A burst above the bounded worker admission limit produces controlled 503 responses, not unbounded work."""

    settings = settings_for(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        register_fixture(client, settings)
        admin_headers = bearer(settings, "operator", "admin")
        users = [f"listener-{index}" for index in range(6)]
        for user_id in users:
            response = client.put(
                "/v1/assets/fixture-audio/entitlements", headers=admin_headers, json={"user_id": user_id, "allowed": True}
            )
            assert response.status_code == 200

        requests: list[tuple[str, dict[str, str]]] = []
        for user_id in users:
            created = client.post("/v1/stream-sessions", headers=bearer(settings, user_id), json={"asset_id": "fixture-audio"})
            assert created.status_code == 201
            headers = bearer(settings, user_id)
            manifest = client.get(created.json()["playlist_url"], headers=headers)
            assert manifest.status_code == 200
            requests.append((relative_uri(manifest.text, "/segments/"), headers))

        import concurrent.futures

        def request_cold_segment(item: tuple[str, dict[str, str]]) -> int:
            uri, headers = item
            return client.get(uri, headers=headers).status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(requests)) as executor:
            statuses = list(executor.map(request_cold_segment, requests))

        assert statuses.count(200) == settings.worker_concurrency * 2
        assert statuses.count(503) == len(requests) - (settings.worker_concurrency * 2)
