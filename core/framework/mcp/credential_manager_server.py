"""
MCP Server for Credential Management

Exposes tools for secure credential management via the Model Context Protocol.

Features:
- List and validate credentials
- Retrieve credential values safely (with audit logging)
- Rotate encryption keys
- Generate new credentials
- Check credential health

Usage:
    uv run python -m framework.mcp.credential_manager_server
"""

import logging
from typing import Annotated

from mcp.server import FastMCP
from mcp.types import TextContent, Tool

from framework.credentials import (
    CredentialStore,
    CredentialObject,
    CredentialKey,
    CredentialType,
)
from pydantic import SecretStr

# Initialize MCP server
mcp = FastMCP("credential-manager")
logger = logging.getLogger(__name__)

# Global credential store instance
_store: CredentialStore | None = None


def get_store() -> CredentialStore:
    """Get or initialize the global credential store."""
    global _store
    if _store is None:
        # Use default encrypted storage with env var fallback
        try:
            _store = CredentialStore.with_encrypted_storage()
        except Exception as e:
            logger.warning(f"Encrypted storage failed, using env vars only: {e}")
            _store = CredentialStore.with_env_storage()
    return _store


@mcp.tool()
def list_credentials() -> str:
    """
    List all available credentials (by ID only, no values).

    Returns:
        JSON array of credential IDs available in storage
    """
    store = get_store()
    credentials = store.list_credentials()
    return f"Available credentials: {', '.join(credentials) if credentials else 'None'}"


@mcp.tool()
def get_credential(
    credential_id: Annotated[str, "The credential identifier (e.g., 'github_oauth')"],
) -> str:
    """
    Retrieve a credential value by ID.

    **Security:** This logs the retrieval for audit purposes.

    Args:
        credential_id: The credential identifier

    Returns:
        The credential value (masked in logs)
    """
    store = get_store()
    value = store.get(credential_id)

    if value is None:
        logger.warning(f"Credential '{credential_id}' not found")
        return f"Credential '{credential_id}' not found"

    logger.info(f"Retrieved credential '{credential_id}' (audit: access logged)")
    return f"✓ Retrieved credential '{credential_id}' (length: {len(value)} chars)"


@mcp.tool()
def validate_credential(
    credential_id: Annotated[str, "The credential identifier to validate"],
) -> str:
    """
    Validate a credential using its provider (if available).

    Tests whether the credential is:
    - Present and non-empty
    - Has required keys
    - Passes provider validation (e.g., OAuth token refresh)

    Args:
        credential_id: The credential identifier

    Returns:
        Validation status and any errors
    """
    store = get_store()
    credential = store.get_credential(credential_id)

    if credential is None:
        return f"✗ Credential '{credential_id}' not found"

    # Check basic structure
    if not credential.keys:
        return f"✗ Credential '{credential_id}' has no keys"

    # Try provider validation
    is_valid = store.validate_credential(credential_id)
    if is_valid:
        return f"✓ Credential '{credential_id}' is valid"
    else:
        return f"⚠ Credential '{credential_id}' failed validation (may need refresh)"


@mcp.tool()
def rotate_encryption_key(
    new_key_b64: Annotated[
        str,
        "Base64-encoded Fernet key (generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')",
    ],
) -> str:
    """
    Rotate the encryption key used by credential storage.

    This re-encrypts all stored credentials with a new key atomically.

    **Important:**
    - Backup credentials first: cp -r ~/.hive/credentials ~/.hive/credentials.backup
    - Keep old key until rotation completes and is verified
    - Only works with EncryptedFileStorage backend

    Args:
        new_key_b64: Base64-encoded Fernet key bytes

    Returns:
        Status message with result
    """
    store = get_store()

    # Decode the base64 key
    try:
        new_key = new_key_b64.encode()
    except Exception as e:
        return f"✗ Invalid key format: {e}"

    # Attempt rotation
    try:
        store._storage.rotate_key(new_key)
        logger.info("Encryption key rotated successfully")
        return "✓ Encryption key rotated successfully. All credentials re-encrypted."
    except AttributeError:
        return "✗ Storage backend does not support key rotation (not EncryptedFileStorage)"
    except Exception as e:
        logger.error(f"Key rotation failed: {e}")
        return f"✗ Key rotation failed: {e}"


