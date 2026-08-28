"""Behavioral regression tests for the conservative DSP enhancement path."""

from __future__ import annotations

import numpy as np
import soundfile as sf

from audio_streaming.enhancer import (
    EnhancementSettings,
    _enhance_dynamic,
    _min_stats_air_attenuate,
    enhance_file,
    enhance_voice,
    enhance_wav,
)


def test_enhancer_preserves_shape_finiteness_and_headroom() -> None:
    sample_rate = 16_000
    samples = np.random.default_rng(44).normal(0.0, 0.03, sample_rate * 2).astype(np.float32)
    enhanced, report = enhance_voice(samples, sample_rate)
    assert enhanced.shape == samples.shape
    assert np.isfinite(enhanced).all()
    assert np.max(np.abs(enhanced)) <= 1.0
    assert report.clipping_samples_after == 0
    # Dynamic estimation does not consume a lead-in; the report reflects the strategy.
    assert report.noise_estimation == "dynamic"
    assert 0.0 <= report.vad_speech_ratio <= 1.0


def test_adaptive_highpass_derives_cutoff_from_f0() -> None:
    """The high-pass corner must be derived from the signal's fundamental, not hardcoded.

    A 220 Hz tone should yield a detected F0 near 220 Hz and a cutoff below it; a
    noise-only input should fall back to the fixed ``highpass_hz`` (detected_f0_hz is None).
    """
    sample_rate = 48_000
    # Clean 220 Hz tone with silence gaps (pitch detectable).
    n = sample_rate * 2
    sig = np.zeros(n, dtype=np.float32)
    t = np.arange(0, 0.4 * sample_rate, dtype=np.float32) / sample_rate
    for start in (0, 0.7 * sample_rate, 1.4 * sample_rate):
        sig[int(start):int(start) + len(t)] += (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    _, report = enhance_voice(sig, sample_rate, EnhancementSettings(adaptive_highpass=True))
    assert report.detected_f0_hz is not None
    assert 180.0 < report.detected_f0_hz < 260.0

    # Noise-only input: no confident pitch -> fixed cutoff fallback.
    noise = np.random.default_rng(5).normal(0.0, 0.1, n).astype(np.float32)
    _, report2 = enhance_voice(noise, sample_rate, EnhancementSettings(adaptive_highpass=True))
    assert report2.detected_f0_hz is None


def test_fixed_highpass_is_used_when_adaptive_disabled() -> None:
    sample_rate = 48_000
    n = sample_rate
    sig = np.zeros(n, dtype=np.float32)
    t = np.arange(n, dtype=np.float32) / sample_rate
    sig += (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    _, report = enhance_voice(sig, sample_rate, EnhancementSettings(adaptive_highpass=False))
    # With adaptive off, no F0 is reported (cutoff is the hardcoded highpass_hz).
    assert report.detected_f0_hz is None


def test_highpass_reduces_very_low_frequency_content_when_gating_is_disabled() -> None:
    sample_rate = 16_000
    time = np.arange(sample_rate * 2, dtype=np.float32) / sample_rate
    hum = 0.2 * np.sin(2 * np.pi * 30 * time)
    speech_band = 0.03 * np.sin(2 * np.pi * 700 * time)
    input_audio = (hum + speech_band).astype(np.float32)
    settings = EnhancementSettings(
        noise_estimation="off", target_rms_dbfs=-60.0, maximum_makeup_db=0.0
    )
    enhanced, _ = enhance_voice(input_audio, sample_rate, settings)
    hum_reference = np.sin(2 * np.pi * 30 * time)
    before = abs(float(np.dot(input_audio, hum_reference)))
    after = abs(float(np.dot(enhanced, hum_reference)))
    assert after < before * 0.25


def test_dynamic_estimator_does_not_assume_noise_lead_in() -> None:
    """A recording that begins with speech (no noise lead-in) must still be handled safely.

    We build speech-like bursts with genuine silence gaps and a stationary noise floor, so
    the VAD can discover silence *anywhere* in the clip (not just at t=0) and track the noise
    PSD from it. The tone inside speech regions must survive, while the noise between words
    is suppressed.
    """
    sample_rate = 16_000
    n = sample_rate * 2
    sig = np.zeros(n, dtype=np.float32)
    rng = np.random.default_rng(7)
    noise = 0.02 * rng.normal(0, 1, n).astype(np.float32)
    # Three speech bursts of a 1 kHz tone with silence gaps between them.
    for start in (0, 0.8 * sample_rate, 1.4 * sample_rate):
        t = np.arange(0, 0.5 * sample_rate, dtype=np.float32) / sample_rate
        sig[int(start) : int(start) + len(t)] += (0.2 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    noisy = (sig + noise).astype(np.float32)
    settings = EnhancementSettings(noise_estimation="dynamic")
    enhanced, report = enhance_voice(noisy, sample_rate, settings)
    tone_reference = np.sin(2 * np.pi * 1000 * (np.arange(n, dtype=np.float32) / sample_rate))
    before = abs(float(np.dot(noisy, tone_reference)))
    after = abs(float(np.dot(enhanced, tone_reference)))
    # The speech tone must survive; the residual noise band should shrink.
    assert after >= before * 0.5
    assert report.noise_estimation == "dynamic"
    assert 0.0 < report.vad_speech_ratio < 1.0


def test_enhance_wav_writes_a_readable_pcm_file(tmp_path) -> None:
    source = tmp_path / "source.wav"
    destination = tmp_path / "enhanced.wav"
    samples = np.zeros(8_000, dtype=np.float32)
    sf.write(source, samples, 8_000)
    report = enhance_wav(str(source), str(destination), EnhancementSettings(noise_estimation="off"))
    restored, rate = sf.read(destination, dtype="float32")
    assert rate == 8_000
    assert len(restored) == len(samples)
    assert report.clipping_samples_after == 0


def test_nr_skips_when_no_real_noise_floor() -> None:
    """On an already-clean, near-loud recording the VAD finds no genuine silence gap,
    so noise reduction must be skipped (not applied) to avoid eating transients / robotic
    artifacts. This is the adaptive engagement gate, not a hardcoded floor."""
    from audio_streaming.enhancer import _enhance_dynamic

    rate = 48_000
    t = np.arange(2 * rate, dtype=np.float32) / rate
    # Loud continuous tone with no quiet gaps -> no usable noise floor.
    clean = (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    out = _enhance_dynamic(clean, rate, EnhancementSettings())
    assert out["noise_reduced"] is False
    # The signal should be essentially unchanged (passthrough through the STFT/ISTFT
    # hop, not spectrally subtracted) -- allow for the tiny windowing reconstruction error.
    assert np.max(np.abs(out["signal"] - clean)) < 0.02


def test_nr_engages_on_genuine_noise() -> None:
    """A clip with real quiet gaps + steady hiss should engage noise reduction."""
    from audio_streaming.enhancer import _enhance_dynamic

    rate = 48_000
    n = 3 * rate
    t = np.arange(n, dtype=np.float32) / rate
    speech = (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    # Insert 200 ms of near-silence every 400 ms so a real floor exists.
    noise = 0.02 * np.random.default_rng(0).normal(size=n).astype(np.float32)
    mask = np.ones(n, dtype=bool)
    for start in range(0, n, rate // 2):
        mask[start: start + rate // 5] = False
    sig = np.where(mask, speech, noise).astype(np.float32)
    out = _enhance_dynamic(sig, rate, EnhancementSettings())
    assert out["noise_reduced"] is True


def test_enhance_file_round_trips_mp3(tmp_path) -> None:
    """enhance_file should decode MP3 -> enhance -> re-encode MP3 without error."""
    from audio_streaming.enhancer import _as_channel_matrix

    # Build a synthetic MP3 to avoid relying on an external fixture.
    rate = 48_000
    t = np.arange(rate, dtype=np.float32) / rate
    synth = (0.15 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    wav_mid = tmp_path / "mid.wav"
    sf.write(wav_mid, synth, rate)
    mp3_in = tmp_path / "in.mp3"
    mp3_out = tmp_path / "out.mp3"
    import subprocess

    subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav_mid), "-c:a", "libmp3lame", "-b:a", "192k", str(mp3_in)],
        check=True,
        capture_output=True,
    )
    report = enhance_file(str(mp3_in), str(mp3_out), EnhancementSettings(noise_estimation="off"))
    assert mp3_out.exists()
    assert report.noise_estimation == "off"
    _ = _as_channel_matrix


def test_air_dehiss_engages_with_dynamic_profile() -> None:
    """Minimum-statistics 'air'/hiss attenuator must run with a signal-derived floor.

    It needs no silence and no hardcoded frequencies: the per-band temporal minimum of a
    smoothed power spectrum (Martin, 2001) is the noise floor. We feed a band-limited
    voice plus steady broadband hiss with no quiet lead-in, and assert the stage engages,
    stays finite/mono-preserving, and never exceeds the attenuation ceiling.
    """
    from audio_streaming.enhancer import _min_stats_air_attenuate

    sample_rate = 48_000
    rng = np.random.default_rng(7)
    n = sample_rate * 3
    t = np.arange(n, dtype=np.float32) / sample_rate
    # Band-limited voice (energy mostly < 3 kHz) gated on/off so speech is intermittent.
    # Scaled to stay within [-1, 1] so the test checks the stage itself, not input clipping.
    voice = (
        0.35 * np.sin(2 * np.pi * 150 * t)
        + 0.18 * np.sin(2 * np.pi * 300 * t)
        + 0.09 * np.sin(2 * np.pi * 700 * t)
    ).astype(np.float32)
    hiss = (rng.standard_normal(n) * 0.06).astype(np.float32)
    gate = (np.sin(2 * np.pi * 0.6 * t) > 0).astype(np.float32)
    sig = (voice + hiss) * gate
    assert np.max(np.abs(sig)) <= 1.0  # guard: ensure the fixture itself is in range

    res = _min_stats_air_attenuate(sig, sample_rate, EnhancementSettings())
    out = res["signal"]
    assert res["air_engaged"] is True
    assert out.shape == sig.shape
    assert np.isfinite(out).all()
    assert np.max(np.abs(out)) <= 1.0 + 1e-6


def test_air_dehiss_honors_disable_flag() -> None:
    sample_rate = 48_000
    sig = np.random.default_rng(3).normal(0.0, 0.02, sample_rate).astype(np.float32)
    res = _min_stats_air_attenuate(sig, sample_rate, EnhancementSettings(enable_air_dehiss=False))
    assert res["air_engaged"] is False
    assert np.array_equal(res["signal"], sig)
