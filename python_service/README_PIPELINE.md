# Combined Enhance + Master Pipeline

`audio_streaming/pipeline.py` gives you **one call for any input** -- clean or noisy.
It runs the enhancer's spectral noise reduction (only when it will actually help)
and then the studio-mastering chain.

## How the auto-decision works

1. The enhancer runs in **noise-reduction-only mode** (`enable_dynamics=False`) so the
   mastering stage owns all loudness and dynamics.
2. Its dynamic VAD looks for silence frames to build a per-band noise floor.
3. A **guard** keeps the noise reduction only when the estimated floor is *meaningfully
   below the program level* (`floor <= input_rms - 6 dB`). If the VAD found no usable
   silence, or the "noise" it estimated is as loud as the content itself (e.g. uniform
   noise, already-clean loud signal), spectral reduction is skipped and only high-pass +
   mastering run. This prevents the enhancer from guessing a floor and damaging clean audio.
4. The mastering chain then applies broadcast polish regardless.

The decision is reported in `PipelineReport.noise_detected` (and the enhancer's
`estimated_noise_floor_dbfs`), so it is never hidden.

## API

```python
from audio_streaming.pipeline import enhance_and_master_file, enhance_then_master

report = enhance_and_master_file("recording.mp3", "finished.mp3")
# report.noise_detected -> True if spectral noise reduction engaged
# report.mastering        -> the MasteringReport (LUFS, true peak, etc.)

signal, report = enhance_then_master(samples_float32, sample_rate)
```

Both accept optional `EnhancementSettings` and `MasteringSettings` to override defaults.

## Notes / limits

- Same CPU-only, no-neural-model philosophy as the rest of the DSP path.
- Noise reduction here targets *additive stationary-ish* noise. Strong non-stationary
  noise (cafe, wind, keyboard) needs a learned model (DeepFilterNet/RNNoise) which is out
  of scope; for that, pre-process elsewhere or accept the classical ceiling.
- The guard's 6 dB margin is a tunable constant; if you find clean files being over- or
  under-processed, adjust it in `enhance_then_master`.
