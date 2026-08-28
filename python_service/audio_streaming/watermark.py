"""Segment-safe keyed 32-bit attribution watermark for controlled-content fingerprinting."""

from __future__ import annotations

import binascii
from dataclasses import dataclass

import numpy as np

from .config import Settings
from .security import derive_key


MAGIC = 0xA55A
CODEWORD_BITS = 64


@dataclass(frozen=True)
class WatermarkEvidence:
    watermark_id: int | None
    crc_valid: bool
    bit_scores: tuple[float, ...]


def _bytes_to_bits(value: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(value, dtype=np.uint8)).astype(np.int8)


def _bits_to_bytes(bits: np.ndarray) -> bytes:
    return np.packbits(bits.astype(np.uint8)).tobytes()


def codeword_for_id(watermark_id: int) -> np.ndarray:
    """Create 64 protected bits: 16-bit magic, 32-bit ID, and CRC-16 over the prefix."""

    if not 0 <= watermark_id <= 2**32 - 1:
        raise ValueError("watermark id must be an unsigned 32-bit integer")
    prefix = MAGIC.to_bytes(2, "big") + watermark_id.to_bytes(4, "big")
    crc = binascii.crc_hqx(prefix, 0xFFFF).to_bytes(2, "big")
    return _bytes_to_bits(prefix + crc)


def id_from_codeword(bits: np.ndarray) -> int | None:
    """Return an ID only if the fixed header and CRC both validate exactly."""

    if len(bits) != CODEWORD_BITS:
        return None
    packed = _bits_to_bytes(bits)
    prefix, supplied_crc = packed[:6], packed[6:]
    if int.from_bytes(prefix[:2], "big") != MAGIC:
        return None
    if binascii.crc_hqx(prefix, 0xFFFF).to_bytes(2, "big") != supplied_crc:
        return None
    return int.from_bytes(prefix[2:6], "big")


class SegmentSafeWatermarker:
    """A globally coordinated overlap-add keyed watermark independent of request ordering.

    HLS clients legitimately parallelize and retry segment requests. The global hop index is
    therefore the state clock: every segment is rendered from its absolute sample offset,
    yielding the same result as one sequential stateful stream with no reset at boundaries.
    """

    def __init__(self, settings: Settings, watermark_secret: bytes, asset_id: str):
        self.settings = settings
        self.asset_id = asset_id
        self._secret = watermark_secret
        self._frame = settings.frame_samples
        self._hop = settings.frame_samples // 2
        self._window = np.sqrt(np.hanning(self._frame).astype(np.float32))
        self._window_norm = float(np.dot(self._window, self._window))

    def _carrier(self, global_frame: int) -> np.ndarray:
        material = derive_key(self._secret, "audio-dsp-carrier-v1", self.asset_id, str(global_frame), length=16)
        seed = int.from_bytes(material, "big")
        carrier = np.random.Generator(np.random.PCG64(seed)).standard_normal(self._frame).astype(np.float32)
        carrier -= np.mean(carrier)
        scale = float(np.sqrt(np.mean(np.square(carrier), dtype=np.float64)))
        return carrier / max(scale, 1e-8)

    def _frame_range(self, absolute_start: int, sample_count: int) -> range:
        first = max(0, (absolute_start - self._frame + 1) // self._hop)
        last = (absolute_start + sample_count - 1) // self._hop
        return range(first, last + 1)

    def embed(self, samples: np.ndarray, watermark_id: int, absolute_start: int) -> np.ndarray:
        """Apply continuous overlap-add carrier modulation across a segment range."""

        bits = codeword_for_id(watermark_id)
        modulation = np.zeros_like(samples, dtype=np.float32)
        end = absolute_start + len(samples)
        for frame_index in self._frame_range(absolute_start, len(samples)):
            frame_start = frame_index * self._hop
            overlap_start, overlap_end = max(frame_start, absolute_start), min(frame_start + self._frame, end)
            if overlap_end <= overlap_start:
                continue
            local_start = overlap_start - absolute_start
            frame_slice = slice(overlap_start - frame_start, overlap_end - frame_start)
            sign = 1.0 if bits[frame_index % CODEWORD_BITS] else -1.0
            modulation[local_start : local_start + (overlap_end - overlap_start)] += (
                sign * self._carrier(frame_index)[frame_slice] * self._window[frame_slice]
            )
        marked = samples.astype(np.float32, copy=True) + self.settings.watermark_strength * modulation
        return np.clip(marked, -0.999, 0.999)

    def recover(self, samples: np.ndarray, absolute_start: int = 0) -> WatermarkEvidence:
        """Recover a controlled-fixture payload using all complete carrier frames in the supplied range."""

        bit_scores: list[list[float]] = [[] for _ in range(CODEWORD_BITS)]
        end = absolute_start + len(samples)
        for frame_index in self._frame_range(absolute_start, len(samples)):
            frame_start = frame_index * self._hop
            if frame_start < absolute_start or frame_start + self._frame > end:
                continue
            local_start = frame_start - absolute_start
            view = samples[local_start : local_start + self._frame]
            weighted_carrier = self._carrier(frame_index) * self._window
            score = float(np.dot(view, weighted_carrier) / self._window_norm)
            bit_scores[frame_index % CODEWORD_BITS].append(score)
        aggregate = tuple(float(np.median(scores)) if scores else 0.0 for scores in bit_scores)
        decoded_bits = np.asarray([1 if score >= 0.0 else 0 for score in aggregate], dtype=np.int8)
        recovered = id_from_codeword(decoded_bits)
        return WatermarkEvidence(watermark_id=recovered, crc_valid=recovered is not None, bit_scores=aggregate)

