"""AES-128 HLS helpers; encryption keys are deterministically derived, never stored in logs."""

from __future__ import annotations

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .security import derive_key


def segment_key(master_secret: bytes, session_id: str) -> bytes:
    return derive_key(master_secret, "hls-aes128-key-v1", session_id, length=16)


def segment_iv(session_id: str, sequence: int) -> bytes:
    if sequence < 0:
        raise ValueError("segment sequence must not be negative")
    return derive_key(b"hls-iv-public-domain-separation", "hls-aes128-iv-v1", session_id, str(sequence), length=16)


def encrypt_segment(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-128-CBC with PKCS#7 padding as specified by HLS AES-128 mode."""

    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def decrypt_segment(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    """Test-only counterpart for validating encrypted segment delivery."""

    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()

