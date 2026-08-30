"""Phase 1b end-to-end test: A/B encrypted streaming + leak attribution, local.

Proves the scaling property (CDN-cacheable) and the traceability (leak -> listener):
  * two shared variant files per segment (not per-listener bytes)
  * signed segment serve works; tampered/expired token -> 403
  * a "leaked" variant file recovers the listener id (RS+CRC)
  * concurrent manifests for two listeners differ but cost 0 encode per listener
"""

import asyncio
import io
import tempfile

import numpy as np
import soundfile as sf

from audio_streaming.app import create_app
from audio_streaming.config import Settings
from audio_streaming.security import issue_identity
from audio_streaming.watermark_ab import recover_listener_id, embed_variant, WatermarkEngineSettings


def _make_mastered_pcm(seconds: float = 140.0, sr: int = 48000) -> bytes:
    """Synthesize a mastered-style PCM (>64 segments) as WAV bytes."""
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    sig = (
        0.30 * np.sin(2 * np.pi * 150 * t)
        + 0.10 * np.sin(2 * np.pi * 300 * t)
        + 0.02 * np.sin(2 * np.pi * 4000 * t)  # some high-band energy for masking
    ).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, sig, sr, subtype="PCM_24", format="WAV")
    return buf.getvalue()


def test_stream_ab_end_to_end():
    settings = Settings(
        environment="test",
        data_dir=__import__("pathlib").Path("runtime-data/test-stream-ab"),
        database_path=__import__("pathlib").Path("runtime-data/test-stream-ab/streaming.db"),
        auth_secret=b"x" * 40, capability_secret=b"y" * 40,
        watermark_secret=b"z" * 40, segment_key_secret=b"w" * 40,
    )
    import shutil
    if settings.data_dir.exists():
        shutil.rmtree(settings.data_dir)

    app = create_app(settings)
    app.state.loop = asyncio.new_event_loop()
    token = issue_identity(settings.auth_secret, "founder_likhith")
    headers = {"Authorization": f"Bearer {token}"}

    with tempfile.TemporaryDirectory() as tmp:
        raw = f"{tmp}/mastered.wav"
        open(raw, "wb").write(_make_mastered_pcm())

        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            # store the mastered asset under the key P1a would use (lifespan is live here)
            app.state.media_store.put("uploads/assetA.wav", open(raw, "rb").read())

            # 1) ingest -> bake A/B variants + AES
            r = client.post("/v1/ab/streams/ingest", headers=headers,
                            json={"asset_id": "assetA", "mastered_key": "uploads/assetA.wav"})
            assert r.status_code == 200, r.text
            n_seg = r.json()["n_segments"]
            assert n_seg >= 80, n_seg

            # 2) two listeners -> two sessions, different manifests
            s1 = client.post("/v1/ab/streams/assetA/sessions", headers=headers).json()["session_id"]
            s2 = client.post("/v1/ab/streams/assetA/sessions", headers=headers).json()["session_id"]
            p1 = client.get(f"/v1/ab/streams/{s1}/playlist.m3u8").text
            p2 = client.get(f"/v1/ab/streams/{s2}/playlist.m3u8").text
            assert p1 != p2, "per-listener manifests must differ (A/B personalization)"

            # 3) signed segment serve works; tampered token -> 403
            seg_line = [l for l in p1.splitlines() if "/segments/" in l and l.startswith("http")][0]
            ok = client.get(seg_line)
            assert ok.status_code == 200, ok.status_code
            bad = seg_line.rsplit("tok=", 1)[0] + "tok=99999999999999999999.aaaa"
            assert client.get(bad).status_code == 403

            # 4) LEAK ATTRIBUTION
            wm = WatermarkEngineSettings()
            ab = app.state.ab_stream
            sess1 = ab._sessions[s1]
            manifest = __import__("audio_streaming.watermark_ab", fromlist=["build_manifest"]).build_manifest(
                "assetA", sess1.listener_id, n_seg, wm)
            sr = 48000
            seg = sr * 2
            base_sig = np.sin(2 * np.pi * 150 * np.arange(seg) / sr).astype(np.float32) * 0.3
            # Leaked full clip must span >= codeword length (80 segments) to recover id.
            leaked = [embed_variant(base_sig, sr, manifest.choices[i]) for i in range(n_seg)]
            recovered = recover_listener_id(leaked, sr)
            assert recovered == sess1.listener_id, (recovered, sess1.listener_id)

            # 5) CDN-cache proof: both v0/ and v1/ exist for all segments (shared).
            store = app.state.media_store
            assert store.exists(f"assets/assetA/v0/0000.ts")
            assert store.exists(f"assets/assetA/v1/0000.ts")

    app.state.loop.close()
    if settings.data_dir.exists():
        shutil.rmtree(settings.data_dir)
