"""Behavioral regression tests for the CPU-only studio-mastering chain."""

from __future__ import annotations

import numpy as np
import soundfile as sf

from audio_streaming.mastering import (
    MasteringSettings,
    integrated_loudness_lufs,
    master_file,
    master_voice,
)


def test_mastering_preserves_shape_finiteness_and_headroom() -> None:
    sr = 48_000
    rng = np.random.default_rng(1)
    # Speech-like: 1 kHz tone bursts with pauses + mild noise.
    n = sr * 3
    sig = np.zeros(n, dtype=np.float32)
    for start in (0, 1 * sr, 2 * sr):
        t = np.arange(0, 0.6 * sr, dtype=np.float32) / sr
        sig[int(start) : int(start) + len(t)] += (0.15 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    sig = (sig + 0.01 * rng.normal(0, 1, n)).astype(np.float32)
    out, report = master_voice(sig, sr)
    assert out.shape == sig.shape
    assert np.isfinite(out).all()
    assert np.max(np.abs(out)) <= 1.0
    assert report.clipped_after is False


def test_loudness_measurement_is_reasonable() -> None:
    sr = 48_000
    # A -20 dBFS sine should read a plausible LUFS value (not +inf, not nan).
    tone = (0.1 * np.sin(2 * np.pi * 1000 * np.arange(sr) / sr)).astype(np.float32)
    lufs = integrated_loudness_lufs(tone, sr)
    assert -45.0 < lufs < -10.0


def test_mastering_targets_requested_lufs() -> None:
    sr = 48_000
    rng = np.random.default_rng(3)
    n = sr * 4
    sig = np.zeros(n, dtype=np.float32)
    for start in range(0, n, int(0.8 * sr)):
        t = np.arange(0, 0.5 * sr, dtype=np.float32) / sr
        sig[int(start) : int(start) + len(t)] += (0.12 * np.sin(2 * np.pi * 800 * t)).astype(np.float32)
    sig = (sig + 0.008 * rng.normal(0, 1, n)).astype(np.float32)
    settings = MasteringSettings(target_lufs=-16.0, enable_saturation=False)
    out, report = master_voice(sig, sr, settings)
    # Output integrated loudness should land near the target within a sane tolerance.
    assert abs(report.output_lufs - settings.target_lufs) < 4.0


def test_adaptive_highpass_clamps_to_protect_chest_warmth() -> None:
    """Even a high detected F0 must never push the cutoff above the warmth-protecting clamp."""
    sample_rate = 48_000
    n = sample_rate * 2
    # 214 Hz fundamental (as Gemini's critique describes) with silence gaps.
    sig = np.zeros(n, dtype=np.float32)
    t = np.arange(0, 0.4 * sample_rate, dtype=np.float32) / sample_rate
    for start in (0, 0.7 * sample_rate, 1.4 * sample_rate):
        sig[int(start):int(start) + len(t)] += (0.2 * np.sin(2 * np.pi * 214 * t)).astype(np.float32)
    from audio_streaming.enhancer import _high_pass_cutoff, EnhancementSettings
    settings = EnhancementSettings(adaptive_highpass=True, adaptive_highpass_max_hz=95.0)
    cutoff, detected = _high_pass_cutoff(sig, sample_rate, settings)
    # Cutoff must be <= 95 Hz (never 171 Hz), so 100-160 Hz body is preserved.
    assert cutoff <= 95.0
    assert detected is not None


def test_room_notch_triggers_on_synthetic_resonance_and_skips_flat() -> None:
    from audio_streaming.mastering import _ltas_room_notch, MasteringSettings
    sr = 48_000
    n = sr * 2
    t = np.arange(n, dtype=np.float32) / sr
    # Speech-ish base (1 kHz tone bursts) + a strong stationary 300 Hz room resonance.
    base = 0.1 * np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    resonance = 0.15 * np.sin(2 * np.pi * 300 * t).astype(np.float32)
    # Modulate base with a slow envelope so it has pauses; keep resonance continuous.
    env = (np.sin(2 * np.pi * 0.5 * t) > 0).astype(np.float32)
    sig = ((base * env) + resonance).astype(np.float32)
    freq, cut = _ltas_room_notch(sig, sr, MasteringSettings())
    assert freq is not None and 250.0 <= freq <= 500.0
    assert cut <= 0.0  # a cut (negative dB)

    # Flat (no resonance) signal -> no notch applied.
    flat = (0.1 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    freq2, cut2 = _ltas_room_notch(flat, sr, MasteringSettings())
    assert freq2 is None and cut2 == 0.0


def test_air_compensation_boosts_dulled_highs() -> None:
    from audio_streaming.mastering import _air_compensation_gain, MasteringSettings
    sr = 48_000
    n = sr * 2
    t = np.arange(n, dtype=np.float32) / sr
    # Full-band speech energy but with the high band artificially dulled (low-pass at 6 kHz).
    from scipy.signal import butter, sosfilt
    full = (0.1 * np.sin(2 * np.pi * 1000 * t) + 0.05 * np.sin(2 * np.pi * 9000 * t)).astype(np.float32)
    sos = butter(4, 6000.0, btype="lowpass", fs=sr, output="sos")
    dull = sosfilt(sos, full)
    gain = _air_compensation_gain(dull, sr, MasteringSettings())
    # Dulled highs should yield a positive (boosting) air gain, at least the minimum.
    assert gain >= 1.5


def test_downward_expander_ducks_silence_without_pumping() -> None:
    from audio_streaming.mastering import _downward_expander
    sr = 48_000
    n = 4 * sr  # long clip so the 200 ms release fully decays into the quiet band
    t = np.arange(n, dtype=np.float32) / sr
    # Loud speech chunk (0.5 s) then a long quiet noise floor (room residual) well below threshold.
    speech = 0.3 * np.sin(2 * np.pi * 200 * t[: int(0.5 * sr)]).astype(np.float32)
    noise = 0.002 * np.sin(2 * np.pi * 1200 * t[int(0.5 * sr):]).astype(np.float32)  # ~ -54 dBFS
    sig = np.concatenate([speech, noise]).astype(np.float32)
    out = _downward_expander(sig, sr, threshold_dbfs=-45.0, ratio=1.5,
                             attack_ms=50.0, release_ms=200.0)
    # Loud half essentially untouched; the settled tail of the quiet band is ducked.
    loud_in = float(np.max(np.abs(sig[: int(0.4 * sr)])))
    loud_out = float(np.max(np.abs(out[: int(0.4 * sr)])))
    tail = slice(3 * sr, n)
    quiet_in = float(np.max(np.abs(sig[tail])))
    quiet_out_tail = float(np.max(np.abs(out[tail])))
    assert loud_out >= loud_in * 0.99
    assert quiet_out_tail < quiet_in * 0.9


def test_dc_block_removes_offset() -> None:
    from audio_streaming.enhancer import _dc_block
    sr = 48_000
    n = sr
    t = np.arange(n, dtype=np.float32) / sr
    sig = (0.2 * np.sin(2 * np.pi * 200 * t) + 0.05).astype(np.float32)  # +0.05 DC offset
    out = _dc_block(sig, sr, cutoff_hz=10.0)
    # DC component (mean) should be removed; the AC tone survives.
    assert abs(float(np.mean(out))) < 1e-3
    assert abs(float(np.mean(sig)) - 0.05) < 1e-3


def test_adaptive_deesser_threshold_tracks_post_shelf_level() -> None:
    from audio_streaming.mastering import _adaptive_deesser_threshold
    sr = 48_000
    n = sr
    t = np.arange(n, dtype=np.float32) / sr
    # Quiet sibilant-band signal -> low RMS -> threshold clamped to a sane floor.
    quiet = (0.001 * np.sin(2 * np.pi * 6500 * t)).astype(np.float32)
    thr_q = _adaptive_deesser_threshold(quiet, sr, -28.0)
    assert -40.0 <= thr_q <= -10.0
    # Loud sibilant-band signal -> higher RMS -> higher (less aggressive) threshold.
    loud = (0.2 * np.sin(2 * np.pi * 6500 * t)).astype(np.float32)
    thr_l = _adaptive_deesser_threshold(loud, sr, -28.0)
    assert thr_l >= thr_q


def test_all_stages_off_is_near_pass_through() -> None:
    sr = 48_000
    x = (0.1 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr)).astype(np.float32)
    settings = MasteringSettings(
        enable_eq=False,
        enable_room_notch=False,
        enable_air_comp=False,
        enable_deesser=False,
        enable_expander=False,
        enable_mbc=False,
        enable_compressor=False,
        enable_saturation=False,
        enable_limiter=False,
        enable_loudness_match=False,
    )
    out, _ = master_voice(x, sr, settings)
    # With everything off and no gain, output == input.
    assert np.allclose(out, x, atol=1e-3)


def test_master_file_round_trips_mp3(tmp_path) -> None:
    sr = 48_000
    t = np.arange(sr, dtype=np.float32) / sr
    synth = (0.15 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    wav_mid = tmp_path / "mid.wav"
    sf.write(wav_mid, synth, sr)
    mp3_in = tmp_path / "in.mp3"
    mp3_out = tmp_path / "out.mp3"
    import subprocess

    subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav_mid), "-c:a", "libmp3lame", "-b:a", "192k", str(mp3_in)],
        check=True, capture_output=True,
    )
    report = master_file(str(mp3_in), str(mp3_out), MasteringSettings(enable_saturation=False))
    assert mp3_out.exists()
    assert report.clipped_after is False
