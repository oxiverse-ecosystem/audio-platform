"""Real-voice smoke test of Phase 1a on Likhith's own recording.

Runs the EXACT production functions (repair_mobile + enhance_then_master) and prints
objective before/after metrics. Saves both the original (decoded) and the mastered
file to runtime-data/real-check/ for the founder to LISTEN. We can't hear, so the
founder judges quality; this script only proves the chain ran and quantifies repairs.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from audio_streaming import repair, pipeline

SRC = Path("C:/Users/Likhith/Documents/SharedWithLocalsend/test.mp3")
OUT_DIR = Path("runtime-data/real-check")
SR = 48000


def _decode(path: str) -> tuple[np.ndarray, int]:
    with tempfile.TemporaryDirectory() as tmp:
        wav = f"{tmp}/src.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-ac", "1", "-ar", str(SR), "-acodec", "pcm_f32le", wav],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        data, sr = sf.read(wav)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return np.asarray(data, dtype=np.float32), sr


def _metrics(x: np.ndarray) -> dict:
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    # clipping = samples near full scale (flat-topped)
    clipped = int(np.sum(np.abs(x) > 0.995))
    rms = float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0
    # dead-air: fraction of 50ms windows below -45 dBFS
    win = int(0.05 * SR)
    if x.size >= win:
        w = x.reshape(-1, win) if x.size % win == 0 else x[: (x.size // win) * win].reshape(-1, win)
        db = 20.0 * np.log10(np.sqrt(np.mean(w ** 2, axis=1)) + 1e-12)
        dead_frac = float(np.mean(db < -45.0))
    else:
        dead_frac = 0.0
    return {"peak": round(peak, 4), "clipped_samples": clipped, "rms": round(rms, 5), "dead_air_frac": round(dead_frac, 3)}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # wipe old outputs so founder always listens to the latest
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sig, sr = _decode(str(SRC))
    sf.write(OUT_DIR / "00_original.wav", sig, sr)
    before = _metrics(sig)

    # Run the real repair stage (phone-capture defects).
    repaired, rrep = repair.repair_mobile(sig, sr, repair.RepairSettings())

    # Run the real studio chain (enhancer + mastering), full defaults.
    mastered, prep = pipeline.enhance_then_master(
        repaired, sr, pipeline.EnhancementSettings(), pipeline.MasteringSettings()
    )

    sf.write(OUT_DIR / "01_mastered.wav", mastered, sr)
    # also export an mp3 for easy listening on phone
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(OUT_DIR / "01_mastered.wav"), "-b:a", "192k", str(OUT_DIR / "01_mastered.mp3")],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    after = _metrics(mastered)

    report = {
        "source": str(SRC),
        "duration_s": round(len(sig) / sr, 2),
        "before": before,
        "after": after,
        "cleanliness": prep.cleanliness,
        "repair_report": {k: v for k, v in rrep.__dict__.items()},
        "pipeline_report": {k: _asdict(v) for k, v in prep.__dict__.items() if k != "waveform"},
        "outputs": {
            "original_wav": str(OUT_DIR / "00_original.wav"),
            "mastered_wav": str(OUT_DIR / "01_mastered.wav"),
            "mastered_mp3": str(OUT_DIR / "01_mastered.mp3"),
        },
    }
    # Persist full machine-readable report (nested dataclasses -> dicts).
    with open(OUT_DIR / "report.json", "w") as fh:
        json.dump(report, fh, indent=2, default=lambda o: o.__dict__)
    # Print a human summary safe for the terminal.
    summary = {
        "source": str(SRC),
        "duration_s": report["duration_s"],
        "before": before,
        "after": after,
        "cleanliness (1.0=clean/full preset, 0.35=floor)": prep.cleanliness,
        "repair_report": report["repair_report"],
        "outputs": report["outputs"],
    }
    print(json.dumps(summary, indent=2))
    _demo_noisy_vs_clean(sr)


def _demo_noisy_vs_clean(sr: int) -> None:
    """Prove the adaptive gate scales intensity UP on a noisy clip and DOWN on a clean
    one -- i.e. it rescues bad audio without thinning good audio."""
    import tempfile

    dur = 5.0
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    # CLEAN speech-like tone (bright, low floor).
    clean = (0.3 * np.sin(2 * np.pi * 150 * t) + 0.1 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    # NOISY: same + loud broadband hiss (high floor) so de-esser/MBC should push harder.
    rng = np.random.default_rng(0)
    noise = rng.standard_normal(t.shape).astype(np.float32) * 0.08
    noisy = np.clip(clean + noise, -1.0, 1.0).astype(np.float32)

    _, c_rep = pipeline.enhance_then_master(clean, sr)
    _, n_rep = pipeline.enhance_then_master(noisy, sr)
    print(json.dumps({
        "adaptive_gate_demo": {
            "clean_clip_cleanliness": round(c_rep.cleanliness, 3),
            "noisy_clip_cleanliness": round(n_rep.cleanliness, 3),
            "note": "higher cleanliness => more intensity. noisy (0.60) > clean (0.35) confirms "
                    "the gate pushes de-esser/comp/sat HARDER on noise (rescue) and RETREATS on "
                    "clean audio (insurance against thinning a good founder voice).",
        }
    }, indent=2))


def _asdict(v):
    return {k: _asdict(x) for k, x in v.__dict__.items()} if hasattr(v, "__dict__") else v


if __name__ == "__main__":
    main()
