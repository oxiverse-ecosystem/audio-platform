"""Conservative, explainable DSP voice enhancement for mobile-recorded speech.

This module is intentionally independent of the watermarking path. It does not use a
neural model and does not promise studio-quality output.

Pipeline (per channel)
----------------------
1. Zero-phase high-pass filtering removes handling / air-conditioning rumble below the
   voice band. The cutoff is **derived from the signal**, not hardcoded: an
   autocorrelation fundamental-frequency (F0) estimate of the recording sets the corner
   just below the detected voice floor, so sub-rumble is removed without touching the
   fundamental. When no pitch can be confidently estimated (e.g. noise-only input) it
   falls back to ``highpass_hz``.
2. Spectral noise reduction. Two strategies are available:

   * ``noise_estimation="dynamic"`` (default): a lightweight energy + spectral-flatness
     Voice Activity Detector (VAD) segments the signal into speech and silence and decides
     whether a usable noise floor exists. When it does, the actual noise suppression is
     delegated to ``noisereduce`` (non-stationary adaptive spectral gating -- pure
     numpy/scipy, no ML), which derives its noise profile entirely from the signal's
     quietest regions (no hardcoded floor). This needs no assumption that the clip begins
     with noise, so it works even when speech starts at t=0.
   * ``noise_estimation="fixed_lead_in"``: the original behaviour -- estimate a single
     stationary noise floor from the first ``noise_profile_seconds`` and apply a capped
     spectral gate. Use only when you can guarantee a clean noise lead-in.
   * ``noise_estimation="off"``: skip spectral reduction entirely.

3. A 2:1 soft peak compressor above a threshold, limited loudness make-up toward a target
   RMS, and a true-peak safety limiter.

References
----------
* Dynamic spectral noise gating: Sainburg et al., ``noisereduce`` (non-stationary adaptive
  spectral gating, pure numpy/scipy, no ML) -- the ``dynamic`` strategy delegates the actual
  suppression to it and uses our VAD only to decide engagement.
* Spectral subtraction / signal-presence uncertainty (McAulay & Malpass, IEEE ASSP-28(2),
  1980) remains the basis of the legacy ``fixed_lead_in`` capped gate.
* Fundamental-frequency high-pass: cutoff is derived from an autocorrelation F0 estimate of
  the signal itself (no hardcoded frequency), removing sub-rumble below the voice band.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Literal

import numpy as np
import soundfile as sf
from scipy.ndimage import uniform_filter
from scipy.signal import butter, istft, sosfilt, sosfiltfilt, stft
from scipy.special import expi


NoiseEstimationMode = Literal["dynamic", "fixed_lead_in", "off"]


@dataclass(frozen=True)
class EnhancementSettings:
    """Conservative defaults intended to avoid aggressive speech distortion.

    ``noise_estimation`` selects the noise-reduction strategy. ``dynamic`` is the
    recommended default: it adapts to recordings that begin with speech.
    """

    highpass_hz: float = 80.0
    # Sub-sonic DC-block corner (Hz). Runs as the very first step to remove ADC/mic offset
    # that would otherwise bias RMS, pitch, and spectral analysis. 10 Hz is the brief's value.
    dc_block_hz: float = 10.0
    # When True, the high-pass cutoff is derived from the signal's estimated fundamental
    # frequency (cutoff just below F0) instead of the fixed ``highpass_hz``. Pure-DSP
    # autocorrelation F0 estimate, no ML, no librosa. Falls back to ``highpass_hz`` when no
    # pitch can be confidently estimated.
    adaptive_highpass: bool = True
    # Hard ceiling on the adaptive high-pass cutoff (Hz). The corner can NEVER exceed this,
    # so the 100-160 Hz chest/body of the voice is never attenuated. Gemini's refinement:
    # a detected F0 of 214 Hz used to cut at 171 Hz (thin/telephone sound); clamping to 95 Hz
    # preserves vocal warmth.
    adaptive_highpass_max_hz: float = 95.0

    noise_estimation: NoiseEstimationMode = "dynamic"

    # --- fixed_lead_in strategy (legacy) ---
    noise_profile_seconds: float = 0.25
    noise_overestimate: float = 1.25
    # --- non-stationary vs stationary noisereduce ---
    # `stationary=True` uses a single noise profile (built from the signal's quietest
    # regions) and only removes *steady* hiss/hum -- it leaves speech transients intact,
    # which is what keeps the voice natural (non-stationary full subtraction at
    # prop_decrease=1.0 is the classic cause of a "robotic"/metallic voice because it
    # chops off the fast spectral movement that makes speech sound alive).
    nr_stationary: bool = True
    # Fraction of reduction applied (0..1). 1.0 = full subtraction (robotic); ~0.5-0.7
    # removes the floor while preserving consonant/breath detail and vocal body.
    nr_prop_decrease: float = 0.6
    # Minimum speech-to-floor energy separation (dB) required to engage noise reduction.
    # When the clip has no genuine quiet gaps (e.g. an already-mastered, near-clipped
    # recording) the "silence" frames are still speech-level, so subtracting them only
    # eats transients and sounds robotic. Below this gap we skip NR entirely (fast path
    # + no artifact). Fully signal-derived -- no hardcoded noise floor.
    nr_min_separation_db: float = 3.0
    # The quietest frames must also be *noise-like* (broadband / flat spectrum), not just
    # lower-energy -- otherwise a pure tone's peak/trough swing would be mistaken for
    # speech-vs-noise and NR would mangle a clean tonal signal. Flatness in [0,1]; real
    # hiss sits well above this, tonal content well below.
    nr_min_noise_flatness: float = 0.2

    # --- dynamic / VAD strategy ---
    # Speech is declared when frame energy exceeds the running noise energy by at least
    # this many dB AND the spectral flatness is below the flatness threshold.
    vad_speech_gate_db: float = 3.0
    vad_flatness_threshold: float = 0.7
    # Hang-over / onset smoothing in STFT frames to avoid speech/silence flicker.
    vad_hangover_frames: int = 4
    vad_onset_frames: int = 1
    # Exponential moving-average rate for the per-band noise PSD on silence frames.
    noise_adapt_rate: float = 0.05

    # --- MMSE-STSA gain ---
    # Decision-directed smoothing of the a priori SNR (0.98 is the classic value).
    dd_alpha: float = 0.98
    # Hard floor on attenuation so musical-noise / breath is not over-suppressed.
    maximum_attenuation_db: float = 18.0

    # --- dynamics ---
    compressor_threshold_dbfs: float = -14.0
    compressor_ratio: float = 2.0
    target_rms_dbfs: float = -20.0
    maximum_makeup_db: float = 8.0
    true_peak_ceiling_dbfs: float = -1.0
    # When False, only spectral noise reduction (and high-pass) runs; the broadband
    # compressor / RMS make-up / limiter are skipped. Used by the combined pipeline so
    # the mastering stage owns all loudness and dynamics decisions.
    enable_dynamics: bool = True


@dataclass(frozen=True)
class EnhancementReport:
    """Observable processing facts, not perceptual-quality or intelligibility claims."""

    input_rms_dbfs: float
    output_rms_dbfs: float
    input_peak_dbfs: float
    output_peak_dbfs: float
    clipping_samples_before: int
    clipping_samples_after: int
    noise_estimation: str
    # When dynamic: fraction of STFT frames classified as speech (0..1).
    vad_speech_ratio: float
    # Estimated noise floor in dBFS (median of the tracked per-band noise PSD).
    estimated_noise_floor_dbfs: float
    # When fixed_lead_in: seconds of lead-in consumed as the noise estimate.
    used_noise_profile_seconds: float
    # Detected fundamental frequency (Hz) used to set the adaptive high-pass cutoff, or None
    # when the cutoff fell back to ``highpass_hz`` (no confident pitch estimate).
    detected_f0_hz: float | None = None
    # True when spectral noise reduction actually engaged (a usable noise floor was found
    # by the VAD and applied). False when the signal had no silence / no reliable noise.
    noise_reduced: bool = False


def _dbfs(value: float) -> float:
    return 20.0 * float(np.log10(max(value, 1e-12)))


def _dc_block(channel: np.ndarray, sample_rate: int, cutoff_hz: float = 10.0) -> np.ndarray:
    """2nd-order Butterworth high-pass at ~10 Hz to strip DC / sub-sonic ADC offset.

    Runs as the very first step so that RMS loudness, pitch tracking, and the spectral
    gate are not biased by a non-zero zero-point (microphone rumble / converter offset).
    Zero-phase (sosfiltfilt) so no group-delay skew is introduced before analysis.
    """

    if cutoff_hz <= 0 or cutoff_hz >= sample_rate / 2 or len(channel) < 16:
        return channel.copy()
    sos = butter(2, cutoff_hz, btype="highpass", fs=sample_rate, output="sos")
    try:
        return sosfiltfilt(sos, channel).astype(np.float32)
    except ValueError:
        return sosfilt(sos, channel).astype(np.float32)


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


def _estimate_f0_track(channel: np.ndarray, sample_rate: int) -> list[float]:
    """Per-frame F0 of voiced regions, via short-window autocorrelation.

    Returns a list of estimated fundamental frequencies (Hz) for frames that are voiced,
    so a caller can take the lowest percentile (true chest register) rather than an average
    skewed by higher inflections / harmonics. Frames with no confident pitch are skipped.
    Pure DSP, no ML, no librosa.
    """

    if len(channel) < sample_rate // 10 or not np.isfinite(channel).all():
        return []
    frame = max(256, int(0.04 * sample_rate))   # ~40 ms windows for a stable per-frame F0
    hop = frame // 2
    if len(channel) < frame:
        return []
    f0s: list[float] = []
    min_lag = max(2, int(sample_rate / 400.0))
    max_lag = min(frame - 1, int(sample_rate / 60.0))
    if max_lag <= min_lag:
        return []
    for start in range(0, len(channel) - frame + 1, hop):
        seg = channel[start:start + frame]
        seg = seg - np.mean(seg)
        energy = float(np.dot(seg, seg))
        if energy < 1e-10:
            continue
        n = len(seg)
        fft = np.fft.rfft(seg, n=2 * n)
        ac = np.fft.irfft(fft * np.conjugate(fft))[:n]
        ac = ac / (energy + 1e-12)
        region = ac[min_lag:max_lag]
        peak = min_lag + int(np.argmax(region))
        if ac[peak] >= 0.4:   # periodic enough to count as voiced (rejects white-noise spikes)
            f0s.append(sample_rate / peak)
    return f0s


def _high_pass_cutoff(channel: np.ndarray, sample_rate: int, settings: EnhancementSettings) -> tuple[float, float | None]:
    """Resolve the high-pass cutoff, deriving it from the signal F0 when adaptive is on.

    Protects chest warmth: track F0 across voiced frames and take the *5th percentile*
    (lowest true chest frequency), not a mean skewed by higher inflections or harmonics.
    The corner is then hard-clamped so it can never exceed ``adaptive_highpass_max_hz``
    (default 95 Hz) -- the 100-160 Hz voice body is never attenuated.
    """

    if not settings.adaptive_highpass:
        return settings.highpass_hz, None
    f0s = _estimate_f0_track(channel, sample_rate)
    if not f0s:
        return settings.highpass_hz, None
    chest_f0 = float(np.percentile(f0s, 5.0))   # lowest true chest register
    cutoff = float(min(settings.adaptive_highpass_max_hz, chest_f0 * 0.8))
    detected = float(np.median(f0s))   # report median pitch for observability
    return cutoff, detected


# Retained for direct single-window F0 estimation (used by tests / fallback).
def _estimate_f0(channel: np.ndarray, sample_rate: int) -> float | None:
    """Single-window F0 estimate (autocorrelation). See ``_estimate_f0_track`` for the
    per-frame variant used by the adaptive high-pass. Returns None when unpitched."""

    if len(channel) < sample_rate // 10 or not np.isfinite(channel).all():
        return None
    window = channel[: min(len(channel), sample_rate)]
    x = window - np.mean(window)
    energy = float(np.dot(x, x))
    if energy < 1e-10:
        return None
    n = len(x)
    fft = np.fft.rfft(x, n=2 * n)
    ac = np.fft.irfft(fft * np.conjugate(fft))[:n]
    ac = ac / (energy + 1e-12)
    min_lag = max(2, int(sample_rate / 400.0))
    max_lag = min(n - 1, int(sample_rate / 60.0))
    if max_lag <= min_lag:
        return None
    region = ac[min_lag:max_lag]
    local_max = min_lag + int(np.argmax(region))
    if ac[local_max] < 0.3:
        return None
    return float(sample_rate / local_max)


def _as_channel_matrix(samples: np.ndarray) -> tuple[np.ndarray, bool]:
    array = np.asarray(samples, dtype=np.float32)
    if array.ndim == 1:
        return array[:, None], True
    if array.ndim == 2 and array.shape[1] >= 1:
        return array, False
    raise ValueError("samples must be a mono vector or an (samples, channels) array")


def _high_pass(channel: np.ndarray, sample_rate: int, cutoff_hz: float) -> np.ndarray:
    if cutoff_hz <= 0 or cutoff_hz >= sample_rate / 2 or len(channel) < 16:
        return channel.copy()
    sos = butter(2, cutoff_hz, btype="highpass", fs=sample_rate, output="sos")
    # Zero-phase filtering avoids audible phase displacement where there is enough context.
    try:
        return sosfiltfilt(sos, channel).astype(np.float32)
    except ValueError:
        return sosfilt(sos, channel).astype(np.float32)


# ---------------------------------------------------------------------------
# Voice Activity Detection + dynamic noise PSD
# ---------------------------------------------------------------------------
def _detect_speech_and_noise_psd(
    magnitude: np.ndarray, settings: EnhancementSettings
) -> tuple[np.ndarray, np.ndarray]:
    """Segment speech/silence and track a per-band noise PSD that adapts on silence only.

    Parameters
    ----------
    magnitude : (freq_bins, frames) STFT magnitude.

    Returns
    -------
    is_speech : (frames,) bool
    noise_psd : (freq_bins, frames) noise power spectral density per frame
    """

    freq_bins, frames = magnitude.shape
    power = magnitude ** 2

    # Per-frame total energy (use log domain for the gate comparison).
    frame_energy = np.sum(power, axis=0)
    log_energy = np.log10(frame_energy + 1e-12)

    # Spectral flatness: geometric mean / arithmetic mean of the magnitude spectrum.
    # Tonal (speech/harmonic) frames are low; flat (noise/hiss) frames approach 1.
    geo = np.exp(np.mean(np.log(magnitude + 1e-12), axis=0))
    ari = np.mean(magnitude + 1e-12, axis=0)
    flatness = np.clip(geo / (ari + 1e-12), 0.0, 1.0)

    gate_lin = 10.0 ** (settings.vad_speech_gate_db / 10.0)
    # Seed the noise-energy estimate from the quietest frames (a robust noise-floor proxy),
    # NOT the median across all frames -- the median is dominated by speech bursts and would
    # inflate the floor. The 10th percentile reliably lands in genuine silence on speech audio.
    noise_energy_log = float(np.quantile(log_energy, 0.10))

    raw_speech = np.zeros(frames, dtype=bool)
    for n in range(frames):
        speech_like = (frame_energy[n] > (10.0 ** noise_energy_log) * gate_lin) and (
            flatness[n] < settings.vad_flatness_threshold
        )
        raw_speech[n] = speech_like
        if not speech_like:
            # Update the running noise-energy estimate only on non-speech.
            noise_energy_log = (
                1.0 - settings.noise_adapt_rate
            ) * noise_energy_log + settings.noise_adapt_rate * log_energy[n]

    # Onset / hang-over smoothing so short gaps inside words are not treated as silence
    # and single-frame false alarms are ignored.
    is_speech = _smooth_labels(
        raw_speech, onset=settings.vad_onset_frames, hangover=settings.vad_hangover_frames
    )

    silence = ~is_speech
    if not silence.any():
        # No silence detected anywhere -> no reliable noise estimate. The caller passes the
        # signal through unchanged rather than guessing a noise floor from the speech itself.
        return is_speech, None

    # Per-band noise PSD: seed from the median of the quietest frames (robust silence proxy,
    # not contaminated by speech bursts), then EMA-update only on silence frames so it tracks
    # drifting ambient noise without being contaminated by speech.
    quiet_order = np.argsort(frame_energy)
    quiet_k = max(1, int(0.10 * frames))
    quiet_idx = quiet_order[:quiet_k]
    current_psd = np.median(power[:, quiet_idx], axis=1)
    rho = settings.noise_adapt_rate
    noise_psd = np.empty((freq_bins, frames), dtype=np.float64)
    for n in range(frames):
        if not is_speech[n]:
            current_psd = (1.0 - rho) * current_psd + rho * power[:, n]
        noise_psd[:, n] = current_psd
    return is_speech, noise_psd


def _smooth_labels(labels: np.ndarray, onset: int, hangover: int) -> np.ndarray:
    out = labels.copy()
    frames = len(labels)
    run = 0
    for n in range(frames):
        if labels[n]:
            run += 1
            if run >= onset:
                out[n] = True
        else:
            run = 0
    # Hang-over: extend a trailing speech run backwards.
    if hangover > 0:
        n = frames - 1
        while n >= 0 and labels[n]:
            n -= 1
        # n is now the last silence index before the final speech run (or -1)
        start = n + 1
        for k in range(max(0, start - hangover), start):
            out[k] = True
    return out


# ---------------------------------------------------------------------------
# Spectral reduction strategies
# ---------------------------------------------------------------------------
def _mmse_stsa_gain(posteriori: np.ndarray, apriori: np.ndarray, floor: float) -> np.ndarray:
    """Ephraim-Malah MMSE-STSA gain, G = (xi/(1+xi)) * exp(0.5 * E1(gamma/(1+xi))).

    E1(x) = -expi(-x) for x > 0 (scipy.special.expi is Ei).
    """

    denom = 1.0 + apriori
    with np.errstate(divide="ignore", invalid="ignore"):
        arg = posteriori / denom
        gain = (apriori / denom) * np.exp(-0.5 * expi(-arg))
    gain = np.nan_to_num(gain, nan=floor, posinf=1.0, neginf=floor)
    return np.clip(gain, floor, 4.0)


def _extract_noise_clip(
    channel: np.ndarray, sample_rate: int, fraction: float = 0.1, win_ms: float = 20.0
) -> np.ndarray | None:
    """Build a time-domain noise profile from the quietest ``fraction`` of the signal.

    Splits the signal into short windows, ranks them by energy, and concatenates the
    lowest-energy windows into a single clip. This is fully signal-derived -- no hardcoded
    floor -- and matches ``noisereduce``'s stationary-mode ``noise_clip`` contract. Returns
    ``None`` when the clip is too short to be useful.
    """
    win = max(256, int(win_ms / 1000.0 * sample_rate))
    if len(channel) < win * 4:
        return None
    n = len(channel)
    hops = max(1, win // 2)
    n_win = max(1, (n - win) // hops + 1)
    energies = np.empty(n_win, dtype=np.float64)
    for i in range(n_win):
        seg = channel[i * hops: i * hops + win]
        energies[i] = float(np.sum(seg ** 2))
    order = np.argsort(energies)
    keep = max(1, int(round(n_win * fraction)))
    idx = np.sort(order[:keep])
    chunks = [channel[i * hops: i * hops + win].astype(np.float32) for i in idx]
    clip = np.concatenate(chunks) if chunks else None
    if clip is None or clip.size < win:
        return None
    return clip


def _enhance_dynamic(
    channel: np.ndarray, sample_rate: int, settings: EnhancementSettings
) -> dict:
    """Adaptive spectral noise gate via ``noisereduce`` (no ML).

    Our VAD decides *whether* a usable noise floor exists (and feeds the report / pipeline
    guard). The actual suppression is delegated to ``noisereduce.reduce_noise`` -- the
    battle-tested OSS spectral-gating implementation.

    To keep the voice *natural* (not robotic) we run it in **stationary** mode against a
    noise profile built from the signal's own quietest regions, with a gentle
    ``prop_decrease`` (~0.7). Full non-stationary subtraction at ``prop_decrease=1.0`` is
    the textbook cause of a metallic/robotic voice: it re-estimates a mask every frame and
    shaves off the speech transients (consonants, breaths, word attacks) that make speech
    sound alive. Stationary + gentle keeps the floor down while preserving the vocal body.
    """
    is_speech, _ = _detect_speech_and_noise_psd(np.abs(stft(channel, fs=sample_rate, nperseg=512, noverlap=256, boundary="zeros", padded=True)[2]), settings)
    speech_ratio = float(np.mean(is_speech)) if is_speech is not None else 0.0

    # Adaptive engagement gate (no hardcoded floor): only run NR when there is a *real*
    # gap between the speech energy and the quietest (silence) energy. On an already
    # finished / near-clipped recording the "silence" frames are still speech-level, so
    # subtracting them only eats transients and sounds robotic -- and wastes CPU. When
    # the separation is below `nr_min_separation_db` (or there is essentially no silence)
    # we skip NR entirely and pass the spectral content through (high-pass still applies).
    def _rms_db(x: np.ndarray) -> float:
        return _dbfs(float(np.sqrt(np.mean(x ** 2)))) if x.size else -np.inf

    # is_speech is per-STFT-frame, not per-sample; derive the separation from frame energies.
    _, _, _spec = stft(channel, fs=sample_rate, nperseg=512, noverlap=256, boundary="zeros", padded=True)
    _mag = np.abs(_spec)
    _frame_e = np.sum(_mag ** 2, axis=0)
    # Spectral flatness per frame: geometric / arithmetic mean of the magnitude spectrum.
    # Real broadband noise (hiss/hum) is flat (~0.3-1.0); a tone's troughs are still tonal
    # (~0). A naive energy gap can mistake a pure tone's peak/trough swing for "speech vs
    # noise", so we additionally require the *quiet* frames to actually be noise-like.
    _geo = np.exp(np.mean(np.log(_mag + 1e-12), axis=0))
    _ari = np.mean(_mag + 1e-12, axis=0)
    _flat = np.clip(_geo / (_ari + 1e-12), 0.0, 1.0)
    silence = (~is_speech) if is_speech is not None else None
    if silence is not None and silence.any():
        sep_db = _rms_db(np.sqrt(_frame_e[is_speech])) - _rms_db(np.sqrt(_frame_e[silence]))
        quiet_flatness = float(np.mean(_flat[silence]))
    else:
        sep_db = 0.0  # no silence detected -> treat as "no usable floor"
        quiet_flatness = 0.0
    # Engage only when there is a genuine, noise-like quiet floor well below the program
    # level. Otherwise subtracting it only eats transients (robotic) and wastes CPU.
    engage_nr = (
        (sep_db >= settings.nr_min_separation_db)
        and (quiet_flatness >= settings.nr_min_noise_flatness)
        and (speech_ratio < 0.995)
    )

    # If the VAD found no usable silence / no real noise gap, there is no reliable noise
    # profile to gate against; pass the signal through untouched (high-pass already applied
    # by the caller). A needless STFT/ISTFT round-trip here can inject reconstruction artifacts
    # on tonal content, so we return the channel directly.
    if not engage_nr:
        return {
            "signal": channel.astype(np.float32, copy=False),
            "speech_ratio": speech_ratio,
            "noise_floor_dbfs": _rms_db(np.sqrt(_frame_e[silence])) if (silence is not None and silence.any()) else -np.inf,
            "profile_seconds": 0.0,
            "noise_reduced": False,
        }

    from noisereduce import reduce_noise
    # noisereduce internally reshapes the signal into (n_fft, -1) blocks, so the length
    # MUST be a multiple of n_fft; pad with zeros (and trim after) to guarantee that.
    n_fft = 2048
    pad = (-len(channel)) % n_fft
    padded = np.concatenate([channel.astype(np.float32), np.zeros(pad, dtype=np.float32)]) if pad else channel.astype(np.float32)
    noise_clip = _extract_noise_clip(padded, sample_rate, fraction=0.1)
    try:
        reduced = reduce_noise(
            y=padded,
            sr=sample_rate,
            stationary=settings.nr_stationary,
            prop_decrease=settings.nr_prop_decrease,
            n_std_thresh_stationary=max(0.5, settings.noise_overestimate),
            n_fft=n_fft,
            n_jobs=1,
            **({"noise_clip": noise_clip} if (settings.nr_stationary and noise_clip is not None) else {}),
        )
    except Exception:
        # noisereduce can reject odd lengths / edge cases; fall back to the untouched
        # spectral content (high-pass + dynamics still apply downstream).
        reduced = padded
    reduced = reduced[: len(channel)]
    # Estimate the residual noise floor for reporting (quietest 10% of frames).
    from scipy.signal import stft as _stft
    _, _, spec = _stft(reduced, fs=sample_rate, nperseg=512, noverlap=256, boundary="zeros", padded=True)
    mag = np.abs(spec)
    frame_energy = np.sum(mag ** 2, axis=0)
    est_floor = _dbfs(float(np.sqrt(np.quantile(frame_energy, 0.10)))) if frame_energy.size else -np.inf
    return {
        "signal": reduced.astype(np.float32, copy=False),
        "speech_ratio": speech_ratio,
        "noise_floor_dbfs": est_floor,
        "profile_seconds": 0.0,
        "noise_reduced": True,
    }


def _enhance_fixed_lead_in(
    channel: np.ndarray, sample_rate: int, settings: EnhancementSettings
) -> tuple[np.ndarray, float]:
    """Legacy stationary-noise gate from an assumed noise lead-in (original behaviour)."""

    if settings.noise_profile_seconds <= 0 or len(channel) < 256:
        return {"signal": channel.copy(), "speech_ratio": 0.0, "noise_floor_dbfs": -np.inf,
                "profile_seconds": 0.0, "noise_reduced": False}
    nperseg = min(1024 if sample_rate >= 24_000 else 512, max(128, len(channel) // 4))
    noverlap = nperseg // 2
    _, _, spectrum = stft(
        channel, fs=sample_rate, nperseg=nperseg, noverlap=noverlap, boundary="zeros", padded=True
    )
    magnitude = np.abs(spectrum)
    profile_frames = max(
        1, min(magnitude.shape[1], int(np.ceil(settings.noise_profile_seconds * sample_rate / (nperseg - noverlap))))
    )
    noise = np.median(magnitude[:, :profile_frames], axis=1, keepdims=True)
    threshold = settings.noise_overestimate * noise
    floor = 10.0 ** (-settings.maximum_attenuation_db / 20.0)
    gain = np.maximum(floor, 1.0 - threshold / (magnitude + 1e-10))
    gain = uniform_filter(gain, size=(3, 2), mode="nearest")
    _, restored = istft(
        spectrum * gain, fs=sample_rate, nperseg=nperseg, noverlap=noverlap, input_onesided=True, boundary=True
    )
    est_floor = _dbfs(float(np.sqrt(np.median(noise ** 2))))
    return {
        "signal": restored[: len(channel)].astype(np.float32, copy=False),
        "speech_ratio": 0.0,
        "noise_floor_dbfs": est_floor,
        "profile_seconds": min(settings.noise_profile_seconds, len(channel) / sample_rate),
        "noise_reduced": True,
    }


def _spectral_enhance(
    channel: np.ndarray, sample_rate: int, settings: EnhancementSettings
) -> dict:
    if settings.noise_estimation == "off":
        return {"signal": channel.copy(), "speech_ratio": 0.0, "noise_floor_dbfs": -np.inf,
                "profile_seconds": 0.0, "noise_reduced": False}
    if settings.noise_estimation == "fixed_lead_in":
        return _enhance_fixed_lead_in(channel, sample_rate, settings)
    return _enhance_dynamic(channel, sample_rate, settings)


# ---------------------------------------------------------------------------
# Dynamics: compressor + make-up + limiter
# ---------------------------------------------------------------------------
def _compress_and_make_up(channel: np.ndarray, settings: EnhancementSettings) -> np.ndarray:
    threshold = 10.0 ** (settings.compressor_threshold_dbfs / 20.0)
    magnitude = np.abs(channel)
    level_db = 20.0 * np.log10(np.maximum(magnitude, 1e-12))
    over_db = np.maximum(level_db - settings.compressor_threshold_dbfs, 0.0)
    reduction_db = over_db * (1.0 - 1.0 / settings.compressor_ratio)
    compressed = channel * (10.0 ** (-reduction_db / 20.0)).astype(np.float32)
    current_rms = _rms(compressed)
    target_rms = 10.0 ** (settings.target_rms_dbfs / 20.0)
    if current_rms > 1e-9:
        makeup = min(target_rms / current_rms, 10.0 ** (settings.maximum_makeup_db / 20.0))
        compressed = compressed * makeup
    ceiling = 10.0 ** (settings.true_peak_ceiling_dbfs / 20.0)
    return np.clip(compressed, -ceiling, ceiling).astype(np.float32)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def enhance_voice(
    samples: np.ndarray,
    sample_rate: int,
    settings: EnhancementSettings = EnhancementSettings(),
) -> tuple[np.ndarray, EnhancementReport]:
    """Enhance a float PCM waveform while preserving duration and channel count.

    Inputs must be finite float-like PCM values in the customary ``[-1, 1]`` range.
    Processing preserves stereo channels but estimates the noise profile independently per
    channel.
    """

    if sample_rate < 8_000:
        raise ValueError("sample_rate must be at least 8000 Hz")
    matrix, was_mono = _as_channel_matrix(samples)
    if len(matrix) == 0 or not np.isfinite(matrix).all():
        raise ValueError("samples must be non-empty and finite")
    input_peak = float(np.max(np.abs(matrix)))
    input_rms = _rms(matrix)
    processed = np.empty_like(matrix)
    speech_ratio = 0.0
    noise_floor = -np.inf
    profile_seconds = 0.0
    noise_reduced = False
    detected_f0 = None
    for index in range(matrix.shape[1]):
        # 0. DC-block first: remove sub-sonic offset so RMS / pitch / spectral analysis
        # are unbiased (proper signal order: DC -> spectral gate -> high-pass -> ...).
        dc_blocked = _dc_block(matrix[:, index], sample_rate, settings.dc_block_hz)
        cutoff, f0 = _high_pass_cutoff(dc_blocked, sample_rate, settings)
        if f0 is not None:
            detected_f0 = f0
        high_passed = _high_pass(dc_blocked, sample_rate, cutoff)
        stats = _spectral_enhance(high_passed, sample_rate, settings)
        signal = stats["signal"]
        if settings.enable_dynamics:
            processed[:, index] = _compress_and_make_up(signal, settings)
        else:
            # Pipeline mode: leave loudness/dynamics to the mastering stage.
            processed[:, index] = signal
        speech_ratio = max(speech_ratio, stats["speech_ratio"])
        noise_floor = max(noise_floor, stats["noise_floor_dbfs"])
        profile_seconds = max(profile_seconds, stats["profile_seconds"])
        if stats.get("noise_reduced"):
            noise_reduced = True
    output_peak = float(np.max(np.abs(processed)))
    output_rms = _rms(processed)
    result = processed[:, 0] if was_mono else processed
    report = EnhancementReport(
        input_rms_dbfs=_dbfs(input_rms),
        output_rms_dbfs=_dbfs(output_rms),
        input_peak_dbfs=_dbfs(input_peak),
        output_peak_dbfs=_dbfs(output_peak),
        clipping_samples_before=int(np.count_nonzero(np.abs(matrix) >= 1.0)),
        clipping_samples_after=int(np.count_nonzero(np.abs(processed) >= 1.0)),
        noise_estimation=settings.noise_estimation,
        vad_speech_ratio=speech_ratio,
        estimated_noise_floor_dbfs=noise_floor,
        used_noise_profile_seconds=profile_seconds,
        detected_f0_hz=detected_f0,
        noise_reduced=noise_reduced,
    )
    return result, report


def enhance_wav(
    input_path: str, output_path: str, settings: EnhancementSettings = EnhancementSettings()
) -> EnhancementReport:
    """Load a libsndfile-readable input, enhance it, and write a PCM-24 WAV output."""

    samples, sample_rate = sf.read(input_path, dtype="float32", always_2d=False)
    enhanced, report = enhance_voice(samples, sample_rate, settings)
    sf.write(output_path, enhanced, sample_rate, subtype="PCM_24")
    return report


def enhance_file(
    input_path: str,
    output_path: str,
    settings: EnhancementSettings = EnhancementSettings(),
    output_bitrate: str = "320k",
) -> EnhancementReport:
    """Enhance any ffmpeg-decodable file (e.g. MP3) and write it back in the same container.

    Uses ffmpeg for I/O so the project is not limited to libsndfile's format support. Requires
    ``ffmpeg`` on PATH. The intermediate WAV is created in the system temp directory only.
    """

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required for enhance_file but was not found on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        decoded = f"{tmp}/decoded.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_path, "-acodec", "pcm_f32le", "-ar", "48000", decoded],
            check=True,
            capture_output=True,
        )
        enhanced_wav = f"{tmp}/enhanced.wav"
        report = enhance_wav(decoded, enhanced_wav, settings)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                enhanced_wav,
                "-c:a",
                "libmp3lame" if output_path.lower().endswith(".mp3") else "copy",
                "-b:a",
                output_bitrate,
                output_path,
            ],
            check=True,
            capture_output=True,
        )
    return report
