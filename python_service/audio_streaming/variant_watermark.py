"""A/B variant forensic watermarking: one codeword bit per segment, two static variants.

Why this replaces per-session just-in-time embedding
---------------------------------------------------
Per-session embedding makes every delivered byte unique, so a CDN caches nothing and the
origin pays one codec pass per listener per segment. Instead each segment is encoded twice
at ingest -- variant 0 and variant 1, distinguished only by the sign of a keyed spread
spectrum carrier. Both variants are immutable and shared by all listeners, so the CDN
serves them. Personalization becomes the *choice* of variants: a session's 64-bit codeword
selects, segment by segment, which file that listener receives. Forensic recovery reads the
sign of the carrier in each recovered segment, rebuilds the codeword, and validates CRC.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .security import derive_key
from .watermark import CODEWORD_BITS, codeword_for_id, id_from_codeword


@dataclass(frozen=True)
class VariantEvidence:
    """Forensic result for a recovered capture."""

    watermark_id: int | None
    crc_valid: bool
    bits: tuple[int, ...]
    confidence: tuple[float, ...]


def codeword_bits(watermark_id: int) -> np.ndarray:
    """Return the 64 protected bits (magic + id + CRC-16) carried by the variant choices."""

    return codeword_for_id(watermark_id)


def bit_slot_permutation(secret: bytes, asset_id: str) -> tuple[int, ...]:
    """Keyed order in which codeword bits are assigned to segment positions.

    Without this the natural order would put the 16-bit constant magic header in the first 16
    segments, so any capture shorter than that would be byte-identical for every listener and
    carry no attribution at all. A keyed permutation spreads id and CRC bits across the whole
    programme, so even a short capture yields listener-specific evidence.
    """

    material = derive_key(secret, "variant-bit-permutation-v1", asset_id, length=32)
    generator = np.random.Generator(np.random.PCG64(int.from_bytes(material, "big")))
    return tuple(int(value) for value in generator.permutation(CODEWORD_BITS))


def bit_slot_for_sequence(secret: bytes, asset_id: str, sequence: int) -> int:
    """Which codeword bit index a given segment position carries."""

    if sequence < 0:
        raise ValueError("segment sequence must not be negative")
    return bit_slot_permutation(secret, asset_id)[sequence % CODEWORD_BITS]


def variant_for_sequence(watermark_id: int, sequence: int, secret: bytes | None = None, asset_id: str | None = None) -> int:
    """Select which static variant a session receives for one segment index.

    When ``secret`` and ``asset_id`` are supplied the keyed permutation is applied; the plain
    modulo order remains available for direct codeword inspection and unit testing.
    """

    if sequence < 0:
        raise ValueError("segment sequence must not be negative")
    slot = (
        bit_slot_for_sequence(secret, asset_id, sequence)
        if secret is not None and asset_id is not None
        else sequence % CODEWORD_BITS
    )
    return int(codeword_bits(watermark_id)[slot])


class VariantWatermarker:
    """Embeds a single bit into a whole segment using a keyed overlap-add carrier.

    The carrier is derived from (asset, absolute frame index), so it is unique per asset and
    position but identical across listeners -- that is exactly what makes the two variants
    cacheable. Both channels receive the same modulation so the mark survives a stereo
    downmix, and the modulation is windowed and overlap-added to avoid frame-edge clicks.
    """

    def __init__(self, secret: bytes, asset_id: str, frame_samples: int, strength: float):
        if frame_samples % 2 != 0:
            raise ValueError("frame_samples must be even for 50% overlap-add")
        self._secret = secret
        self._asset_id = asset_id
        self._frame = frame_samples
        self._hop = frame_samples // 2
        self._strength = strength
        self._window = np.sqrt(np.hanning(frame_samples).astype(np.float32))
        self._window_norm = float(np.dot(self._window, self._window))
        self._permutation = bit_slot_permutation(secret, asset_id)

    def bit_slot(self, sequence: int) -> int:
        """Codeword bit index carried by a segment position under this asset's keyed permutation."""

        if sequence < 0:
            raise ValueError("segment sequence must not be negative")
        return self._permutation[sequence % CODEWORD_BITS]

    def variant_for(self, watermark_id: int, sequence: int) -> int:
        """The variant a session receives for one segment, honouring the keyed permutation."""

        return int(codeword_bits(watermark_id)[self.bit_slot(sequence)])

    def _carrier(self, global_frame: int) -> np.ndarray:
        material = derive_key(self._secret, "audio-variant-carrier-v1", self._asset_id, str(global_frame), length=16)
        generator = np.random.Generator(np.random.PCG64(int.from_bytes(material, "big")))
        carrier = generator.standard_normal(self._frame).astype(np.float32)
        carrier -= float(np.mean(carrier))
        scale = float(np.sqrt(np.mean(np.square(carrier), dtype=np.float64)))
        return carrier / max(scale, 1e-8)

    def _frames(self, absolute_start: int, sample_count: int) -> range:
        first = max(0, (absolute_start - self._frame + 1) // self._hop)
        last = (absolute_start + sample_count - 1) // self._hop
        return range(first, last + 1)

    def _modulation(self, absolute_start: int, sample_count: int, bit: int) -> np.ndarray:
        sign = 1.0 if bit else -1.0
        modulation = np.zeros(sample_count, dtype=np.float32)
        end = absolute_start + sample_count
        for frame_index in self._frames(absolute_start, sample_count):
            frame_start = frame_index * self._hop
            overlap_start = max(frame_start, absolute_start)
            overlap_end = min(frame_start + self._frame, end)
            if overlap_end <= overlap_start:
                continue
            local = overlap_start - absolute_start
            window_slice = slice(overlap_start - frame_start, overlap_end - frame_start)
            modulation[local : local + (overlap_end - overlap_start)] += (
                sign * self._carrier(frame_index)[window_slice] * self._window[window_slice]
            )
        return modulation

    def embed(self, segment: np.ndarray, absolute_start: int, bit: int) -> np.ndarray:
        """Return one watermarked variant of a segment shaped (samples,) or (samples, channels)."""

        if bit not in (0, 1):
            raise ValueError("variant bit must be 0 or 1")
        block = np.asarray(segment, dtype=np.float32)
        modulation = self._modulation(absolute_start, block.shape[0], bit) * self._strength
        marked = block + (modulation[:, None] if block.ndim == 2 else modulation)
        return np.clip(marked, -0.999, 0.999).astype(np.float32, copy=False)

    def _score_at(self, mono: np.ndarray, absolute_start: int) -> float:
        """Signed correlation of one aligned block against its keyed carrier."""

        end = absolute_start + mono.shape[0]
        scores: list[float] = []
        for frame_index in self._frames(absolute_start, mono.shape[0]):
            frame_start = frame_index * self._hop
            if frame_start < absolute_start or frame_start + self._frame > end:
                continue
            local = frame_start - absolute_start
            view = mono[local : local + self._frame]
            weighted = self._carrier(frame_index) * self._window
            scores.append(float(np.dot(view, weighted) / self._window_norm))
        return float(np.median(scores)) if scores else 0.0

    def detect_bit(self, segment: np.ndarray, absolute_start: int, search_offsets: bool = True) -> tuple[int, float]:
        """Correlate a recovered segment against its carrier; sign gives the bit, magnitude the confidence.

        Lossy codecs introduce an encoder delay (1024 samples for AAC) and a captured recording
        may start anywhere. Time-domain spread-spectrum correlation is alignment-sensitive -- a
        misaligned block scores ~25x weaker and its sign is unreliable -- so the detector searches
        a bounded set of leading offsets and keeps the strongest-magnitude alignment.
        """

        block = np.asarray(segment, dtype=np.float32)
        mono = np.mean(block, axis=1, dtype=np.float32) if block.ndim == 2 else block
        if not search_offsets:
            score = self._score_at(mono, absolute_start)
            return (1 if score >= 0.0 else 0), abs(score)
        best_score = 0.0
        coarse_step = max(1, self._hop // 32)
        for offset in range(0, self._frame + 1, coarse_step):
            if mono.shape[0] - offset < self._frame * 2:
                break
            score = self._score_at(mono[offset:], absolute_start)
            if abs(score) > abs(best_score):
                best_score = score
        return (1 if best_score >= 0.0 else 0), abs(best_score)

    def recover(self, segments: list[tuple[int, np.ndarray]], segment_samples: int | None = None) -> VariantEvidence:
        """Rebuild a codeword from recovered (sequence, samples) pairs and validate its CRC.

        Each segment votes on the codeword bit its position carries under the keyed permutation,
        weighted by correlation confidence, so a partial capture still contributes evidence.
        """

        votes: list[list[tuple[int, float]]] = [[] for _ in range(CODEWORD_BITS)]
        for sequence, samples in segments:
            stride = segment_samples if segment_samples is not None else samples.shape[0]
            bit, confidence = self.detect_bit(samples, sequence * stride)
            votes[self.bit_slot(sequence)].append((bit, confidence))
        bits: list[int] = []
        confidence: list[float] = []
        for slot in votes:
            if not slot:
                bits.append(0)
                confidence.append(0.0)
                continue
            weight = sum((1.0 if bit else -1.0) * value for bit, value in slot)
            bits.append(1 if weight >= 0.0 else 0)
            confidence.append(abs(weight) / len(slot))
        recovered = id_from_codeword(np.asarray(bits, dtype=np.int8))
        return VariantEvidence(
            watermark_id=recovered,
            crc_valid=recovered is not None,
            bits=tuple(bits),
            confidence=tuple(confidence),
        )
