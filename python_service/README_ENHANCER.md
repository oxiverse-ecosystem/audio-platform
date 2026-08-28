# Pure-DSP Mobile Voice Enhancement

`audio_streaming/enhancer.py` supplies a **conservative, explainable audio enhancement baseline** for mobile-recorded speech. It is standalone and does not share secrets or state with HLS personalization and watermarking. It does **not** use a neural model.

## Pipeline

1. **DC-block** — a 2nd-order Butterworth high-pass at 10 Hz strips sub-sonic ADC/mic
   offset *first*, so RMS, pitch, and spectral analysis are unbiased.
2. **High-pass** — a second-order high-pass filter (after DC-block) removes handling /
   air-conditioning rumble below the voice band. The cutoff is **derived from the signal**,
   not hardcoded: an autocorrelation F0 estimate is tracked across *all voiced frames* and the
   **5th percentile** (lowest true chest register) sets the corner just below it, hard-clamped
   to `adaptive_highpass_max_hz` (default 95 Hz) so the 100–160 Hz body is never attenuated.
   When no pitch is confidently estimated it falls back to `highpass_hz` (default 80 Hz).
2. **Spectral noise reduction** — selectable strategy via `EnhancementSettings.noise_estimation`:
   - `dynamic` (default) — a lightweight **energy + spectral-flatness Voice Activity Detector (VAD)** segments the clip into speech and silence and decides whether a usable noise floor exists. When it does, the actual noise suppression is delegated to **`noisereduce`** (stationary-mode adaptive spectral gating, pure numpy/scipy, no ML) — the battle-tested OSS implementation, which derives its noise profile entirely from the signal's quietest regions (no hardcoded floor). This adapts to recordings that begin with speech and needs no noise lead-in.
   - **Adaptive engagement (no hardcoded floor):** noise reduction only runs when the clip has a *genuine* noise floor — measured as a real speech-to-quiet energy gap (`nr_min_separation_db`, default 3 dB) **and** the quiet frames are actually noise-like (broadband / high spectral flatness, `nr_min_noise_flatness`, default 0.2). On an already-clean, near-loud, or already-mastered recording the "silence" frames are still speech-level (or tonal troughs), so the subtraction would only eat transients and sound robotic — in that case NR is skipped entirely (a fast, artifact-free passthrough). This is what keeps a finished track from being mangled.
   - When the VAD finds no silence, or the engagement gate is not met, the spectral stage passes through unchanged rather than guessing a floor.
   - `fixed_lead_in` — the legacy behaviour: one stationary noise floor estimated from the first `noise_profile_seconds` (default 0.25 s), capped spectral gate. Use only when you can guarantee a clean noise lead-in.
   - `off` — skip spectral reduction (high-pass + dynamics still apply).

3. **Minimum-statistics "air"/hiss attenuator** (`enable_air_dehiss`, default on) — a *second*, complementary noise profile that needs **no silence at all** and is **never hardcoded**. Per Martin (2001), the per-frequency-bin *temporal minimum* of a smoothed power spectrum converges to the stationary noise floor, because any band is only intermittently excited by speech. So even on a finished master with no quiet gaps, the high bins (where speech has little energy) reveal their own hiss floor as the local temporal minimum. The floor is therefore derived purely from the signal, every band independently, every run — there are no fixed noise frequencies or thresholds. We subtract it (gentle, `air_subtract_factor`, with a per-bin attenuation ceiling `air_max_attenuation_db`) **only inside the high band** (default 3.5–16 kHz, derived from `sample_rate`, not a fixed EQ list), leaving consonant body and presence untouched. Note: if the perceived "air" on a finished file is actually the **air-shelf EQ boost** (the +3.5 dB high-shelf in mastering) and not real hiss, this stage will correctly find little to subtract — tune `air_shelf_gain_db` in `MasteringSettings` to taste instead.
3. **Dynamics** — a 2:1 soft peak compressor above `compressor_threshold_dbfs` (−14 dBFS), limited loudness make-up toward `target_rms_dbfs` (−20 dBFS), and a true-peak safety limiter at `true_peak_ceiling_dbfs` (−1 dBFS).

## API

| Function | Input | Output | Intended use |
| --- | --- | --- | --- |
| `enhance_voice(samples, sample_rate, settings)` | Finite float PCM vector or `(samples, channels)` matrix | Enhanced PCM with equal duration/channels plus `EnhancementReport` | In-process processing |
| `enhance_wav(input_path, output_path, settings)` | A libsndfile-readable audio file | PCM-24 WAV plus `EnhancementReport` | Offline file enhancement |
| `enhance_file(input_path, output_path, settings, output_bitrate)` | Any ffmpeg-decodable file (e.g. MP3) | Same container (re-encoded) plus `EnhancementReport` | Offline enhancement of any format |

```python
from audio_streaming.enhancer import enhance_file, EnhancementSettings

# MP3 in, MP3 out -- no need to pre-convert.
report = enhance_file("mobile_recording.mp3", "enhanced.mp3")
print(report)
```

### Security / dependency note

`enhance_file` shells out to `ffmpeg` (must be on `PATH`) to decode and re-encode
non-WAV formats. It never passes untrusted shell strings — arguments are passed as a
list to `subprocess.run`, so there is no shell-injection surface.

## `EnhancementReport` fields

`input_rms_dbfs`, `output_rms_dbfs`, `input_peak_dbfs`, `output_peak_dbfs`,
`clipping_samples_before`, `clipping_samples_after`, `noise_estimation`,
`vad_speech_ratio` (fraction of STFT frames classified as speech when dynamic),
`estimated_noise_floor_dbfs`, and `used_noise_profile_seconds` (legacy mode).

## Important limitations

- The MMSE-STSA estimator assumes **additive stationary-ish noise** and benefits from genuine silence frames (real speech has pauses). If a clip has **no silence at all** (e.g. continuous tone or music with no gaps), the dynamic VAD finds no reliable noise estimate and the spectral stage passes through unchanged rather than guessing a floor and damaging the signal.
- Spectral flatness + energy VAD can misclassify very tonal, sustained sounds as speech. The `vad_speech_gate_db` and `vad_flatness_threshold` settings tune this.
- The `dynamic` spectral stage uses **`noisereduce`** (adaptive, non-stationary, no ML) for the actual denoising; our VAD still decides engagement. If `noisereduce` ever rejects an odd-length input it falls back to a pass-through so the pipeline never hard-fails.
- The report records only signal facts — RMS, peak, clipping count, VAD ratio, noise floor. It does not produce PESQ, STOI/ESTOI, SI-SDR, LUFS, segmental SNR, or a subjective-quality score.
