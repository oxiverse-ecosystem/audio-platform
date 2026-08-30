"""End-to-end test of the Phase 1 upload -> queue -> repair -> studio -> store pipeline.

Synthesizes a "mobile-recorded" clip that exhibits the three capture artifacts we
must fix (clipping, dead-air lead, plosive pop), then drives it through the real
FastAPI app via TestClient, polls until ready, and asserts the mastered artifact is
stored and served over a signed URL. Also verifies the raw file is deleted.
"""

import asyncio
import io
import time

import numpy as np
import soundfile as sf

from audio_streaming.app import create_app
from audio_streaming.config import Settings
from audio_streaming.security import issue_identity


def _make_mobile_clip(path: str, sr: int = 48000) -> None:
    """Synthetic founder voice-ish clip with realistic mobile capture defects."""
    dur = 4.0
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    # Vowel-ish fundamental + a couple of harmonics (looks like speech energy).
    f0 = 140.0
    sig = (
        0.30 * np.sin(2 * np.pi * f0 * t)
        + 0.12 * np.sin(2 * np.pi * 2 * f0 * t)
        + 0.06 * np.sin(2 * np.pi * 3 * f0 * t)
    )
    # 1) Dead-air lead (1.2 s of near-silence).
    sig[: int(1.2 * sr)] *= 0.0005
    # 2) Clipping: a loud burst near the end flat-tops at +/-0.98.
    burst = slice(int(2.5 * sr), int(2.8 * sr))
    sig[burst] = np.clip(sig[burst] * 4.0, -0.98, 0.98)
    # 3) Plosive pop: short low-frequency burst at ~1.6 s.
    pop_start = int(1.6 * sr)
    pop_len = int(0.02 * sr)
    sig[pop_start: pop_start + pop_len] += (
        0.5 * np.sin(2 * np.pi * 80 * t[:pop_len])
        * np.hanning(pop_len)
    )
    sig = np.clip(sig, -1.0, 1.0).astype(np.float32)
    sf.write(path, sig, sr, subtype="PCM_16")


def test_upload_pipeline_end_to_end():
    settings = Settings(
        environment="test",
        data_dir=__import__("pathlib").Path("runtime-data/test-e2e"),
        database_path=__import__("pathlib").Path("runtime-data/test-e2e/streaming.db"),
        auth_secret=b"x" * 40, capability_secret=b"y" * 40,
        watermark_secret=b"z" * 40, segment_key_secret=b"w" * 40,
    )
    # Clean slate.
    import shutil
    if settings.data_dir.exists():
        shutil.rmtree(settings.data_dir)
    app = create_app(settings)
    app.state.loop = asyncio.new_event_loop()

    token = issue_identity(settings.auth_secret, "founder_likhith")
    headers = {"Authorization": f"Bearer {token}"}

    with io.BytesIO() as buf:
        _make_mobile_clip_to_buffer(buf, sr=48000)
        raw_bytes = buf.getvalue()

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        # 1) Upload
        resp = client.post(
            "/v1/uploads",
            headers=headers,
            files={"file": ("recording.wav", raw_bytes, "audio/wav")},
            data={"title": "My founder thoughts", "output_format": "mp3"},
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        job_id = body["job_id"]
        asset_id = body["asset_id"]
        assert body["status"] == "queued"

        # 2) Poll until ready (background executor runs CPU work).
        status_url = f"/v1/uploads/{job_id}"
        ready = False
        for _ in range(60):
            r = client.get(status_url, headers=headers)
            assert r.status_code == 200, r.text
            if r.json()["status"] == "ready":
                ready = True
                break
            time.sleep(0.5)
        assert ready, "job did not become ready in time"

        done = client.get(status_url, headers=headers).json()
        assert done["report"] is not None
        rep = done["report"]
        # Repair must have detected the defects.
        assert rep["repair"]["clipped_samples_before"] > 0, "expected clipping to be detected"
        assert rep["repair"]["silence_trimmed"] is True, "expected dead-air trim"
        # Studio mastering produced a sane loudness target.
        assert -20.0 <= rep["enhance"]["output_lufs"] <= -12.0, rep["enhance"]["output_lufs"]
        # Download signed URLs present.
        assert "mp3" in done["download"]

        # 3) Fetch the stored mastered file via the signed URL.
        dl = client.get(done["download"]["mp3"])
        assert dl.status_code == 200, dl.text
        assert dl.headers["content-type"].startswith("audio/")
        assert len(dl.content) > 1000

        # 4) Raw file deleted after processing.
        raw_path = settings.data_dir / "uploads" / f"{asset_id}.raw"
        assert not raw_path.exists(), "raw file must be deleted after processing"

    app.state.loop.close()
    if settings.data_dir.exists():
        shutil.rmtree(settings.data_dir)


def _make_mobile_clip_to_buffer(buf: io.BytesIO, sr: int = 48000) -> None:
    """Same as _make_mobile_clip but write into an in-memory WAV buffer."""
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmp:
        p = f"{tmp}/clip.wav"
        _make_mobile_clip(p, sr)
        with open(p, "rb") as fh:
            buf.write(fh.read())
    buf.seek(0)
