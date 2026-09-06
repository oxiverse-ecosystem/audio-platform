"""Test suite for the new audio platform features:
1. True Audio Waveform Peaks Generation
2. Synchronized A/B Audio Comparison (raw.mp3 retention and CDN delivery)
3. Async / Draft & Publish-Ahead processing
4. Time-Series Creator Analytics & Listener Retention
5. Transactional Email Service
"""

import asyncio
import io
import pathlib
import shutil
import time

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from audio_streaming.app import create_app
from audio_streaming.config import Settings
from audio_streaming.email import send_password_reset_email, send_verification_email
from audio_streaming.security import issue_identity


def _create_sine_wav(duration: float = 3.0, sr: int = 48000) -> bytes:
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    # create signal with varying amplitude to test dynamic peaks
    sig = 0.5 * np.sin(2 * np.pi * 440 * t) * np.linspace(0.2, 1.0, len(t))
    buf = io.BytesIO()
    sf.write(buf, sig.astype(np.float32), sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def test_waveform_peaks_and_ab_raw_audio():
    data_dir = pathlib.Path("runtime-data/test-peaks-ab")
    if data_dir.exists():
        shutil.rmtree(data_dir)
    db_path = data_dir / "streaming.db"

    settings = Settings(
        environment="test",
        data_dir=data_dir,
        database_path=db_path,
        auth_secret=b"a" * 40, capability_secret=b"c" * 40,
        watermark_secret=b"w" * 40, segment_key_secret=b"s" * 40,
    )

    app = create_app(settings)
    app.state.loop = asyncio.new_event_loop()

    with TestClient(app) as client:
        # Sign up creator
        r = client.post("/v1/auth/signup", json={
            "email": "creator_ab@example.com",
            "display_name": "Studio Creator",
            "password": "strongpassword123",
            "is_creator": True,
        })
        assert r.status_code == 200, r.text
        token = r.json()["verify_token"]
        client.get("/v1/auth/verify-email", params={"token": token})

        # Login
        r = client.post("/v1/auth/login", json={
            "email": "creator_ab@example.com",
            "password": "strongpassword123",
        })
        assert r.status_code == 200
        access_token = r.json()["access_token"]
        creator_id = r.json()["user_id"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Upload audio with draft creation
        raw_wav = _create_sine_wav(2.5)
        r = client.post(
            "/v1/uploads",
            headers=headers,
            files={"file": ("test_voice.wav", raw_wav, "audio/wav")},
            data={"title": "Dynamic Speech Drop", "output_format": "mp3"},
        )
        assert r.status_code == 202, r.text
        upload_data = r.json()
        job_id = upload_data["job_id"]
        asset_id = upload_data["asset_id"]
        assert upload_data["status"] == "queued"
        assert upload_data["episode_id"] is not None
        draft_episode_id = upload_data["episode_id"]

        # Poll status until ready
        for _ in range(60):
            sr = client.get(f"/v1/uploads/{job_id}", headers=headers)
            assert sr.status_code == 200
            if sr.json()["status"] == "ready":
                break
            time.sleep(0.5)

        status_resp = client.get(f"/v1/uploads/{job_id}", headers=headers).json()
        assert status_resp["status"] == "ready"

        # Feature 1 verification: True waveform peaks
        assert "waveform_peaks" in status_resp["report"]
        peaks = status_resp["report"]["waveform_peaks"]
        assert isinstance(peaks, list)
        assert len(peaks) == 128
        assert all(isinstance(p, (float, int)) for p in peaks)
        assert all(0.05 <= p <= 1.0 for p in peaks)

        # Feature 2 verification: A/B raw audio download and CDN delivery
        assert "download" in status_resp and status_resp["download"] is not None
        assert "mp3" in status_resp["download"]
        assert "wav" in status_resp["download"]
        assert "raw" in status_resp["download"]

        raw_cdn_url = status_resp["download"]["raw"]
        assert f"/v1/cdn/{asset_id}/raw.mp3" in raw_cdn_url
        # Fetch raw audio from CDN
        cdn_resp = client.get(raw_cdn_url)
        assert cdn_resp.status_code == 200
        assert cdn_resp.headers["content-type"] == "audio/mpeg"
        assert len(cdn_resp.content) > 0

        # Feature 6 verification: Draft state & Publish
        # Check drafts list
        r_drafts = client.get("/v1/episodes/drafts", headers=headers)
        assert r_drafts.status_code == 200
        draft_list = r_drafts.json()["drafts"]
        assert any(d["episode_id"] == draft_episode_id for d in draft_list)
        draft = next(d for d in draft_list if d["episode_id"] == draft_episode_id)
        assert draft["status"] == "ready"
        assert draft["waveform_peaks"] is not None
        assert len(draft["waveform_peaks"]) == 128

        # Draft shouldn't appear in public discovery yet
        r_pub = client.get("/v1/episodes")
        assert not any(ep["episode_id"] == draft_episode_id for ep in r_pub.json()["episodes"])

        # Publish the draft
        r_publish = client.post(f"/v1/episodes/{draft_episode_id}/publish", headers=headers)
        assert r_publish.status_code == 200
        published_ep = r_publish.json()
        assert published_ep["status"] == "published"
        assert published_ep["duration_seconds"] > 0
        assert published_ep["waveform_peaks"] is not None

        # Now it appears in public discovery
        r_pub2 = client.get("/v1/episodes")
        assert any(ep["episode_id"] == draft_episode_id for ep in r_pub2.json()["episodes"])

        # Feature 4 verification: Time-series analytics
        # Record play beacons (1 completed, 1 partial)
        r_play1 = client.post(
            f"/v1/episodes/{draft_episode_id}/play",
            json={"duration_listened_seconds": 120.0, "completed": True},
        )
        assert r_play1.status_code == 200

        r_play2 = client.post(
            f"/v1/episodes/{draft_episode_id}/play",
            json={"duration_listened_seconds": 45.0, "completed": False},
        )
        assert r_play2.status_code == 200

        # Query creator time-series
        r_ts = client.get("/v1/analytics/creator/timeseries?days=7", headers=headers)
        assert r_ts.status_code == 200
        ts_data = r_ts.json()
        assert ts_data["total_plays"] >= 2
        assert ts_data["days"] == 7
        assert len(ts_data["points"]) == 7
        assert ts_data["overall_retention_rate"] > 0
        assert ts_data["avg_listen_seconds"] > 0


def test_transactional_email_fallback():
    # Test that transactional email gracefully falls back to dev logging when no API key is provided
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        # verify email
        sent_v = send_verification_email("newcreator@example.com", "Alex", "http://localhost:3000/verify-email?token=abc")
        # In test environment without Resend/Sendgrid keys, returns False and logs
        assert sent_v is False

        # password reset
        sent_p = send_password_reset_email("recovery@example.com", "http://localhost:3000/reset-password?token=xyz")
        assert sent_p is False
