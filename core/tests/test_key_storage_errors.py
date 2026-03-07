"""Tests for key_storage.py exception handling improvements.

Covers Issue #5931: Bare ``except Exception:`` clauses silently swallow errors.
The fix narrows exception types and raises log severity from debug to warning.
"""

from __future__ import annotations

import logging
import os
from unittest.mock import patch


class TestDeleteAdenApiKey:
    """delete_aden_api_key should log a warning on failure, not silently pass."""

    def test_logs_warning_on_storage_error(self, caplog):
        from framework.credentials.key_storage import delete_aden_api_key

        with patch(
            "framework.credentials.storage.EncryptedFileStorage",
            side_effect=OSError("disk error"),
        ):
            with caplog.at_level(logging.WARNING):
                delete_aden_api_key()

        assert any("Could not delete" in r.message for r in caplog.records)

    def test_env_var_removed_even_on_failure(self):
        from framework.credentials.key_storage import (
            ADEN_ENV_VAR,
            delete_aden_api_key,
        )

        os.environ[ADEN_ENV_VAR] = "test-key"
        with patch(
            "framework.credentials.storage.EncryptedFileStorage",
            side_effect=ValueError("bad key"),
        ):
            delete_aden_api_key()

        assert ADEN_ENV_VAR not in os.environ


class TestReadCredentialKeyFile:
    """_read_credential_key_file should log warning on failure."""

    def test_returns_none_on_unicode_error(self, tmp_path, caplog):
        from framework.credentials.key_storage import _read_credential_key_file

        key_file = tmp_path / "credential_key"
        key_file.write_bytes(b"\xff\xfe")  # Invalid UTF-8

        with patch("framework.credentials.key_storage.CREDENTIAL_KEY_PATH", key_file):
            with caplog.at_level(logging.WARNING):
                result = _read_credential_key_file()

        assert result is None
        assert any("Could not read" in r.message for r in caplog.records)

    def test_returns_value_on_success(self, tmp_path):
        from framework.credentials.key_storage import _read_credential_key_file

        key_file = tmp_path / "credential_key"
        key_file.write_text("my-secret-key", encoding="utf-8")

        with patch("framework.credentials.key_storage.CREDENTIAL_KEY_PATH", key_file):
            result = _read_credential_key_file()

        assert result == "my-secret-key"


class TestReadAdenFromEncryptedStore:
    """_read_aden_from_encrypted_store should log warning on failure."""

    def test_returns_none_when_no_env_var(self):
        from framework.credentials.key_storage import _read_aden_from_encrypted_store

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HIVE_CREDENTIAL_KEY", None)
            result = _read_aden_from_encrypted_store()

        assert result is None

    def test_logs_warning_on_storage_error(self, caplog):
        from framework.credentials.key_storage import _read_aden_from_encrypted_store

        with patch.dict(os.environ, {"HIVE_CREDENTIAL_KEY": "test-key"}):
            with patch(
                "framework.credentials.storage.EncryptedFileStorage",
                side_effect=OSError("corrupt store"),
            ):
                with caplog.at_level(logging.WARNING):
                    result = _read_aden_from_encrypted_store()

        assert result is None
        assert any("Could not load" in r.message for r in caplog.records)
