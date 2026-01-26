from key_value.shared.errors import KeyValueOperationError


class EncryptionError(KeyValueOperationError):
    """Exception raised when encryption or decryption fails."""


class DecryptionError(EncryptionError):
    """Exception raised when decryption fails."""


class EncryptionVersionError(EncryptionError):
    """Exception raised when the encryption version is not supported."""


class CorruptedDataError(DecryptionError):
    """Exception raised when the encrypted data is corrupted."""
