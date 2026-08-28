"""End-to-end tests for the single /v1/enhance endpoint."""

from __future__ import annotations

import base64
import io

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from audio_streaming.app import create_app
from audio_streaming.config import Settings
from audio_streaming.security import issue_identity


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


def audio_b64(sample_rate: int = 48_000, duration_seconds: float = 3.0) -> str:
    """A clean-ish synthetic voice fixture (tones with silence gaps)."""
    count = int(sample_rate * duration_seconds)
    rng = np.random.default_rng(7)
    sig = np.zeros(count, dtype=np.float32)
    for start in range(0, count, int(0.8 * sample_rate)):
        t = np.arange(0, 0.5 * sample_rate, dtype=np.float32) / sample_rate
        sig[int(start):int(start) + len(t)] += (0.12 * np.sin(2 * np.pi * 800 * t)).astype(np.float32)
    sig = (sig + 0.01 * rng.standard_normal(count)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, sig, sample_rate, format="WAV", subtype="PCM_16")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def noisy_audio_b64(sample_rate: int = 48_000, duration_seconds: float = 3.0) -> str:
    """A noisy voice fixture (~+10 dB SNR, real silence gaps)."""
    count = int(sample_rate * duration_seconds)
    rng = np.random.default_rng(42)
    sig = np.zeros(count, dtype=np.float32)
    for start in range(0, count, int(0.8 * sample_rate)):
        t = np.arange(0, 0.5 * sample_rate, dtype=np.float32) / sample_rate
        sig[int(start):int(start) + len(t)] += (0.12 * np.sin(2 * np.pi * 800 * t)).astype(np.float32)
    sig = (sig + 0.03 * rng.standard_normal(count)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, sig, sample_rate, format="WAV", subtype="PCM_16")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def bearer(settings: Settings, subject: str, role: str = "listener") -> dict[str, str]:
    token = issue_identity(settings.auth_secret, subject, role=role, ttl_seconds=3600)
    return {"Authorization": f"Bearer {token}"}


def build_app(tmp_path):
    settings = settings_for(tmp_path)
    app = create_app(settings)
    return app, settings


def test_enhance_requires_auth(tmp_path):
    app, _ = build_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post("/v1/enhance", json={"audio_b64": audio_b64(), "output_format": "mp3"})
    assert resp.status_code == 401, resp.text


def test_enhance_clean_file_returns_processed_audio_and_report(tmp_path):
    app, settings = build_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/enhance",
            headers=bearer(settings, "listener-a"),
            json={"audio_b64": audio_b64(), "output_format": "mp3"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "enhanced.mp3"
    assert body["media_type"] == "audio/mpeg"
    assert body["report"]["mastering"]["clipped_after"] is False
    assert -30 < body["report"]["mastering"]["output_lufs"] < 0
    # Decode the returned audio and confirm it is valid, finite, right shape.
    raw = base64.b64decode(body["audio_b64"])
    data, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    assert np.isfinite(data).all()
    assert sr == 48000


def test_enhance_noisy_file_detects_noise_and_reports(tmp_path):
    app, settings = build_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/enhance",
            headers=bearer(settings, "listener-a"),
            json={"audio_b64": noisy_audio_b64(), "output_format": "wav"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "enhanced.wav"
    assert body["report"]["noise_detected"] is True
    assert body["report"]["enhancer_estimated_noise_floor_dbfs"] < -30


def test_enhance_accepts_mp3_upload_and_encodes_mp3(tmp_path):
    """Exercises the ffmpeg decode path (MP3 in) and the mp3 encode path."""
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")

    # Build a valid MP3 fixture via ffmpeg (mirrors real client uploads).
    wav_b64 = audio_b64()
    import io as _io

    wav_bytes = base64.b64decode(wav_b64)
    app, settings = build_app(tmp_path)
    with TestClient(app) as client:
        # Convert the WAV fixture to MP3 using ffmpeg so we upload a real MP3.
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", "-", "-c:a", "libmp3lame", "-b:a", "192k", "-f", "mp3", "-"],
            input=wav_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[:200]
        mp3_b64 = base64.b64encode(proc.stdout).decode("ascii")
        resp = client.post(
            "/v1/enhance",
            headers=bearer(settings, "listener-a"),
            json={"audio_b64": mp3_b64, "output_format": "mp3"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["media_type"] == "audio/mpeg"
    raw = base64.b64decode(body["audio_b64"])
    data, sr = sf.read(_io.BytesIO(raw), dtype="float32", always_2d=False)
    assert np.isfinite(data).all()


def test_enhance_rejects_undecodable_payload(tmp_path):
    app, settings = build_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/enhance",
            headers=bearer(settings, "listener-a"),
            json={"audio_b64": base64.b64encode(b"not audio at all").decode("ascii"), "output_format": "mp3"},
        )
    assert resp.status_code == 422, resp.text
