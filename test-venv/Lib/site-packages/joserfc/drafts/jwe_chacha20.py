from __future__ import annotations
from Crypto.Cipher import ChaCha20_Poly1305
from .._rfc7516.registry import JWERegistry
from .._rfc7516.models import JWEEncModel

__all__ = ["ChaCha20EncModel", "JWE_ENC_MODELS", "register_chacha20_poly1305"]


class ChaCha20EncModel(JWEEncModel):
    # https://datatracker.ietf.org/doc/html/draft-amringer-jose-chacha-02#section-4
    cek_size = 256
    recommended = False

    def __init__(self, name: str, description: str, iv_size: int):
        self.name = name
        self.description = description
        self.iv_size = iv_size

    def encrypt(self, plaintext: bytes, cek: bytes, iv: bytes, aad: bytes) -> tuple[bytes, bytes]:
        """Key Encryption with AEAD_CHACHA20_POLY1305"""
        chacha = ChaCha20_Poly1305.new(key=cek, nonce=iv)
        chacha.update(aad)
        ciphertext, tag = chacha.encrypt_and_digest(plaintext)
        return ciphertext, tag

    def decrypt(self, ciphertext: bytes, tag: bytes, cek: bytes, iv: bytes, aad: bytes) -> bytes:
        """Key Decryption with AEAD_CHACHA20_POLY1305."""
        chacha = ChaCha20_Poly1305.new(key=cek, nonce=iv)
        chacha.update(aad)
        return chacha.decrypt_and_verify(ciphertext, tag)


C20P = ChaCha20EncModel("C20P", "ChaCha20-Poly1305", 96)
XC20P = ChaCha20EncModel("XC20P", "XChaCha20-Poly1305", 192)

JWE_ENC_MODELS = [C20P, XC20P]


def register_chacha20_poly1305() -> None:
    for model in JWE_ENC_MODELS:
        JWERegistry.register(model)
