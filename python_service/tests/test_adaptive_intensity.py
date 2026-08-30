"""Unit test: adaptive mastering intensity never thins a clean voice, rescues noise.

Proves the ``adaptive_intensity`` gate scales de-esser / compressor / saturation DOWN on
a clean recording (floor) and UP on a noisy one, using the same signal-derived
``cleanliness`` factor the production chain uses. Pure DSP, no ML, deterministic.
"""

import numpy as np

from audio_streaming.mastering import MasteringSettings, master_voice


def _make_clean(sr: int, dur: float = 4.0) -> np.ndarray:
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    sig = 0.3 * np.sin(2 * np.pi * 150 * t) + 0.1 * np.sin(2 * np.pi * 300 * t)
    return sig.astype(np.float32)


def _make_noisy(sr: int, dur: float = 4.0) -> np.ndarray:
    clean = _make_clean(sr, dur)
    rng = np.random.default_rng(0)
    noise = rng.standard_normal(clean.shape).astype(np.float32) * 0.08
    return np.clip(clean + noise, -1.0, 1.0).astype(np.float32)


def test_adaptive_intensity_scales_up_on_noise():
    sr = 48000
    settings = MasteringSettings()  # adaptive_intensity=True, floor=0.35
    _, clean_rep = master_voice(_make_clean(sr), sr, settings)
    _, noisy_rep = master_voice(_make_noisy(sr), sr, settings)

    # Noisy recording gets strictly more intensity than a clean one.
    assert noisy_rep.cleanliness > clean_rep.cleanliness, (
        noisy_rep.cleanliness, clean_rep.cleanliness
    )
    # Clean recording is pulled down to the safety floor (insurance vs thinning).
    assert clean_rep.cleanliness == 0.35
    # Both stay true-peak safe and within a sane broadcast band (the loudness-match stage
    # only boosts when materially quieter than target, so an already-loud synthetic tone
    # stays near its input level -- that is correct, not a bug).
    for rep in (clean_rep, noisy_rep):
        assert rep.output_true_peak_dbfs <= -1.0 + 0.2
        assert -24.0 <= rep.output_lufs <= -8.0


def test_adaptive_intensity_disabled_gives_full_preset():
    sr = 48000
    settings = MasteringSettings(adaptive_intensity=False)
    _, rep = master_voice(_make_clean(sr), sr, settings)
    assert rep.cleanliness == 1.0
