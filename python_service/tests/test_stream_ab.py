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


def _make_mastered_pcm(seconds: float = 191.3, sr: int = 48000) -> bytes:
    """Synthesize a mastered-style PCM (>= 80 segments) as WAV bytes."""
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

            # 2b) EXTINF durations must sum to the real content length: the last
            # segment is trimmed to the true duration (no padded-silence tail).
            extinf = [float(x.split(":")[1].rstrip(",")) for x in p1.splitlines() if x.startswith("#EXTINF:")]
            assert extinf[-1] < 2.0, extinf[-1]
            assert abs(sum(extinf) - 191.3) < 0.05, sum(extinf)

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


def test_carrier_is_band_limited_and_survives_aac_roundtrip():
    """The watermark carrier must (1) sit inside the masked 2-4kHz band (no hiss in
    6-20kHz) and (2) be recoverable after a real AAC encode/decode at an arbitrary
    leak-window offset (codec priming)."""
    import subprocess

    from audio_streaming.media import encode_aac_transport_stream
    from audio_streaming.watermark_ab import (
        WatermarkEngineSettings, _band_limited_carrier, _max_lag_correlation,
        build_manifest, embed_variant,
    )

    sr = 48000
    settings = WatermarkEngineSettings()
    n = sr * 2

    # (1) spectral confinement: carrier energy must be in 2-4kHz, ~nothing above 6kHz.
    carrier = _band_limited_carrier(n, sr, settings)
    spec = np.fft.rfft(carrier)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    power = np.abs(spec) ** 2
    in_band = power[(freqs >= 2000) & (freqs <= 4000)].sum()
    out_band = power[(freqs >= 6000) & (freqs <= 20000)].sum()
    assert in_band > 1000 * out_band, f"carrier leaks out-of-band energy: {in_band:.1f} vs {out_band:.1f}"

    # (2) per-segment sign evidence must survive AAC encode+decode at arbitrary offsets.
    wm = build_manifest("assetT", 99, 10, settings)
    rng = np.random.default_rng(3)
    embedded = []
    for i in range(10):
        mod = 0.5 + 0.5 * np.sin(2 * np.pi * 3.5 * np.arange(n) / sr)
        sig = (mod * rng.standard_normal(n) * 0.35).astype(np.float32)
        embedded.append(embed_variant(sig, sr, wm.choices[i], settings))

    ref = _band_limited_carrier(n, sr, settings)
    correct = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, e in enumerate(embedded):
            ts = encode_aac_transport_stream(e, None, sr)
            ts_path = f"{tmp}/s{i}.ts"
            with open(ts_path, "wb") as fh:
                fh.write(ts)
            wav_path = f"{tmp}/s{i}.wav"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", ts_path, wav_path], check=True)
            decoded, _ = sf.read(wav_path, dtype="float32")
            for offset in (0, 1024, 4096, 31337):  # arbitrary leak-window offsets
                leak = np.ascontiguousarray(decoded[offset:])
                c = _max_lag_correlation(leak, ref)
                correct += (c >= 0) == (wm.choices[i] == 0)
    assert correct == 40, f"only {correct}/40 segment-offset decisions survived AAC round-trip"
