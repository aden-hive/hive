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
            base_path: Directory for credential files. Defaults to
                ``$HIVE_HOME/credentials`` (per-user) when HIVE_HOME is set,
                else ``~/.hive/credentials``.
            encryption_key: 32-byte Fernet key. If None, reads from env var.
            key_env_var: Environment variable containing encryption key
        """
        try:
            from cryptography.fernet import Fernet
        except ImportError as e:
            raise ImportError(
                "Encrypted storage requires 'cryptography'. Install with: uv pip install cryptography"
            ) from e

        if base_path is None:
            # Honor HIVE_HOME (set by the desktop shell to a per-user dir) so
            # the encrypted store doesn't fork between ~/.hive and the desktop
            # userData root. Falls back to ~/.hive/credentials when standalone.
            from framework.config import HIVE_HOME

            base_path = HIVE_HOME / "credentials"
        self.base_path = Path(base_path).expanduser()
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

        # Rebuild the metadata index from disk if it's missing or older than
        # the current index schema. The index is a developer-readable JSON
        # snapshot of the encrypted store; the .enc files remain authoritative.
        try:
            self._maybe_rebuild_index()
        except Exception:
            logger.debug("Initial index rebuild failed (non-fatal)", exc_info=True)

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

        # Update developer-readable index
        self._index_upsert(credential)
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
            data = json.loads(json_bytes.decode("utf-8-sig"))
        except Exception as e:
            raise CredentialDecryptionError(f"Failed to decrypt credential '{credential_id}': {e}") from e

        # Deserialize
        return self._deserialize_credential(data)

    def delete(self, credential_id: str) -> bool:
        """Delete a credential file."""
        cred_path = self._cred_path(credential_id)
        if cred_path.exists():
            cred_path.unlink()
            self._index_remove(credential_id)
            logger.debug(f"Deleted credential '{credential_id}'")
            return True
        return False

    def list_all(self) -> list[str]:
        """List all credential IDs."""
        index_path = self.base_path / "metadata" / "index.json"
        if not index_path.exists():
            return []
        with open(index_path, encoding="utf-8-sig") as f:
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

    # ------------------------------------------------------------------
    # Developer-readable metadata index
    #
    # The index lives at ``<base_path>/metadata/index.json`` and mirrors what
    # is in the encrypted store at a glance: credential id, provider, alias,
    # identity, key names, timestamps, and earliest expiry. It contains NO
    # secret values and is safe to share when filing a bug report. The .enc
    # files remain authoritative — the index is purely for human inspection
    # and for cheap ``list_all()`` enumeration.
    #
    # Schema version is bumped whenever the entry shape changes; the store
    # rebuilds the index from the encrypted files on load when the on-disk
    # version is older.
    # ------------------------------------------------------------------

    INDEX_VERSION = "2.0"
    INDEX_INTERNAL_KEY_NAMES = ("_alias", "_integration_type")

    def _index_path(self) -> Path:
        return self.base_path / "metadata" / "index.json"

    def _read_index(self) -> dict[str, Any]:
        """Read the index from disk; return an empty skeleton if missing."""
        path = self._index_path()
        if not path.exists():
            return {"version": self.INDEX_VERSION, "credentials": {}}
        try:
            with open(path, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            logger.debug("Failed to read credential index, starting fresh", exc_info=True)
            return {"version": self.INDEX_VERSION, "credentials": {}}

    def _write_index(self, index: dict[str, Any]) -> None:
        """Write the index to disk with consistent envelope fields."""
        index["version"] = self.INDEX_VERSION
        index["store_path"] = str(self.base_path)
        index["generated_at"] = datetime.now(UTC).isoformat()
        path = self._index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, sort_keys=False, default=str)

    def _index_entry_for(self, credential: CredentialObject) -> dict[str, Any]:
        """Build a single index entry from a CredentialObject (no secrets)."""
        # Visible key names: drop internal markers like _alias / _integration_type
        # / _identity_* so the entry shows what's actually a credential key.
        visible_keys = [
            name
            for name in credential.keys.keys()
            if name not in self.INDEX_INTERNAL_KEY_NAMES and not name.startswith("_identity_")
        ]

        # Earliest expiry across all keys (most likely the access_token).
        earliest_expiry: datetime | None = None
        for key in credential.keys.values():
            if key.expires_at is None:
                continue
            if earliest_expiry is None or key.expires_at < earliest_expiry:
                earliest_expiry = key.expires_at

        return {
            "credential_type": credential.credential_type.value,
            "provider": credential.provider_type,
            "alias": credential.alias,
            "identity": credential.identity.to_dict(),
            "key_names": sorted(visible_keys),
            "created_at": credential.created_at.isoformat() if credential.created_at else None,
            "updated_at": credential.updated_at.isoformat() if credential.updated_at else None,
            "last_refreshed": (credential.last_refreshed.isoformat() if credential.last_refreshed else None),
            "expires_at": earliest_expiry.isoformat() if earliest_expiry else None,
            "auto_refresh": credential.auto_refresh,
            "tags": list(credential.tags),
        }

    def _index_upsert(self, credential: CredentialObject) -> None:
        """Insert or update one credential entry in the index."""
        try:
            index = self._read_index()
            if index.get("version") != self.INDEX_VERSION:
                # Old schema — rebuild from disk so we don't blend formats.
                self._rebuild_index()
                return
            credentials = index.setdefault("credentials", {})
            credentials[credential.id] = self._index_entry_for(credential)
            self._write_index(index)
        except Exception:
            logger.debug("Index upsert failed (non-fatal)", exc_info=True)

    def _index_remove(self, credential_id: str) -> None:
        """Remove one credential entry from the index."""
        try:
            index = self._read_index()
            if index.get("version") != self.INDEX_VERSION:
                self._rebuild_index()
                return
            credentials = index.setdefault("credentials", {})
            credentials.pop(credential_id, None)
            self._write_index(index)
        except Exception:
            logger.debug("Index remove failed (non-fatal)", exc_info=True)

    def _maybe_rebuild_index(self) -> None:
        """Rebuild the index if it's missing, malformed, or on an old schema.

        Called once at startup. The check is cheap — read the version field
        and bail out if it matches. Encrypted files remain authoritative; this
        only refreshes the developer-facing snapshot.
        """
        path = self._index_path()
        if path.exists():
            try:
                with open(path, encoding="utf-8-sig") as f:
                    index = json.load(f)
                if index.get("version") == self.INDEX_VERSION:
                    return
            except Exception:
                pass  # fall through to rebuild
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        """Walk the encrypted credentials directory and rewrite a fresh index."""
        cred_dir = self.base_path / "credentials"
        if not cred_dir.is_dir():
            return

        entries: dict[str, Any] = {}
        for cred_file in sorted(cred_dir.glob("*.enc")):
            credential_id = cred_file.stem
            try:
                cred = self.load(credential_id)
            except Exception:
                logger.debug(
                    "Failed to load %s during index rebuild — skipping",
                    credential_id,
                    exc_info=True,
                )
                continue
            if cred is None:
                continue
            entries[cred.id] = self._index_entry_for(cred)

        index = {"credentials": entries}
        self._write_index(index)
        logger.info("Rebuilt credential index with %d entries", len(entries))


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
            "EnvVarStorage is read-only. Set environment variables externally or use EncryptedFileStorage."
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
        raise NotImplementedError("EnvVarStorage is read-only. Unset environment variables externally.")

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
        return bool(self._read_env_value(env_var))

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
