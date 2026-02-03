"""
Storage backends for the credential store.

This module provides abstract and concrete storage implementations:
- CredentialStorage: Abstract base class
- EncryptedFileStorage: Fernet-encrypted JSON files (default for production)
- EnvVarStorage: Environment variable reading (backward compatibility)
- InMemoryStorage: For testing
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from .models import CredentialDecryptionError, CredentialKey, CredentialObject, CredentialType

logger = logging.getLogger(__name__)


class CredentialStorage(ABC):
    """
    Abstract storage backend for credentials.

    Implementations must provide save, load, delete, list_all, and exists methods.
    All implementations should handle serialization of SecretStr values securely.
    """

    @abstractmethod
    def save(self, credential: CredentialObject) -> None:
        """
        Save a credential to storage.

        Args:
            credential: The credential object to save
        """
        pass

    @abstractmethod
    def load(self, credential_id: str) -> CredentialObject | None:
        """
        Load a credential from storage.

        Args:
            credential_id: The ID of the credential to load

        Returns:
            CredentialObject if found, None otherwise
        """
        pass

    @abstractmethod
    def delete(self, credential_id: str) -> bool:
        """
        Delete a credential from storage.

        Args:
            credential_id: The ID of the credential to delete

        Returns:
            True if the credential existed and was deleted, False otherwise
        """
        pass

    @abstractmethod
    def list_all(self) -> list[str]:
        """
        List all credential IDs in storage.

        Returns:
            List of credential IDs
        """
        pass

    @abstractmethod
    def exists(self, credential_id: str) -> bool:
        """
        Check if a credential exists in storage.

        Args:
            credential_id: The ID to check

        Returns:
            True if credential exists, False otherwise
        """
        pass


class EncryptedFileStorage(CredentialStorage):
    """
    Encrypted file-based credential storage.

    Uses Fernet symmetric encryption (AES-128-CBC + HMAC) for at-rest encryption.
    Each credential is stored as a separate encrypted JSON file.

    Directory structure:
        {base_path}/
            credentials/
                {credential_id}.enc   # Encrypted credential JSON
            metadata/
                index.json            # Index of all credentials (unencrypted)

    The encryption key is read from the HIVE_CREDENTIAL_KEY environment variable.
    If not set, a new key is generated (and must be persisted for data recovery).

    Example:
        storage = EncryptedFileStorage("~/.hive/credentials")
        storage.save(credential)
        credential = storage.load("brave_search")
    """

    DEFAULT_PATH = "~/.hive/credentials"

    def __init__(
        self,
        base_path: str | Path | None = None,
        encryption_key: bytes | None = None,
        key_env_var: str = "HIVE_CREDENTIAL_KEY",
    ):
        """
        Initialize encrypted storage.

        Args:
            base_path: Directory for credential files. Defaults to ~/.hive/credentials.
            encryption_key: 32-byte Fernet key. If None, reads from env var.
            key_env_var: Environment variable containing encryption key
        """
        try:
            from cryptography.fernet import Fernet
        except ImportError as e:
            raise ImportError(
                "Encrypted storage requires 'cryptography'. Install with: pip install cryptography"
            ) from e

        self.base_path = Path(base_path or self.DEFAULT_PATH).expanduser()
        self._ensure_dirs()
        self._key_env_var = key_env_var

        # Get or generate encryption key
        if encryption_key:
            self._key = encryption_key
        else:
            key_str = os.environ.get(key_env_var)
            if key_str:
                self._key = key_str.encode()
            else:
                # Generate new key
                self._key = Fernet.generate_key()
                logger.warning(
                    f"Generated new encryption key. To persist credentials across restarts, "
                    f"set {key_env_var}={self._key.decode()}"
                )

        self._fernet = Fernet(self._key)

    def _ensure_dirs(self) -> None:
        """Create directory structure."""
        (self.base_path / "credentials").mkdir(parents=True, exist_ok=True)
        (self.base_path / "metadata").mkdir(parents=True, exist_ok=True)

    def _cred_path(self, credential_id: str) -> Path:
        """Get the file path for a credential."""
        # Sanitize credential_id to prevent path traversal
        safe_id = credential_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        return self.base_path / "credentials" / f"{safe_id}.enc"

    def save(self, credential: CredentialObject) -> None:
        """Encrypt and save credential."""
        # Serialize credential
        data = self._serialize_credential(credential)
        json_bytes = json.dumps(data, default=str).encode()

        # Encrypt
        encrypted = self._fernet.encrypt(json_bytes)

        # Write to file
        cred_path = self._cred_path(credential.id)
        with open(cred_path, "wb") as f:
            f.write(encrypted)

        # Update index
        self._update_index(credential.id, "save", credential.credential_type.value)
        logger.debug(f"Saved encrypted credential '{credential.id}'")

    def load(self, credential_id: str) -> CredentialObject | None:
        """Load and decrypt credential."""
        cred_path = self._cred_path(credential_id)
        if not cred_path.exists():
            return None

        # Read encrypted data
        with open(cred_path, "rb") as f:
            encrypted = f.read()

        # Decrypt
        try:
            json_bytes = self._fernet.decrypt(encrypted)
            data = json.loads(json_bytes.decode())
        except Exception as e:
            raise CredentialDecryptionError(
                f"Failed to decrypt credential '{credential_id}': {e}"
            ) from e

        # Deserialize
        return self._deserialize_credential(data)

    def delete(self, credential_id: str) -> bool:
        """Delete a credential file."""
        cred_path = self._cred_path(credential_id)
        if cred_path.exists():
            cred_path.unlink()
            self._update_index(credential_id, "delete")
            logger.debug(f"Deleted credential '{credential_id}'")
            return True
        return False

    def list_all(self) -> list[str]:
        """List all credential IDs."""
        index_path = self.base_path / "metadata" / "index.json"
        if not index_path.exists():
            return []
        with open(index_path) as f:
            index = json.load(f)
        return list(index.get("credentials", {}).keys())

    def exists(self, credential_id: str) -> bool:
        """Check if credential exists."""
        return self._cred_path(credential_id).exists()

    def _serialize_credential(self, credential: CredentialObject) -> dict[str, Any]:
        """Convert credential to JSON-serializable dict, extracting secret values."""
        data = credential.model_dump(mode="json")

        # Extract actual secret values from SecretStr
        for key_name, key_data in data.get("keys", {}).items():
            if "value" in key_data:
                # SecretStr serializes as "**********", need actual value
                actual_key = credential.keys.get(key_name)
                if actual_key:
                    key_data["value"] = actual_key.get_secret_value()

        return data

    def _deserialize_credential(self, data: dict[str, Any]) -> CredentialObject:
        """Reconstruct credential from dict, wrapping values in SecretStr."""
        # Convert plain values back to SecretStr
        for key_data in data.get("keys", {}).values():
            if "value" in key_data and isinstance(key_data["value"], str):
                key_data["value"] = SecretStr(key_data["value"])

        return CredentialObject.model_validate(data)

    def _update_index(
        self,
        credential_id: str,
        operation: str,
        credential_type: str | None = None,
    ) -> None:
        """Update the metadata index."""
        index_path = self.base_path / "metadata" / "index.json"

        if index_path.exists():
            with open(index_path) as f:
                index = json.load(f)
        else:
            index = {"credentials": {}, "version": "1.0"}

        if operation == "save":
            index["credentials"][credential_id] = {
                "updated_at": datetime.now(UTC).isoformat(),
                "type": credential_type,
            }
        elif operation == "delete":
            index["credentials"].pop(credential_id, None)

        index["last_modified"] = datetime.now(UTC).isoformat()

        with open(index_path, "w") as f:
            json.dump(index, f, indent=2)

    def rotate_key(
        self,
        new_key: bytes,
        validate_strength: bool = True,
    ) -> dict[str, bool]:
        """
        rotate encryption key by re-encrypting all credentials.

        this method:
        1. loads all credentials with the current key
        2. creates new encrypted files with the new key
        3. atomically replaces old files
        4. rolls back on any failure

        args:
            new_key: 44-byte base64-encoded fernet key (32 random bytes encoded)
            validate_strength: if True, validates key format

        returns:
            dict mapping credential_id to success status

        raises:
            ValueError: if new key format is invalid
            CredentialDecryptionError: if any credential cant be decrypted
        """
        from cryptography.fernet import Fernet

        # validate key format
        if validate_strength:
            if len(new_key) != 44:  # fernet keys are 44 bytes base64
                raise ValueError(
                    "invalid key length - fernet keys should be 44 bytes base64 encoded"
                )
            try:
                Fernet(new_key)  # will raise if invalid
            except Exception as e:
                raise ValueError(f"invalid fernet key: {e}") from e

        # load all credentials with current key
        cred_ids = self.list_all()
        if not cred_ids:
            logger.info("no credentials to rotate")
            return {}

        logger.info(f"starting key rotation for {len(cred_ids)} credentials")

        # first pass: load and verify all credentials can be decrypted
        credentials: list[CredentialObject] = []
        for cred_id in cred_ids:
            cred = self.load(cred_id)
            if cred is None:
                raise CredentialDecryptionError(
                    f"failed to load credential '{cred_id}' during rotation"
                )
            credentials.append(cred)

        # create backup of current files
        backup_dir = self.base_path / "credentials_backup"
        backup_dir.mkdir(exist_ok=True)

        backup_files: list[tuple[Path, Path]] = []
        for cred_id in cred_ids:
            src = self._cred_path(cred_id)
            dst = backup_dir / src.name
            if src.exists():
                import shutil

                shutil.copy2(src, dst)
                backup_files.append((src, dst))

        # switch to new key and re-encrypt
        old_key = self._key
        old_fernet = self._fernet

        try:
            self._key = new_key
            self._fernet = Fernet(new_key)

            results: dict[str, bool] = {}
            for cred in credentials:
                try:
                    self.save(cred)
                    results[cred.id] = True
                    logger.debug(f"rotated key for credential '{cred.id}'")
                except Exception as e:
                    logger.error(f"failed to rotate credential '{cred.id}': {e}")
                    results[cred.id] = False
                    raise  # will trigger rollback

            logger.info(f"key rotation complete for {len(credentials)} credentials")

            # cleanup backups on success
            for _, backup in backup_files:
                backup.unlink(missing_ok=True)
            backup_dir.rmdir()

            return results

        except Exception as e:
            # rollback: restore old key and backup files
            logger.error(f"key rotation failed, rolling back: {e}")
            self._key = old_key
            self._fernet = old_fernet

            for src, backup in backup_files:
                if backup.exists():
                    import shutil

                    shutil.copy2(backup, src)
                    backup.unlink()

            if backup_dir.exists():
                backup_dir.rmdir()

            raise


class EnvVarStorage(CredentialStorage):
    """
    Environment variable-based storage for backward compatibility.

    Maps credential IDs to environment variable patterns.
    Supports hot-reload from .env files using python-dotenv.

    This storage is READ-ONLY - credentials cannot be saved at runtime.

    Example:
        storage = EnvVarStorage(
            env_mapping={"brave_search": "BRAVE_SEARCH_API_KEY"},
            dotenv_path=Path(".env")
        )
        credential = storage.load("brave_search")
    """

    def __init__(
        self,
        env_mapping: dict[str, str] | None = None,
        dotenv_path: Path | None = None,
    ):
        """
        Initialize env var storage.

        Args:
            env_mapping: Map of credential_id -> env_var_name
                        e.g., {"brave_search": "BRAVE_SEARCH_API_KEY"}
                        If not provided, uses {CREDENTIAL_ID}_API_KEY pattern
            dotenv_path: Path to .env file for hot-reload support
        """
        self._env_mapping = env_mapping or {}
        self._dotenv_path = dotenv_path or Path.cwd() / ".env"

    def _get_env_var_name(self, credential_id: str) -> str:
        """Get the environment variable name for a credential."""
        if credential_id in self._env_mapping:
            return self._env_mapping[credential_id]
        # Default pattern: CREDENTIAL_ID_API_KEY
        return f"{credential_id.upper().replace('-', '_')}_API_KEY"

    def _read_env_value(self, env_var: str) -> str | None:
        """Read value from env var or .env file."""
        # Check os.environ first (takes precedence)
        value = os.environ.get(env_var)
        if value:
            return value

        # Fallback: read from .env file (hot-reload)
        if self._dotenv_path.exists():
            try:
                from dotenv import dotenv_values

                values = dotenv_values(self._dotenv_path)
                return values.get(env_var)
            except ImportError:
                logger.debug("python-dotenv not installed, skipping .env file")
                return None

        return None

    def save(self, credential: CredentialObject) -> None:
        """Cannot save to environment variables at runtime."""
        raise NotImplementedError(
            "EnvVarStorage is read-only. Set environment variables "
            "externally or use EncryptedFileStorage."
        )

    def load(self, credential_id: str) -> CredentialObject | None:
        """Load credential from environment variable."""
        env_var = self._get_env_var_name(credential_id)
        value = self._read_env_value(env_var)

        if not value:
            return None

        return CredentialObject(
            id=credential_id,
            credential_type=CredentialType.API_KEY,
            keys={"api_key": CredentialKey(name="api_key", value=SecretStr(value))},
            description=f"Loaded from {env_var}",
        )

    def delete(self, credential_id: str) -> bool:
        """Cannot delete environment variables at runtime."""
        raise NotImplementedError(
            "EnvVarStorage is read-only. Unset environment variables externally."
        )

    def list_all(self) -> list[str]:
        """List credentials that are available in environment."""
        available = []

        # Check mapped credentials
        for cred_id in self._env_mapping.keys():
            if self.exists(cred_id):
                available.append(cred_id)

        return available

    def exists(self, credential_id: str) -> bool:
        """Check if credential is available in environment."""
        env_var = self._get_env_var_name(credential_id)
        return self._read_env_value(env_var) is not None

    def add_mapping(self, credential_id: str, env_var: str) -> None:
        """
        Add a credential ID to environment variable mapping.

        Args:
            credential_id: The credential identifier
            env_var: The environment variable name
        """
        self._env_mapping[credential_id] = env_var


class InMemoryStorage(CredentialStorage):
    """
    In-memory storage for testing.

    Credentials are stored in a dictionary and lost when the process exits.

    Example:
        storage = InMemoryStorage()
        storage.save(credential)
        credential = storage.load("test_cred")
    """

    def __init__(self, initial_data: dict[str, CredentialObject] | None = None):
        """
        Initialize in-memory storage.

        Args:
            initial_data: Optional dict of credential_id -> CredentialObject
        """
        self._data: dict[str, CredentialObject] = initial_data or {}

    def save(self, credential: CredentialObject) -> None:
        """Save credential to memory."""
        self._data[credential.id] = credential

    def load(self, credential_id: str) -> CredentialObject | None:
        """Load credential from memory."""
        return self._data.get(credential_id)

    def delete(self, credential_id: str) -> bool:
        """Delete credential from memory."""
        if credential_id in self._data:
            del self._data[credential_id]
            return True
        return False

    def list_all(self) -> list[str]:
        """List all credential IDs."""
        return list(self._data.keys())

    def exists(self, credential_id: str) -> bool:
        """Check if credential exists."""
        return credential_id in self._data

    def clear(self) -> None:
        """Clear all credentials."""
        self._data.clear()


class CompositeStorage(CredentialStorage):
    """
    Composite storage that reads from multiple backends.

    Useful for layering storages, e.g., encrypted file with env var fallback:
    - Writes go to the primary storage
    - Reads check primary first, then fallback storages

    Example:
        storage = CompositeStorage(
            primary=EncryptedFileStorage("~/.hive/credentials"),
            fallbacks=[EnvVarStorage({"brave_search": "BRAVE_SEARCH_API_KEY"})]
        )
    """

    def __init__(
        self,
        primary: CredentialStorage,
        fallbacks: list[CredentialStorage] | None = None,
    ):
        """
        Initialize composite storage.

        Args:
            primary: Primary storage for writes and first read attempt
            fallbacks: List of fallback storages to check if primary doesn't have credential
        """
        self._primary = primary
        self._fallbacks = fallbacks or []

    def save(self, credential: CredentialObject) -> None:
        """Save to primary storage."""
        self._primary.save(credential)

    def load(self, credential_id: str) -> CredentialObject | None:
        """Load from primary, then fallbacks."""
        # Try primary first
        credential = self._primary.load(credential_id)
        if credential is not None:
            return credential

        # Try fallbacks
        for fallback in self._fallbacks:
            credential = fallback.load(credential_id)
            if credential is not None:
                return credential

        return None

    def delete(self, credential_id: str) -> bool:
        """Delete from primary storage only."""
        return self._primary.delete(credential_id)

    def list_all(self) -> list[str]:
        """List credentials from all storages."""
        all_ids = set(self._primary.list_all())
        for fallback in self._fallbacks:
            all_ids.update(fallback.list_all())
        return list(all_ids)

    def exists(self, credential_id: str) -> bool:
        """Check if credential exists in any storage."""
        if self._primary.exists(credential_id):
            return True
        return any(fallback.exists(credential_id) for fallback in self._fallbacks)
