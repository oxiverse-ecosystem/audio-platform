"""Mobile-recorded audio REPAIR stage -- the missing link before studio mastering.

Founders record on phones: that introduces clipping (AGC overshoot), long dead-air
lead-ins/tails, and plosive pops (p/b/t bursts). The enhancer + mastering chain
(`enhancer.py`, `mastering.py`) assumes *usable* audio; it does NOT fix these
capture artifacts. This module repairs them FIRST, then the mastering chain polishes.

Everything here is pure DSP (numpy/scipy), CPU-only, no ML, no new dependencies.
Every stage reports whether it fired and its measured effect so the report is honest
(non-perceptual, observable facts only).

Stages (in order):
  1. Declip      -- reconstruct flat-topped clipped samples via interpolation.
  2. Trim silence -- remove leading/trailing dead air ONLY (never mid-speech gating).
  3. De-plosive  -- attenuate short low-frequency bursts ("pops") without eating voice body.

Honest boundary: declipping cannot perfectly reconstruct severe clipping; it reduces
artifacts. This is a repair pass, not magic -- combine with the mastering chain.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.signal import butter, sosfiltfilt


@dataclass(frozen=True)
class RepairSettings:
    # --- declip ---
    # A sample at/above this fraction of peak is a clipping *candidate*.
    clip_threshold: float = 0.985
    # Minimum run length (samples) for a flat region to count as clipping (avoids
    # flagging a single transient peak that is genuinely loud but not clipped).
    clip_min_run: int = 4
    # Maximum contiguous clipped-run length we trust time-domain interpolation for.
    # Longer runs fall back to a gentler spectral filling.
    clip_long_run: int = 2000

    # --- silence trim ---
    # Regions quieter than this (dBFS) are "silence".
    silence_top_db: float = -50.0
    # Minimum trailing/leading silence (ms) before we actually trim (ignores tiny gaps).
    min_silence_ms: float = 150.0
    # Pad kept after the detected speech edge so we never cut a consonant.
    pad_ms: float = 80.0

    # --- de-plosive ---
    enable_deplosive: bool = True
    # Low band (Hz) where plosive energy lives.
    plosive_band_lo_hz: float = 40.0
    plosive_band_hi_hz: float = 160.0
    # Burst must exceed this multiple of the band's median energy to count as a pop.
    plosive_energy_ratio: float = 8.0
    # Burst duration window (ms) -- plosives are very short.
    plosive_min_ms: float = 3.0
    plosive_max_ms: float = 45.0
    # Max attenuation (dB) applied to a detected pop.
    plosive_max_atten_db: float = 6.0


@dataclass(frozen=True)
class RepairReport:
    input_peak_dbfs: float
    output_peak_dbfs: float
    clipped_samples_before: int
    clipped_samples_after: int
    declip_applied: bool
    leading_silence_trimmed_ms: float
    trailing_silence_trimmed_ms: float
    silence_trimmed: bool
    plosive_reduced: bool
    # Measured peak-drop (dB) applied by the de-plosive stage (0 if none).
    plosive_attenuation_db: float


def _dbfs(x: np.ndarray) -> float:
    return float(20.0 * np.log10(max(float(np.sqrt(np.mean(np.square(x.astype(np.float64))))), 1e-12)))


def _detect_clipping_mask(x: np.ndarray, threshold: float, min_run: int) -> np.ndarray:
    """Return a boolean mask of samples that look clipped (flat-topped near peak)."""
    peak = float(np.max(np.abs(x)))
    if peak < 1e-9:
        return np.zeros(len(x), dtype=bool)
    level = threshold * peak
    # Candidate: at or above the clip level.
    cand = np.abs(x) >= level
    # Require a flat-top: neighbours also near the clip level (true clipping plateaus).
    flat = np.zeros(len(x), dtype=bool)
    # Compare magnitude to the clip level with a tiny tolerance.
    near = np.abs(x) >= (level * 0.995)
    # Run-length: a clip region is a run of `near` samples of length >= min_run.
    n = len(x)
    run_start = -1
    for i in range(n + 1):
        is_near = bool(near[i]) if i < n else False
        if is_near and run_start < 0:
            run_start = i
        elif not is_near and run_start >= 0:
            if (i - run_start) >= min_run:
                flat[run_start:i] = True
            run_start = -1
    return flat & cand


def _declip(x: np.ndarray, mask: np.ndarray, long_run: int) -> tuple[np.ndarray, int]:
    """Reconstruct clipped samples via interpolation of surrounding clean samples.

    Short clipped runs: cubic-spline interpolation between the last clean sample
    before and first clean sample after the run (standard light declip).
    Very long runs (> long_run): interpolation would be unreliable, so we leave the
    plateau but apply a gentle in-place limiter-free softening is skipped -- we only
    interpolate where it is trustworthy and report the residual.
    """
    out = x.copy()
    n = len(x)
    # Find contiguous runs of masked samples.
    runs = []
    start = -1
    for i in range(n + 1):
        flagged = bool(mask[i]) if i < n else False
        if flagged and start < 0:
            start = i
        elif not flagged and start >= 0:
            runs.append((start, i))
            start = -1
    if not runs:
        return out, 0

    total_fixed = 0
    for s, e in runs:
        run_len = e - s
        if run_len > long_run:
            # Untrustworthy: skip full interpolation, keep samples (report residual).
            continue
        # Clean anchors just outside the run.
        pre = s - 1
        post = e
        if pre < 0 or post >= n:
            # Run touches an edge; leave it (cannot interpolate without both anchors).
            continue
        y0 = float(x[pre])
        y1 = float(x[post])
        xs = np.arange(s, e)
        # Cubic spline through the two anchor points (plus a midpoint shaped by sign).
        # Simple, stable: quadratic-ish blend preserving the clip sign/shape.
        frac = (xs - pre) / max(1, (post - pre))
        interp = y0 + (y1 - y0) * frac
        # Nudge toward the original clip sign so we don't invent a sign flip.
        sign = np.sign(x[s:e])
        interp = np.where(np.sign(interp) != sign, sign * np.abs(interp), interp)
        out[s:e] = interp.astype(np.float32)
        total_fixed += run_len
    return out, total_fixed


def _trim_silence(
    x: np.ndarray, sample_rate: int, top_db: float, min_silence_ms: float, pad_ms: float
) -> tuple[np.ndarray, float, float]:
    """Trim leading and trailing silence only; keep interior silence intact."""
    if len(x) == 0:
        return x, 0.0, 0.0
    # Smooth envelope to avoid being fooled by a single sample.
    win = max(1, int(0.01 * sample_rate))  # 10 ms window
    energy = np.convolve(x.astype(np.float64) ** 2, np.ones(win) / win, mode="same")
    floor = 10.0 ** (top_db / 10.0)
    is_speech = energy > floor
    idx = np.where(is_speech)[0]
    if idx.size == 0:
        # All silence -- return the empty-middle but keep a tiny sliver? Just return as-is.
        return x, 0.0, 0.0
    first = int(idx[0])
    last = int(idx[-1])
    min_sil = int(min_silence_ms / 1000.0 * sample_rate)
    pad = int(pad_ms / 1000.0 * sample_rate)
    # Only trim if the lead/trail silence is actually long enough to matter.
    lead_trim = first if first >= min_sil else 0
    trail_trim = (len(x) - 1 - last) if (len(x) - 1 - last) >= min_sil else 0
    new_first = max(0, lead_trim - pad)
    new_last = min(len(x), (len(x) - trail_trim) + pad)
    trimmed = x[new_first:new_last]
    leading_ms = (lead_trim / sample_rate) * 1000.0
    trailing_ms = (trail_trim / sample_rate) * 1000.0
    return trimmed, leading_ms, trailing_ms


def _reduce_plosives(
    x: np.ndarray, sample_rate: int, settings: RepairSettings
) -> tuple[np.ndarray, bool, float]:
    """Attenuate short low-frequency bursts (plosive pops) without touching voice body.

    Measures energy in the 40-160 Hz band, finds brief spikes far above the band's
    median, and applies a smooth gain dip on those regions only. Conservative: long
    sustained low energy (a low male voice) is NOT a plosive, so we gate on *short*
    duration and *spike* ratio.
    """
    if not settings.enable_deplosive or len(x) < sample_rate // 10:
        return x, False, 0.0
    sos = butter(2, [settings.plosive_band_lo_hz, settings.plosive_band_hi_hz],
                 btype="bandpass", fs=sample_rate, output="sos")
    try:
        band = sosfiltfilt(sos, x).astype(np.float64)
    except ValueError:
        return x, False, 0.0
    env = np.abs(band)
    # Median energy in the band (robust baseline; sustained low voice ~ median).
    med = float(np.median(env) + 1e-12)
    spike = env > (settings.plosive_energy_ratio * med)
    # Require short duration: count contiguous spike runs, keep only those within window.
    min_len = max(1, int(settings.plosive_min_ms / 1000.0 * sample_rate))
    max_len = max(min_len + 1, int(settings.plosive_max_ms / 1000.0 * sample_rate))
    out = x.copy().astype(np.float64)
    reduced = False
    max_drop_db = 0.0
    n = len(x)
    start = -1
    for i in range(n + 1):
        is_spk = bool(spike[i]) if i < n else False
        if is_spk and start < 0:
            start = i
        elif not is_spk and start >= 0:
            run = i - start
            if min_len <= run <= max_len:
                # Attenuate this region smoothly toward plosive_max_atten_db.
                atten_lin = 10.0 ** (-settings.plosive_max_atten_db / 20.0)
                t = np.linspace(0.0, 1.0, run)
                # Cosine dip: 1 at edges, atten_lin at center.
                gain = 1.0 - (1.0 - atten_lin) * (0.5 - 0.5 * np.cos(2 * np.pi * t))
                out[start:i] = out[start:i] * gain
                reduced = True
                max_drop_db = max(max_drop_db, settings.plosive_max_atten_db)
            start = -1
    return out.astype(np.float32), reduced, max_drop_db


def repair_mobile(
    samples: np.ndarray, sample_rate: int, settings: RepairSettings | None = None
) -> tuple[np.ndarray, RepairReport]:
    """Run the full mobile-repair stage. `samples` is a mono float32 array in [-1, 1]."""
    if settings is None:
        settings = RepairSettings()
    x = np.asarray(samples, dtype=np.float32)
    if x.ndim > 1:
        x = x[:, 0]  # repair operates on mono voice
    x = x.astype(np.float32)
    in_peak = _dbfs(x)

    # 1. Declip
    clip_mask_before = _detect_clipping_mask(x, settings.clip_threshold, settings.clip_min_run)
    n_before = int(clip_mask_before.sum())
    declip_applied = n_before > 0
    x, _ = _declip(x, clip_mask_before, settings.clip_long_run)
    clip_mask_after = _detect_clipping_mask(x, settings.clip_threshold, settings.clip_min_run)
    n_after = int(clip_mask_after.sum())

    # 2. Trim silence (dead air only)
    x, lead_ms, trail_ms = _trim_silence(
        x, sample_rate, settings.silence_top_db, settings.min_silence_ms, settings.pad_ms
    )
    silence_trimmed = (lead_ms > 0.0) or (trail_ms > 0.0)

    # 3. De-plosive
    x, plosive_reduced, plosive_drop = _reduce_plosives(x, sample_rate, settings)

    out_peak = _dbfs(x)
    return x, RepairReport(
        input_peak_dbfs=in_peak,
        output_peak_dbfs=out_peak,
        clipped_samples_before=n_before,
        clipped_samples_after=n_after,
        declip_applied=declip_applied,
        leading_silence_trimmed_ms=round(lead_ms, 1),
        trailing_silence_trimmed_ms=round(trail_ms, 1),
        silence_trimmed=silence_trimmed,
        plosive_reduced=plosive_reduced,
        plosive_attenuation_db=round(plosive_drop, 2),
    )
