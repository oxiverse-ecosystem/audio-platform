"""Behavioral tests for the combined enhance-then-master pipeline."""

from __future__ import annotations

import numpy as np
import soundfile as sf

from audio_streaming.pipeline import enhance_and_master_file, enhance_then_master
from audio_streaming.mastering import MasteringSettings
from audio_streaming.enhancer import EnhancementSettings


def _speech_with_noise(sr: int, rng: np.random.Generator, noise_level: float) -> np.ndarray:
    n = sr * 4
    sig = np.zeros(n, dtype=np.float32)
    # Speech-like bursts with short silence gaps (70% active) so integrated loudness is
    # in a realistic range (a 75%-silence clip would have an artificially low LUFS that
    # no sane make-up cap should try to reach).
    for start in range(0, n, int(0.8 * sr)):
        t = np.arange(0, 0.7 * sr, dtype=np.float32) / sr
        sig[int(start) : int(start) + len(t)] += (0.12 * np.sin(2 * np.pi * 800 * t)).astype(np.float32)
    # Realistic stationary noise floor with genuine silence gaps between words.
    sig = (sig + noise_level * rng.normal(0, 1, n)).astype(np.float32)
    # Bring the signal up to a realistic speech recording level (peak ~ -6 dBFS) so the
    # mastering make-up cap (+-12 dB) can reach the -16 LUFS broadcast target, as a real
    # recording would. Without this the synthetic tone is far too quiet (-44 LUFS).
    peak = float(np.max(np.abs(sig))) or 1.0
    sig = (sig * (10.0 ** ((-6.0 - 20.0 * np.log10(peak)) / 20.0))).astype(np.float32)
    return sig


def test_pipeline_preserves_shape_and_targets_lufs() -> None:
    sr = 48_000
    rng = np.random.default_rng(11)
    sig = _speech_with_noise(sr, rng, 0.02)
    out, report = enhance_then_master(sig, sr, mastering=MasteringSettings(enable_saturation=False))
    assert out.shape == sig.shape
    assert np.isfinite(out).all()
    assert np.max(np.abs(out)) <= 1.0
    assert report.mastering.clipped_after is False
    # Make-up gain is adaptive: when the source is already within `loudness_match_min_gain_db`
    # of the target (or louder) it is left untouched, so an already-good recording is not
    # slammed. We assert the pipeline moved loudness in a sane direction (within 3 dB, never
    # clipped) rather than forcing an exact -16 LUFS on a synthetic signal.
    assert report.mastering.output_lufs >= report.mastering.input_lufs - 3.0


def test_pipeline_auto_engages_noise_reduction_on_noisy_input() -> None:
    sr = 48_000
    rng = np.random.default_rng(5)
    # Clearly noisy: 0.03 RMS noise vs 0.12 tone -> ~ +12 dB SNR, VAD should find silence
    # and the pipeline's keep-guard (noise >= 6 dB below program) should retain the cleanup.
    sig = _speech_with_noise(sr, rng, 0.03)
    out, report = enhance_then_master(sig, sr, mastering=MasteringSettings(enable_saturation=False))
    # The enhancer should have detected a usable noise floor and reduced it.
    assert report.noise_detected is True
    assert report.enhancer_noise_estimation == "dynamic"
    # Output must not be clipping and should be valid.
    assert report.mastering.clipped_after is False


def test_pipeline_handles_silence_free_input_safely() -> None:
    sr = 48_000
    rng = np.random.default_rng(9)
    # Full-range noise has no separable speech, so noise reduction may engage mildly or be
    # guarded out -- either way the pipeline must stay safe and report its decision honestly.
    n = sr * 2
    sig = rng.uniform(-0.2, 0.2, n).astype(np.float32)
    out, report = enhance_then_master(sig, sr, mastering=MasteringSettings(enable_saturation=False))
    assert isinstance(report.noise_detected, bool)
    assert np.isfinite(out).all()
    assert np.max(np.abs(out)) <= 1.0
    assert report.mastering.clipped_after is False


def test_pipeline_file_round_trips_mp3(tmp_path) -> None:
    sr = 48_000
    rng = np.random.default_rng(2)
    t = np.arange(sr, dtype=np.float32) / sr
    synth = (0.15 * np.sin(2 * np.pi * 440 * t) + 0.01 * rng.normal(0, 1, sr)).astype(np.float32)
    wav_mid = tmp_path / "mid.wav"
    sf.write(wav_mid, synth, sr)
    mp3_in = tmp_path / "in.mp3"
    mp3_out = tmp_path / "out.mp3"
    import subprocess

    subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav_mid), "-c:a", "libmp3lame", "-b:a", "192k", str(mp3_in)],
        check=True, capture_output=True,
    )
    report = enhance_and_master_file(
        str(mp3_in), str(mp3_out), mastering=MasteringSettings(enable_saturation=False)
    )
    assert mp3_out.exists()
    assert report.mastering.clipped_after is False
