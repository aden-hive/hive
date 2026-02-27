"""
Dedicated file-based storage for bootstrap credentials.

HIVE_CREDENTIAL_KEY -> ~/.hive/secrets/credential_key  (plain text, chmod 600)
ADEN_API_KEY        -> ~/.hive/credentials/             (encrypted via EncryptedFileStorage)

Boot order:
  1. load_credential_key()   -- reads/generates the Fernet key, sets os.environ
  2. load_aden_api_key()     -- uses the encrypted store (which needs the key from step 1)
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

CREDENTIAL_KEY_PATH = Path.home() / ".hive" / "secrets" / "credential_key"
CREDENTIAL_KEY_ENV_VAR = "HIVE_CREDENTIAL_KEY"
ADEN_CREDENTIAL_ID = "aden_api_key"
ADEN_ENV_VAR = "ADEN_API_KEY"


# ---------------------------------------------------------------------------
# HIVE_CREDENTIAL_KEY
# ---------------------------------------------------------------------------


def load_credential_key() -> str | None:
    """Load HIVE_CREDENTIAL_KEY with priority: env > file > shell config.

    Sets ``os.environ["HIVE_CREDENTIAL_KEY"]`` as a side-effect when found.
    Returns the key string, or ``None`` if unavailable everywhere.
    """
    # 1. Already in environment (set by parent process, CI, Windows Registry, etc.)
    key = os.environ.get(CREDENTIAL_KEY_ENV_VAR)
    if key:
        return key

    # 2. Dedicated secrets file
    key = _read_credential_key_file()
    if key:
        os.environ[CREDENTIAL_KEY_ENV_VAR] = key
        return key

    # 3. Shell config fallback (backward compat for old installs)
    key = _read_from_shell_config(CREDENTIAL_KEY_ENV_VAR)
    if key:
        os.environ[CREDENTIAL_KEY_ENV_VAR] = key
        return key

    return None


def save_credential_key(key: str) -> Path:
    """Save HIVE_CREDENTIAL_KEY to ``~/.hive/secrets/credential_key``.

    Creates parent dirs with mode 700, writes the file with mode 600.
    Also sets ``os.environ["HIVE_CREDENTIAL_KEY"]``.

    Returns:
        The path that was written.
    """
    path = CREDENTIAL_KEY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # Restrict the secrets directory itself
    path.parent.chmod(stat.S_IRWXU)  # 0o700

    path.write_text(key)
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600

    os.environ[CREDENTIAL_KEY_ENV_VAR] = key
    return path


def generate_and_save_credential_key() -> str:
    """Generate a new Fernet key and persist it to ``~/.hive/secrets/credential_key``.

    Returns:
        The generated key string.
    """
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    save_credential_key(key)
    return key


# ---------------------------------------------------------------------------
# ADEN_API_KEY
# ---------------------------------------------------------------------------


def load_aden_api_key() -> str | None:
    """Load ADEN_API_KEY with priority: env > encrypted store > shell config.

    **Must** be called after ``load_credential_key()`` because the encrypted
    store depends on HIVE_CREDENTIAL_KEY.

    Sets ``os.environ["ADEN_API_KEY"]`` as a side-effect when found.
    Returns the key string, or ``None`` if unavailable everywhere.
    """
    # 1. Already in environment
    key = os.environ.get(ADEN_ENV_VAR)
    if key:
        return key

    # 2. Encrypted credential store
    key = _read_aden_from_encrypted_store()
    if key:
        os.environ[ADEN_ENV_VAR] = key
        return key

    # 3. Shell config fallback (backward compat)
    key = _read_from_shell_config(ADEN_ENV_VAR)
    if key:
        os.environ[ADEN_ENV_VAR] = key
        return key

    return None


def save_aden_api_key(key: str) -> None:
    """Save ADEN_API_KEY to the encrypted credential store.

    Also sets ``os.environ["ADEN_API_KEY"]``.
    """
    from pydantic import SecretStr

    from .models import CredentialKey, CredentialObject
    from .storage import EncryptedFileStorage

    storage = EncryptedFileStorage()
    cred = CredentialObject(
        id=ADEN_CREDENTIAL_ID,
        keys={"api_key": CredentialKey(name="api_key", value=SecretStr(key))},
    )
    storage.save(cred)
    os.environ[ADEN_ENV_VAR] = key


def delete_aden_api_key() -> None:
    """Remove ADEN_API_KEY from the encrypted store and ``os.environ``."""
    try:
        from .storage import EncryptedFileStorage

        storage = EncryptedFileStorage()
        storage.delete(ADEN_CREDENTIAL_ID)
    except Exception:
        logger.debug("Could not delete %s from encrypted store", ADEN_CREDENTIAL_ID)

    os.environ.pop(ADEN_ENV_VAR, None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_credential_key_file() -> str | None:
    """Read the credential key from ``~/.hive/secrets/credential_key``."""
    try:
        if CREDENTIAL_KEY_PATH.is_file():
            value = CREDENTIAL_KEY_PATH.read_text().strip()
            if value:
                return value
    except Exception:
        logger.debug("Could not read %s", CREDENTIAL_KEY_PATH)
    return None


def _read_from_shell_config(env_var: str) -> str | None:
    """Fallback: read an env var from ~/.zshrc or ~/.bashrc."""
    try:
        from aden_tools.credentials.shell_config import check_env_var_in_shell_config

        found, value = check_env_var_in_shell_config(env_var)
        if found and value:
            return value
    except ImportError:
        pass
    return None


def _read_aden_from_encrypted_store() -> str | None:
    """Try to load ADEN_API_KEY from the encrypted credential store."""
    if not os.environ.get(CREDENTIAL_KEY_ENV_VAR):
        return None
    try:
        from .storage import EncryptedFileStorage

        storage = EncryptedFileStorage()
        cred = storage.load(ADEN_CREDENTIAL_ID)
        if cred:
            return cred.get_key("api_key")
    except Exception:
        logger.debug("Could not load %s from encrypted store", ADEN_CREDENTIAL_ID)
    return None
