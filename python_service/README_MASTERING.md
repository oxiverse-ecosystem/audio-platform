# Studio Mastering Chain (CPU-only, no neural models)

`audio_streaming/mastering.py` targets **studio POLISH** for already-usable voice:
making a clean recording sound broadcast-professional using only classical DSP. Every
stage is a documented, parameterised transform — nothing is a black box, and it runs
fully on CPU with only numpy/scipy.

## What this is, and what it is NOT

- **IS:** EQ, de-essing, multiband compression, tape-style saturation, LUFS loudness
  normalisation, and true-peak limiting. It makes a good recording sound finished.
- **IS NOT:** studio *isolation*. It does **not** remove room reverberation, separate a
  voice from background noise, or turn a bad/echoey capture into a dry studio voice. That
  class of problem needs a learned model (DeepFilterNet, RNNoise) which is intentionally
  out of scope here. For noisy/echoey source, run the noise reducer in `enhancer.py`
  first, then polish with this module.

## Signal chain (per channel)

The chain runs in this strict order so artifact interactions cancel instead of compound:

1. **DC-block** (10 Hz) — removes sub-sonic offset (enhancer, first step).
2. **Adaptive spectral gating** — `noisereduce` when the VAD finds a floor (enhancer).
3. **Adaptive high-pass** — F0-bounded, ≤95 Hz (enhancer).
4. **LTAS room-resonance notch** — 250–500 Hz standing-wave suppression (mastering).
5. **Dynamic "broadcast air" high-shelf** — 8.5 kHz, +1.5 to +3.5 dB (mastering).
6. **Adaptive de-esser** — split-band 5–8 kHz, runs *after* the air shelf so the boost
   cannot re-accentuate sibilance; threshold tracks the post-shelf sibilant RMS.
7. **Soft downward expander** — tucks pause noise toward silence (1:1.5, 50/200 ms), no
   hard-gate pumping.
8. **Adaptive RMS compression** + **tape saturation** (mastering).
9. **ITU-R BS.1770-4 normalization** (pyloudnorm) + **true-peak limiter** (mastering).

RBJ biquads (cookbook coefficients) are used throughout for tonal EQ and the notch/air
shelves — identical math to professional plugins, fully deterministic on CPU, no C++ deps.

## API

```python
from audio_streaming.mastering import master_file, MasteringSettings

report = master_file("recording.mp3", "mastered.mp3")          # default broadcast preset
report = master_file("recording.mp3", "mastered.mp3",
                     MasteringSettings(target_lufs=-14.0))      # Spotify-style
```

`master_voice(samples, sample_rate, settings)` operates in-process on float PCM.
`MasteringReport` returns `input_lufs`, `output_lufs`, `input_true_peak_dbfs`,
`output_true_peak_dbfs`, `gain_to_target_db`, `clipped_after`.

All stages are independently toggleable via `MasteringSettings` (`enable_eq`,
`enable_deesser`, `enable_mbc`, `enable_compressor`, `enable_saturation`,
`enable_loudness_match`, `enable_limiter`), so you can A/B any subset.

**Adaptive loudness (no forced normalization):** the LUFS make-up only boosts when the
source is materially quieter than the target — `loudness_match_min_gain_db` (default 3 dB)
is the minimum positive gain required before any make-up is applied. An already-broadcast-loud
recording (within 3 dB of target, or louder) is left untouched so the brickwall limiter never
clamps its transients. Forcing a finished track to a fixed −16 LUFS would push peaks into the
limiter and flatten the voice — exactly the "robotic" artifact to avoid.

**Live tuning:** the `/v1/enhance` endpoint accepts optional `enhancement` / `mastering`
override dicts (any `EnhancementSettings` / `MasteringSettings` field), so you can dial in a
gentler preset for already-mastered inputs without redeploying, e.g.
`{"mastering": {"enable_loudness_match": false, "enable_expander": false, "body_gain_db": 0.6}}`.

## References

- RBJ, "Cookbook formulae for audio EQ biquad filter coefficients".
- ITU-R BS.1770 K-weighting (stage 1 high-shelf ~1.5 kHz +4 dB; stage 2 RLB HP ~38 Hz).
- De-essing via sidechain band-pass compressor (split-band).
- Tape saturation as soft odd-harmonic waveshaper.
