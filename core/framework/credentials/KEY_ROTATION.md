Key Rotation for EncryptedFileStorage

This document describes the `rotate_key` helper added to `EncryptedFileStorage`.

Overview

- `EncryptedFileStorage.rotate_key(new_key: bytes)` re-encrypts all stored credential files
  using the provided Fernet key. Each credential file is rewritten atomically to avoid
  partial updates.

Important notes

- The `new_key` must be a valid Fernet key (32 url-safe base64-encoded bytes).
- If you currently rely on the `HIVE_CREDENTIAL_KEY` environment variable, set the
  new value before calling `rotate_key` (or pass the raw key bytes directly).
- After successful rotation, the in-memory key is updated so subsequent operations
  use the new key.
- Rotation requires access to both the current and new keys. If the current key is
  lost, rotation cannot proceed.

Usage (example)

```python
from core.framework.credentials import EncryptedFileStorage

# Load storage (reads key from HIVE_CREDENTIAL_KEY by default)
storage = EncryptedFileStorage("~/.hive/credentials")

# Provide new key bytes (Fernet.generate_key())
new_key = b"..."

# Rotate all credential files
storage.rotate_key(new_key)
```

Adapter helper

`CredentialStoreAdapter.rotate_encryption_key(new_key: bytes)` is provided as a
convenience wrapper that delegates to the underlying storage backend if it
supports rotation.

Security

- Keep the old key until rotation completes successfully and you have backups.
- After rotation, securely retire the old key according to your key management
  policies.

