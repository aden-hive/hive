"""
joserfc._rfc7518
~~~~~~~~~~~~~~~~

Cryptographic Models for Cryptographic Models for Content
Encryption per `Section 5`_.

.. _`Section 5`: https://tools.ietf.org/html/rfc7518#section-5
"""

from __future__ import annotations
import hmac
import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.primitives.ciphers.modes import GCM, CBC
from cryptography.hazmat.primitives.padding import PKCS7
from cryptography.exceptions import InvalidTag
from .._rfc7516.models import JWEEncModel
from ..errors import DecodeError
from .util import encode_int


class CBCHS2EncModel(JWEEncModel):
    # The IV used is a 128-bit value generated randomly or
    # pseudo-randomly for use in the cipher.
    iv_size = 128
    recommended = True

    def __init__(self, key_size: int, hash_type: int):
        self.name = f"A{key_size}CBC-HS{hash_type}"
        self.description = f"AES_{key_size}_CBC_HMAC_SHA_{hash_type} authenticated encryption algorithm"

        # key size in bit
        self.key_size = key_size
        # key size in byte
        self.key_len = key_size // 8

        self.cek_size = key_size * 2
        self.hash_alg = getattr(hashlib, f"sha{hash_type}")

    def _hmac(self, ciphertext: bytes, aad: bytes, iv: bytes, key: bytes) -> bytes:
        al = encode_int(len(aad) * 8, 64)
        msg = aad + iv + ciphertext + al
        d = hmac.new(key, msg, self.hash_alg).digest()
        return d[: self.key_len]

    def encrypt(self, plaintext: bytes, cek: bytes, iv: bytes, aad: bytes) -> tuple[bytes, bytes]:
        """Key Encryption with AES_CBC_HMAC_SHA2."""
        hkey = cek[: self.key_len]
        ekey = cek[self.key_len :]

        pad = PKCS7(AES.block_size).padder()
        padded_data = pad.update(plaintext) + pad.finalize()

        cipher = Cipher(AES(ekey), CBC(iv))
        enc = cipher.encryptor()
        ciphertext = enc.update(padded_data) + enc.finalize()
        tag = self._hmac(ciphertext, aad, iv, hkey)
        return ciphertext, tag

    def decrypt(self, ciphertext: bytes, tag: bytes, cek: bytes, iv: bytes, aad: bytes) -> bytes:
        """Key Decryption with AES AES_CBC_HMAC_SHA2."""
        hkey = cek[: self.key_len]
        dkey = cek[self.key_len :]

        ctag = self._hmac(ciphertext, aad, iv, hkey)
        if not hmac.compare_digest(ctag, tag):
            raise DecodeError("tag does not match")

        cipher = Cipher(AES(dkey), CBC(iv))
        d = cipher.decryptor()
        data = d.update(ciphertext) + d.finalize()
        unpad = PKCS7(AES.block_size).unpadder()
        return unpad.update(data) + unpad.finalize()


class GCMEncModel(JWEEncModel):
    # Use of an IV of size 96 bits is REQUIRED with this algorithm.
    # https://tools.ietf.org/html/rfc7518#section-5.3
    iv_size = 96
    recommended = True

    def __init__(self, key_size: int):
        self.name = f"A{key_size}GCM"
        self.description = f"AES GCM using {key_size}-bit key"
        self.key_size = key_size
        self.cek_size = key_size

    def encrypt(self, plaintext: bytes, cek: bytes, iv: bytes, aad: bytes) -> tuple[bytes, bytes]:
        """Key Encryption with AES GCM"""
        cipher = Cipher(AES(cek), GCM(iv))
        enc = cipher.encryptor()
        enc.authenticate_additional_data(aad)
        ciphertext = enc.update(plaintext) + enc.finalize()
        return ciphertext, enc.tag

    def decrypt(self, ciphertext: bytes, tag: bytes, cek: bytes, iv: bytes, aad: bytes) -> bytes:
        """Key Decryption with AES GCM"""
        cipher = Cipher(AES(cek), GCM(iv, tag))
        d = cipher.decryptor()
        d.authenticate_additional_data(aad)
        try:
            return d.update(ciphertext) + d.finalize()
        except InvalidTag as error:
            raise DecodeError(str(error))


JWE_ENC_MODELS: list[JWEEncModel] = [
    CBCHS2EncModel(128, 256),  # A128CBC-HS256
    CBCHS2EncModel(192, 384),  # A192CBC-HS384
    CBCHS2EncModel(256, 512),  # A256CBC-HS512
    GCMEncModel(128),  # A128GCM
    GCMEncModel(192),  # A192GCM
    GCMEncModel(256),  # A256GCM
]
