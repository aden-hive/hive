"""
HashiCorp Vault storage adapter.

Provides integration with HashiCorp Vault for enterprise secret management.
Requires the 'hvac' package: pip install hvac
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from pydantic import SecretStr

from ..models import CredentialKey, CredentialObject, CredentialType
from ..storage import CredentialStorage

logger = logging.getLogger(__name__)


class HashiCorpVaultStorage(CredentialStorage):
    """
    HashiCorp Vault storage adapter.

    Features:
    - KV v2 secrets engine support
    - Namespace support (Enterprise)
    - Automatic secret versioning
    - Audit logging via Vault

    The adapter stores credentials in Vault's KV v2 secrets engine with
    the following structure:

        {mount_point}/data/{path_prefix}/{credential_id}
        └── data:
            ├── _type: "oauth2"
            ├── access_token: "xxx"
            ├── refresh_token: "yyy"
            ├── _expires_access_token: "2024-01-26T12:00:00"
            └── _provider_id: "oauth2"

    Example:
        storage = HashiCorpVaultStorage(
            url="https://vault.example.com:8200",
            token="hvs.xxx",  # Or use VAULT_TOKEN env var
            mount_point="secret",
            path_prefix="hive/credentials"
        )

        store = CredentialStore(storage=storage)

        # Credentials are now stored in Vault
        store.save_credential(credential)
        credential = store.get_credential("my_api")

    Authentication:
        The adapter uses token-based authentication. The token can be provided:
        1. Directly via the 'token' parameter
        2. Via the VAULT_TOKEN environment variable

        For production, consider using:
        - Kubernetes auth method
        - AppRole auth method
        - AWS IAM auth method

    Requirements:
        pip install hvac
    """

    def __init__(
        self,
        url: str,
        token: str | None = None,
        mount_point: str = "secret",
        path_prefix: str = "hive/credentials",
        namespace: str | None = None,
        verify_ssl: bool = True,
    ):
        """
        Initialize Vault storage.

        Args:
            url: Vault server URL (e.g., https://vault.example.com:8200)
            token: Vault token. If None, reads from VAULT_TOKEN env var
            mount_point: KV secrets engine mount point (default: "secret")
            path_prefix: Path prefix for all credentials
            namespace: Vault namespace (Enterprise feature)
            verify_ssl: Whether to verify SSL certificates

        Raises:
            ImportError: If hvac is not installed
            ValueError: If authentication fails
        """
        try:
            import hvac
        except ImportError as e:
            raise ImportError(
                "HashiCorp Vault support requires 'hvac'. Install with: pip install hvac"
            ) from e

        self._url = url
        self._token = token or os.environ.get("VAULT_TOKEN")
        self._mount = mount_point
        self._prefix = path_prefix
        self._namespace = namespace

        if not self._token:
            raise ValueError(
                "Vault token required. Set VAULT_TOKEN env var or pass token parameter."
            )

        self._client = hvac.Client(
            url=url,
            token=self._token,
            namespace=namespace,
            verify=verify_ssl,
        )

        if not self._client.is_authenticated():
            raise ValueError("Vault authentication failed. Check token and server URL.")

        logger.info(f"Connected to HashiCorp Vault at {url}")

    def _path(self, credential_id: str) -> str:
        """Build Vault path for credential."""
        # Sanitize credential_id
        safe_id = credential_id.replace("/", "_").replace("\\", "_")
        return f"{self._prefix}/{safe_id}"

    def save(self, credential: CredentialObject) -> None:
        """Save credential to Vault KV v2."""
        path = self._path(credential.id)
        data = self._serialize_for_vault(credential)

        try:
            self._client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=data,
                mount_point=self._mount,
            )
            logger.debug(f"Saved credential '{credential.id}' to Vault at {path}")
        except Exception as e:
            logger.error(f"Failed to save credential '{credential.id}' to Vault: {e}")
            raise

    def load(self, credential_id: str) -> CredentialObject | None:
        """Load credential from Vault."""
        path = self._path(credential_id)

        try:
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self._mount,
            )
            data = response["data"]["data"]
            return self._deserialize_from_vault(credential_id, data)
        except Exception as e:
            # Check if it's a "not found" error
            error_str = str(e).lower()
            if "not found" in error_str or "404" in error_str:
                logger.debug(f"Credential '{credential_id}' not found in Vault")
                return None
            logger.error(f"Failed to load credential '{credential_id}' from Vault: {e}")
            raise

    def delete(self, credential_id: str) -> bool:
        """Delete credential from Vault (all versions)."""
        path = self._path(credential_id)

        try:
            self._client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=path,
                mount_point=self._mount,
            )
            logger.debug(f"Deleted credential '{credential_id}' from Vault")
            return True
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "404" in error_str:
                return False
            logger.error(f"Failed to delete credential '{credential_id}' from Vault: {e}")
            raise

    def list_all(self) -> list[str]:
        """List all credentials under the prefix."""
        try:
            response = self._client.secrets.kv.v2.list_secrets(
                path=self._prefix,
                mount_point=self._mount,
            )
            keys = response.get("data", {}).get("keys", [])
            # Remove trailing slashes from folder names
            return [k.rstrip("/") for k in keys]
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "404" in error_str:
                return []
            logger.error(f"Failed to list credentials from Vault: {e}")
            raise

    def exists(self, credential_id: str) -> bool:
        """Check if credential exists in Vault."""
        try:
            path = self._path(credential_id)
            self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self._mount,
            )
            return True
        except Exception:
            return False

    def _serialize_for_vault(self, credential: CredentialObject) -> dict[str, Any]:
        """Convert credential to Vault secret format."""
        data: dict[str, Any] = {
            "_type": credential.credential_type.value,
        }

        if credential.provider_id:
            data["_provider_id"] = credential.provider_id

        if credential.description:
            data["_description"] = credential.description

        if credential.auto_refresh:
            data["_auto_refresh"] = "true"

        # Store each key
        for key_name, key in credential.keys.items():
            data[key_name] = key.get_secret_value()

            if key.expires_at:
                data[f"_expires_{key_name}"] = key.expires_at.isoformat()

            if key.metadata:
                data[f"_metadata_{key_name}"] = str(key.metadata)

        return data

    def _deserialize_from_vault(self, credential_id: str, data: dict[str, Any]) -> CredentialObject:
        """Reconstruct credential from Vault secret."""
        # Extract metadata fields
        cred_type = CredentialType(data.pop("_type", "api_key"))
        provider_id = data.pop("_provider_id", None)
        description = data.pop("_description", "")
        auto_refresh = data.pop("_auto_refresh", "") == "true"

        # Build keys dict
        keys: dict[str, CredentialKey] = {}

        # Find all non-metadata keys
        key_names = [k for k in data.keys() if not k.startswith("_")]

        for key_name in key_names:
            value = data[key_name]

            # Check for expiration
            expires_at = None
            expires_key = f"_expires_{key_name}"
            if expires_key in data:
                try:
                    expires_at = datetime.fromisoformat(data[expires_key])
                except (ValueError, TypeError):
                    pass

            # Check for metadata
            metadata: dict[str, Any] = {}
            metadata_key = f"_metadata_{key_name}"
            if metadata_key in data:
                try:
                    import ast

                    metadata = ast.literal_eval(data[metadata_key])
                except (ValueError, SyntaxError):
                    pass

            keys[key_name] = CredentialKey(
                name=key_name,
                value=SecretStr(value),
                expires_at=expires_at,
                metadata=metadata,
            )

        return CredentialObject(
            id=credential_id,
            credential_type=cred_type,
            keys=keys,
            provider_id=provider_id,
            description=description,
            auto_refresh=auto_refresh,
        )

    # --- Vault-Specific Operations ---

    def get_secret_metadata(self, credential_id: str) -> dict[str, Any] | None:
        """
        Get Vault metadata for a secret (version info, timestamps, etc.).

        Args:
            credential_id: The credential identifier

        Returns:
            Metadata dict or None if not found
        """
        path = self._path(credential_id)

        try:
            response = self._client.secrets.kv.v2.read_secret_metadata(
                path=path,
                mount_point=self._mount,
            )
            return response.get("data", {})
        except Exception:
            return None

    def soft_delete(self, credential_id: str, versions: list[int] | None = None) -> bool:
        """
        Soft delete specific versions (can be recovered).

        Args:
            credential_id: The credential identifier
            versions: Version numbers to delete. If None, deletes latest.

        Returns:
            True if successful
        """
        path = self._path(credential_id)

        try:
            if versions:
                self._client.secrets.kv.v2.delete_secret_versions(
                    path=path,
                    versions=versions,
                    mount_point=self._mount,
                )
            else:
                self._client.secrets.kv.v2.delete_latest_version_of_secret(
                    path=path,
                    mount_point=self._mount,
                )
            return True
        except Exception as e:
            logger.error(f"Soft delete failed for '{credential_id}': {e}")
            return False

    def undelete(self, credential_id: str, versions: list[int]) -> bool:
        """
        Recover soft-deleted versions.

        Args:
            credential_id: The credential identifier
            versions: Version numbers to recover

        Returns:
            True if successful
        """
        path = self._path(credential_id)

        try:
            self._client.secrets.kv.v2.undelete_secret_versions(
                path=path,
                versions=versions,
                mount_point=self._mount,
            )
            return True
        except Exception as e:
            logger.error(f"Undelete failed for '{credential_id}': {e}")
            return False

    def load_version(self, credential_id: str, version: int) -> CredentialObject | None:
        """
        Load a specific version of a credential.

        Args:
            credential_id: The credential identifier
            version: Version number to load

        Returns:
            CredentialObject or None
        """
        path = self._path(credential_id)

        try:
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                version=version,
                mount_point=self._mount,
            )
            data = response["data"]["data"]
            return self._deserialize_from_vault(credential_id, data)
        except Exception:
            return None
