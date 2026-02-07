"""Encryption Service for Sensitive Data.

Provides AES-256-GCM encryption for data at rest and in transit.
Uses industry-standard key derivation (PBKDF2) and secure random IVs.

Usage:
    from framework.security import encrypt_value, decrypt_value

    # Encrypt sensitive data
    encrypted = encrypt_value("my-api-key", key="master-key")

    # Decrypt when needed
    original = decrypt_value(encrypted, key="master-key")
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Optional cryptography import
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logger.warning("cryptography not installed - using fallback encryption")


@dataclass
class EncryptedValue:
    """Container for encrypted data with metadata."""

    ciphertext: bytes
    nonce: bytes
    salt: bytes
    tag: str = "hive-encrypted-v1"

    def to_string(self) -> str:
        """Serialize to base64 string for storage."""
        combined = b":".join([
            self.tag.encode(),
            base64.b64encode(self.salt),
            base64.b64encode(self.nonce),
            base64.b64encode(self.ciphertext),
        ])
        return base64.b64encode(combined).decode("utf-8")

    @classmethod
    def from_string(cls, data: str) -> "EncryptedValue":
        """Deserialize from base64 string."""
        combined = base64.b64decode(data.encode("utf-8"))
        parts = combined.split(b":")
        if len(parts) != 4:
            raise ValueError("Invalid encrypted value format")

        tag = parts[0].decode()
        salt = base64.b64decode(parts[1])
        nonce = base64.b64decode(parts[2])
        ciphertext = base64.b64decode(parts[3])

        return cls(
            ciphertext=ciphertext,
            nonce=nonce,
            salt=salt,
            tag=tag,
        )


class EncryptionService:
    """AES-256-GCM encryption service.

    Uses:
    - PBKDF2 for key derivation (100k iterations)
    - Random 96-bit nonce per encryption
    - Random 128-bit salt per key derivation
    - GCM mode for authenticated encryption
    """

    NONCE_SIZE = 12  # 96 bits for GCM
    SALT_SIZE = 16  # 128 bits
    KEY_SIZE = 32  # 256 bits
    ITERATIONS = 100_000

    def __init__(self, master_key: str | bytes | None = None):
        """Initialize with optional master key.

        Args:
            master_key: Master encryption key. If not provided,
                       will look for HIVE_ENCRYPTION_KEY env var.
        """
        if master_key is None:
            master_key = os.environ.get("HIVE_ENCRYPTION_KEY")

        if master_key is None:
            # Generate ephemeral key for this session (not persistent!)
            logger.warning(
                "No encryption key provided - using ephemeral key. "
                "Set HIVE_ENCRYPTION_KEY for persistent encryption."
            )
            self._master_key = secrets.token_bytes(32)
        elif isinstance(master_key, str):
            self._master_key = master_key.encode("utf-8")
        else:
            self._master_key = master_key

    def _derive_key(self, salt: bytes) -> bytes:
        """Derive encryption key from master key using PBKDF2."""
        if CRYPTO_AVAILABLE:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=self.KEY_SIZE,
                salt=salt,
                iterations=self.ITERATIONS,
            )
            return kdf.derive(self._master_key)
        else:
            # Fallback using hashlib
            return hashlib.pbkdf2_hmac(
                "sha256",
                self._master_key,
                salt,
                self.ITERATIONS,
                dklen=self.KEY_SIZE,
            )

    def encrypt(self, plaintext: str | bytes) -> EncryptedValue:
        """Encrypt data using AES-256-GCM.

        Args:
            plaintext: Data to encrypt

        Returns:
            EncryptedValue containing ciphertext and metadata
        """
        if isinstance(plaintext, str):
            plaintext = plaintext.encode("utf-8")

        # Generate random salt and nonce
        salt = secrets.token_bytes(self.SALT_SIZE)
        nonce = secrets.token_bytes(self.NONCE_SIZE)

        # Derive key
        key = self._derive_key(salt)

        if CRYPTO_AVAILABLE:
            # Use cryptography library
            aesgcm = AESGCM(key)
            ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        else:
            # Fallback: XOR with derived key stream (less secure)
            key_stream = hashlib.sha256(key + nonce).digest()
            ciphertext = bytes(p ^ k for p, k in zip(plaintext, key_stream * (len(plaintext) // 32 + 1)))
            # Add HMAC for authentication
            mac = hmac.new(key, ciphertext, hashlib.sha256).digest()
            ciphertext = ciphertext + mac

        return EncryptedValue(
            ciphertext=ciphertext,
            nonce=nonce,
            salt=salt,
        )

    def decrypt(self, encrypted: EncryptedValue) -> bytes:
        """Decrypt data.

        Args:
            encrypted: EncryptedValue to decrypt

        Returns:
            Decrypted bytes

        Raises:
            ValueError: If decryption fails (wrong key, tampered data)
        """
        # Derive key
        key = self._derive_key(encrypted.salt)

        if CRYPTO_AVAILABLE:
            aesgcm = AESGCM(key)
            try:
                plaintext = aesgcm.decrypt(
                    encrypted.nonce,
                    encrypted.ciphertext,
                    None,
                )
            except Exception as e:
                raise ValueError("Decryption failed - invalid key or corrupted data") from e
        else:
            # Fallback decryption
            if len(encrypted.ciphertext) < 32:
                raise ValueError("Invalid ciphertext")

            ciphertext = encrypted.ciphertext[:-32]
            mac = encrypted.ciphertext[-32:]

            # Verify MAC
            expected_mac = hmac.new(key, ciphertext, hashlib.sha256).digest()
            if not hmac.compare_digest(mac, expected_mac):
                raise ValueError("Decryption failed - data integrity check failed")

            # Decrypt
            key_stream = hashlib.sha256(key + encrypted.nonce).digest()
            plaintext = bytes(c ^ k for c, k in zip(ciphertext, key_stream * (len(ciphertext) // 32 + 1)))

        return plaintext

    def encrypt_string(self, plaintext: str) -> str:
        """Encrypt string and return as base64 string."""
        encrypted = self.encrypt(plaintext)
        return encrypted.to_string()

    def decrypt_string(self, encrypted_string: str) -> str:
        """Decrypt base64 string back to original string."""
        encrypted = EncryptedValue.from_string(encrypted_string)
        return self.decrypt(encrypted).decode("utf-8")


# Global instance
_encryption_service: EncryptionService | None = None


def get_encryption_service() -> EncryptionService:
    """Get global encryption service instance."""
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    return _encryption_service


def encrypt_value(value: str | bytes, key: str | None = None) -> str:
    """Encrypt a value and return as string.

    Args:
        value: Value to encrypt
        key: Optional encryption key (uses global key if not provided)

    Returns:
        Encrypted value as base64 string
    """
    if key:
        service = EncryptionService(key)
    else:
        service = get_encryption_service()

    return service.encrypt_string(value if isinstance(value, str) else value.decode())


def decrypt_value(encrypted: str, key: str | None = None) -> str:
    """Decrypt a value.

    Args:
        encrypted: Encrypted string from encrypt_value
        key: Optional encryption key (uses global key if not provided)

    Returns:
        Decrypted string
    """
    if key:
        service = EncryptionService(key)
    else:
        service = get_encryption_service()

    return service.decrypt_string(encrypted)


def hash_value(value: str, salt: str | None = None) -> str:
    """Create a secure hash of a value (one-way).

    Uses SHA-256 with optional salt. Suitable for:
    - Password hashing (use with salt)
    - Data integrity verification
    - Deduplication keys

    Args:
        value: Value to hash
        salt: Optional salt for security

    Returns:
        Hex-encoded hash
    """
    if salt:
        value = salt + value

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "EncryptionService",
    "EncryptedValue",
    "encrypt_value",
    "decrypt_value",
    "hash_value",
    "get_encryption_service",
]
