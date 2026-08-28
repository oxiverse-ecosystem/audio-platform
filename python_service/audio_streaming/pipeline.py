"""One-call pipeline: noise-reduction (when needed) then studio mastering.

This ties together :mod:`audio_streaming.enhancer` and
:mod:`audio_streaming.mastering` so a caller can process *any* recording -- clean or
noisy -- with a single function. The enhancer runs in **noise-reduction-only mode**
(dynamics disabled) and only engages its spectral stage when the VAD actually finds a
usable noise floor; otherwise it passes through. The mastering stage then applies the
broadcast polish regardless. The decision is reported, not hidden.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import soundfile as sf

from .enhancer import EnhancementSettings, enhance_voice
from .mastering import MasteringReport, MasteringSettings, master_voice


@dataclass(frozen=True)
class PipelineReport:
    """Combined report from the enhance-then-master pipeline."""

    noise_detected: bool
    # Enhancer report fields (None when noise reduction was skipped).
    enhancer_noise_estimation: str
    enhancer_vad_speech_ratio: float
    enhancer_estimated_noise_floor_dbfs: float
    # Detected fundamental frequency (Hz) used for the adaptive high-pass, or None.
    enhancer_detected_f0_hz: float | None
    # Mastering report (always populated).
    mastering: MasteringReport


def enhance_then_master(
    samples: np.ndarray,
    sample_rate: int,
    enhancement: EnhancementSettings | None = None,
    mastering: MasteringSettings | None = None,
) -> tuple[np.ndarray, PipelineReport]:
    """Run noise reduction (if the VAD finds noise) then mastering.

    The enhancer is forced into ``enable_dynamics=False`` so the mastering stage owns all
    loudness and dynamics. If no usable noise floor is found, only high-pass + mastering run.
    """

    if enhancement is None:
        enhancement = EnhancementSettings()
    if mastering is None:
        mastering = MasteringSettings()
    # Pipeline contract: enhancer does spectral cleanup only; mastering does the polish.
    enhancement = EnhancementSettings(**{**enhancement.__dict__, "enable_dynamics": False})

    enhanced, enh_report = enhance_voice(samples, sample_rate, enhancement)

    # Guard: noise reduction is only kept when the VAD found a floor that is meaningfully
    # below the program level. If the "noise" it estimated is as loud as the content itself
    # (e.g. uniform noise with no real silence, or an already-clean loud signal), removing it
    # would damage the audio, so we fall back to the high-passed-only signal.
    input_rms_dbfs = 20.0 * np.log10(max(float(np.sqrt(np.mean(np.square(samples.astype(np.float64))))), 1e-12))
    noise_floor = enh_report.estimated_noise_floor_dbfs
    keep_noise_reduction = enh_report.noise_reduced and (
        np.isfinite(noise_floor) and (noise_floor <= input_rms_dbfs - 3.0)
    )
    if not keep_noise_reduction:
        # Re-run high-pass only (cheap) so the mastering stage sees consistent pre-processing.
        from .enhancer import _high_pass, _as_channel_matrix, _high_pass_cutoff

        matrix, was_mono = _as_channel_matrix(samples)
        hp = np.empty_like(matrix)
        for c in range(matrix.shape[1]):
            cutoff, _ = _high_pass_cutoff(matrix[:, c], sample_rate, enhancement)
            hp[:, c] = _high_pass(matrix[:, c], sample_rate, cutoff)
        enhanced = hp[:, 0] if was_mono else hp
        noise_detected = False
    else:
        noise_detected = True

    mastered, mas_report = master_voice(enhanced, sample_rate, mastering)

    report = PipelineReport(
        noise_detected=noise_detected,
        enhancer_noise_estimation=enh_report.noise_estimation,
        enhancer_vad_speech_ratio=enh_report.vad_speech_ratio,
        enhancer_estimated_noise_floor_dbfs=enh_report.estimated_noise_floor_dbfs,
        enhancer_detected_f0_hz=enh_report.detected_f0_hz,
        mastering=mas_report,
    )
    return mastered, report


def enhance_and_master_file(
    input_path: str,
    output_path: str,
    enhancement: EnhancementSettings | None = None,
    mastering: MasteringSettings | None = None,
    output_bitrate: str = "320k",
) -> PipelineReport:
    """Enhance-then-master any ffmpeg-decodable file to the same container. Requires ffmpeg on PATH."""

    import shutil
    import subprocess
    import tempfile

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required for enhance_and_master_file but was not found on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        decoded = f"{tmp}/decoded.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_path, "-acodec", "pcm_f32le", "-ar", "48000", decoded],
            check=True, capture_output=True,
        )
        data, sr = sf.read(decoded, dtype="float32", always_2d=False)
        mastered, report = enhance_then_master(data, sr, enhancement, mastering)
        enhanced_wav = f"{tmp}/pipeline.wav"
        sf.write(enhanced_wav, mastered, sr, subtype="PCM_24")
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", enhanced_wav,
                "-c:a", "libmp3lame" if output_path.lower().endswith(".mp3") else "copy",
                "-b:a", output_bitrate, output_path,
            ],
            check=True, capture_output=True,
        )
    return report
