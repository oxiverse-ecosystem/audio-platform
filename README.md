# Secure Audio Streaming MVP Source Package

This repository contains a Python-first source MVP for **entitlement-controlled, session-personalized HLS audio streaming** and a separate, conservative **pure-DSP mobile voice enhancement** baseline.

| Component | Source location | Purpose |
| --- | --- | --- |
| Async streaming service | `python_service/audio_streaming/` | FastAPI/ASGI APIs, HLS manifests, session capabilities, AES-128 segment encryption, stateful keyed watermark embedding, caches, worker limits, and audit persistence. |
| Watermark implementation | `python_service/audio_streaming/watermark.py` | Exact 32-bit ID codeword with header/CRC and deterministic keyed, overlap-add carrier embedding/recovery for controlled fixtures. |
| Voice enhancement | `python_service/audio_streaming/enhancer.py` | High-pass filtering, conservative stationary-noise spectral attenuation, peak compression, and limited make-up gain. |
| Tests | `python_service/tests/` | Authorization, encrypted/key delivery, token determinism, controlled recovery, boundaries, concurrency, and enhancer regression tests. |
| Operations documentation | `python_service/README.md` and `docs/research_notes.md` | Threat model, HLS encryption, deployment topology, key rotation, capacity controls, sources, and limitations. |

## Install and verify

```bash
cd python_service
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. pytest -q
uvicorn audio_streaming.app:app --host 127.0.0.1 --port 8000
```

Install `ffmpeg` and the `libsndfile` runtime through the operating-system package manager before starting the HLS server. The nested `python_service/Dockerfile` is a reference image for an external container platform; the project’s managed web preview is not positioned as high-throughput media infrastructure.

## Validation boundaries

The test suite confirms code-level behavior under controlled fixtures. It **does not** establish watermark imperceptibility, robustness to re-encoding, replay, trimming, TSM, or attack removal, nor does it report Pd/Pfa. It also does not establish voice-quality improvements such as PESQ/STOI/SI-SDR/LUFS. Earlier unsupported watermark figures are intentionally excluded.

See [the streaming README](python_service/README.md) and [the enhancer README](python_service/README_ENHANCER.md) before using the code in a production decision.