@mcp.tool()
def check_credential_health() -> str:
    """
    Check the health of all stored credentials.

    Validates:
    - Each credential exists and is readable
    - No corrupted encryption
    - Keys are accessible

    Returns:
        Summary of credential health status
    """
    store = get_store()
    credentials = store.list_credentials()

    if not credentials:
        return "⚠ No credentials found in storage"

    results = []
    errors = []

    for cred_id in credentials:
        try:
            cred = store.get_credential(cred_id, refresh_if_needed=False)
            if cred:
                results.append(f"  ✓ {cred_id} ({len(cred.keys)} keys)")
            else:
                errors.append(f"  ✗ {cred_id} (read returned None)")
        except Exception as e:
            errors.append(f"  ✗ {cred_id} ({type(e).__name__}: {str(e)[:50]})")

    status = f"Credential Health Report:\n"
    if results:
        status += f"OK ({len(results)}):\n" + "\n".join(results) + "\n"
    if errors:
        status += f"ERRORS ({len(errors)}):\n" + "\n".join(errors)

    return status


@mcp.tool()
def generate_fernet_key() -> str:
    """
    Generate a new Fernet encryption key.

    Use this output as `new_key_b64` for rotate_encryption_key.

    Returns:
        Base64-encoded Fernet key ready for use
    """
    try:
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        return f"Generated key (base64):\n{key.decode()}\n\nSet as env var:\nexport HIVE_CREDENTIAL_KEY={key.decode()}"
    except ImportError:
        return "✗ cryptography package not installed. Install with: pip install cryptography"


@mcp.tool()
def save_credential(
    credential_id: Annotated[str, "Unique identifier for the credential"],
    credential_value: Annotated[str, "The secret value (API key, token, etc.)"],
    credential_type: Annotated[
        str,
        "Type: API_KEY, OAUTH2, BEARER_TOKEN, USERNAME_PASSWORD, WEBHOOK_SECRET",
    ] = "API_KEY",
) -> str:
    """
    Save a new credential to encrypted storage.

    Args:
        credential_id: Unique identifier (e.g., 'my_api_key')
        credential_value: The secret value to store
        credential_type: The credential type/category

    Returns:
        Status message
    """
    store = get_store()

    try:
        cred_type = CredentialType[credential_type.upper()]
    except KeyError:
        return f"✗ Invalid credential_type. Use: API_KEY, OAUTH2, BEARER_TOKEN, USERNAME_PASSWORD, WEBHOOK_SECRET"

    try:
        credential = CredentialObject(
            id=credential_id,
            credential_type=cred_type,
            keys={"api_key": CredentialKey(name="api_key", value=SecretStr(credential_value))},
        )
        store.save_credential(credential)
        logger.info(f"Saved credential '{credential_id}'")
        return f"✓ Credential '{credential_id}' saved securely"
    except Exception as e:
        logger.error(f"Failed to save credential: {e}")
        return f"✗ Failed to save credential: {e}"


@mcp.tool()
def delete_credential(
    credential_id: Annotated[str, "The credential identifier to delete"],
) -> str:
    """
    Delete a credential from storage.

    Args:
        credential_id: The credential to delete

    Returns:
        Status message
    """
    store = get_store()

    try:
        deleted = store.delete_credential(credential_id)
        if deleted:
            logger.info(f"Deleted credential '{credential_id}'")
            return f"✓ Credential '{credential_id}' deleted"
        else:
            return f"✗ Credential '{credential_id}' not found"
    except Exception as e:
        logger.error(f"Failed to delete credential: {e}")
        return f"✗ Failed to delete credential: {e}"


if __name__ == "__main__":
    import sys

    # Run server
    mcp.run(sys.stdout.buffer)
