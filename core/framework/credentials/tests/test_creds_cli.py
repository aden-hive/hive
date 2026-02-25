"""Test suite for credential CLI commands."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from pydantic import SecretStr

from framework.credentials import (
    CredentialKey,
    CredentialObject,
    CredentialStore,
    CredentialType,
    InMemoryStorage,
)
from framework.credentials.cli import (
    _get_store,
    cmd_add,
    cmd_delete,
    cmd_list,
    cmd_refresh,
    cmd_show,
    cmd_test,
    register_commands,
)


@pytest.fixture
def mock_store():
    """Create a mock credential store with in-memory storage."""
    storage = InMemoryStorage()
    store = CredentialStore(storage=storage)
    return store


@pytest.fixture
def sample_credential():
    """Create a sample credential for testing."""
    return CredentialObject(
        id="test_api",
        credential_type=CredentialType.API_KEY,
        keys={
            "api_key": CredentialKey(name="api_key", value=SecretStr("secret-key-12345"))
        },
    )


@pytest.fixture
def oauth_credential():
    """Create an OAuth2 credential for testing."""
    expires = datetime.now(UTC) + timedelta(hours=1)
    return CredentialObject(
        id="test_oauth",
        credential_type=CredentialType.OAUTH2,
        keys={
            "access_token": CredentialKey(
                name="access_token", value=SecretStr("token-abc123"), expires_at=expires
            )
        },
    )


@pytest.fixture
def expired_credential():
    """Create an expired credential for testing."""
    past = datetime.now(UTC) - timedelta(hours=1)
    return CredentialObject(
        id="expired_api",
        credential_type=CredentialType.API_KEY,
        keys={
            "api_key": CredentialKey(
                name="api_key", value=SecretStr("old-key"), expires_at=past
            )
        },
    )


class TestCmdList:
    """Tests for `hive creds list` command."""

    @patch("framework.credentials.cli._get_store")
    def test_list_empty(self, mock_get_store, mock_store, capsys):
        """Test listing when no credentials exist."""
        mock_get_store.return_value = mock_store

        args = argparse.Namespace(json=False)
        exit_code = cmd_list(args)

        assert exit_code == 0, "Expected exit code 0 for successful list command"
        captured = capsys.readouterr()
        assert captured.out.strip() == "No credentials found."

    @patch("framework.credentials.cli._get_store")
    def test_list_empty_json(self, mock_get_store, mock_store, capsys):
        """Test listing empty credentials with JSON output."""
        mock_get_store.return_value = mock_store

        args = argparse.Namespace(json=True)
        exit_code = cmd_list(args)

        assert exit_code == 0, "Expected exit code 0 for successful list command"
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == {"credentials": []}

    @patch("framework.credentials.cli._get_store")
    def test_list_single_credential(self, mock_get_store, mock_store, sample_credential, capsys):
        """Test listing a single credential."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)

        args = argparse.Namespace(json=False)
        result = cmd_list(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Found 1 credential(s)" in captured.out
        assert "test_api" in captured.out
        assert "api_key" in captured.out

    @patch("framework.credentials.cli._get_store")
    def test_list_multiple_credentials(
        self, mock_get_store, mock_store, sample_credential, oauth_credential, capsys
    ):
        """Test listing multiple credentials."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)
        mock_store.save_credential(oauth_credential)

        args = argparse.Namespace(json=False)
        result = cmd_list(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Found 2 credential(s)" in captured.out
        assert "test_api" in captured.out
        assert "test_oauth" in captured.out

    @patch("framework.credentials.cli._get_store")
    def test_list_json_output(self, mock_get_store, mock_store, sample_credential, capsys):
        """Test listing with JSON output format."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)

        args = argparse.Namespace(json=True)
        result = cmd_list(args)

        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "credentials" in data
        assert len(data["credentials"]) == 1
        assert data["credentials"][0]["id"] == "test_api"
        assert data["credentials"][0]["type"] == "api_key"

    @patch("framework.credentials.cli._get_store")
    def test_list_with_expiration(
        self, mock_get_store, mock_store, oauth_credential, capsys
    ):
        """Test listing credentials with expiration info."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(oauth_credential)

        args = argparse.Namespace(json=False)
        result = cmd_list(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "expires soon" in captured.out

    @patch("framework.credentials.cli._get_store")
    def test_list_error_handling(self, mock_get_store, capsys):
        """Test error handling in list command."""
        mock_get_store.side_effect = Exception("Storage error")

        args = argparse.Namespace(json=False)
        result = cmd_list(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error listing credentials" in captured.err


class TestCmdShow:
    """Tests for `hive creds show` command."""

    @patch("framework.credentials.cli._get_store")
    def test_show_existing_credential(
        self, mock_get_store, mock_store, sample_credential, capsys
    ):
        """Test showing an existing credential."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)

        args = argparse.Namespace(credential_id="test_api", json=False)
        result = cmd_show(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Credential: test_api" in captured.out
        assert "Type: api_key" in captured.out
        assert "Status: valid" in captured.out

    @patch("framework.credentials.cli._get_store")
    def test_show_masks_secrets(self, mock_get_store, mock_store, sample_credential, capsys):
        """Test that secrets are masked in output."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)

        args = argparse.Namespace(credential_id="test_api", json=False)
        result = cmd_show(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "secret-key-12345" not in captured.out
        assert "*****12345" in captured.out or "*****" in captured.out

    @patch("framework.credentials.cli._get_store")
    def test_show_nonexistent_credential(self, mock_get_store, mock_store, capsys):
        """Test showing a non-existent credential."""
        mock_get_store.return_value = mock_store

        args = argparse.Namespace(credential_id="nonexistent", json=False)
        exit_code = cmd_show(args)

        assert exit_code == 1, "Expected exit code 1 for non-existent credential"
        captured = capsys.readouterr()
        assert "Error: Credential 'nonexistent' not found." in captured.err

    @patch("framework.credentials.cli._get_store")
    def test_show_json_output(self, mock_get_store, mock_store, sample_credential, capsys):
        """Test showing credential with JSON output."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)

        args = argparse.Namespace(credential_id="test_api", json=True)
        result = cmd_show(args)

        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["id"] == "test_api"
        assert data["type"] == "api_key"
        assert "keys" in data
        assert "api_key" in data["keys"]
        assert "secret-key-12345" not in data["keys"]["api_key"]["value"]

    @patch("framework.credentials.cli._get_store")
    def test_show_with_expiration(
        self, mock_get_store, mock_store, oauth_credential, capsys
    ):
        """Test showing credential with expiration."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(oauth_credential)

        args = argparse.Namespace(credential_id="test_oauth", json=False)
        result = cmd_show(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Expires:" in captured.out

    @patch("framework.credentials.cli._get_store")
    def test_show_error_handling(self, mock_get_store, capsys):
        """Test error handling in show command."""
        mock_get_store.side_effect = Exception("Storage error")

        args = argparse.Namespace(credential_id="test_api", json=False)
        result = cmd_show(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error showing credential" in captured.err


class TestCmdAdd:
    """Tests for `hive creds add` command."""

    @patch("framework.credentials.cli._get_store")
    @patch("framework.credentials.cli.input")
    @patch("framework.credentials.cli.getpass")
    def test_add_new_credential(
        self, mock_getpass, mock_input, mock_get_store, mock_store, capsys
    ):
        """Test adding a new credential interactively."""
        mock_get_store.return_value = mock_store
        mock_input.side_effect = ["api_key", "", ""]
        mock_getpass.getpass.return_value = "my-secret-key"

        args = argparse.Namespace(
            credential_id="new_api", type="static", storage="file"
        )
        result = cmd_add(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Successfully saved credential 'new_api'" in captured.out
        assert mock_store.is_available("new_api")

    @patch("framework.credentials.cli._get_store")
    @patch("framework.credentials.cli.input")
    @patch("framework.credentials.cli.getpass")
    def test_add_with_multiple_keys(
        self, mock_getpass, mock_input, mock_get_store, mock_store, capsys
    ):
        """Test adding credential with multiple keys."""
        mock_get_store.return_value = mock_store
        mock_input.side_effect = [
            "api_key",
            "2025-12-31 23:59:59",
            "client_id",
            "",
            "",
        ]
        mock_getpass.getpass.side_effect = ["secret-key", "client-123"]

        args = argparse.Namespace(
            credential_id="multi_key", type="api_key", storage="file"
        )
        result = cmd_add(args)

        assert result == 0
        cred = mock_store.get_credential("multi_key")
        assert cred is not None
        assert "api_key" in cred.keys
        assert "client_id" in cred.keys

    @patch("framework.credentials.cli._get_store")
    @patch("framework.credentials.cli.input")
    def test_add_duplicate_without_overwrite(
        self, mock_input, mock_get_store, mock_store, sample_credential, capsys
    ):
        """Test adding duplicate credential without overwriting."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)
        mock_input.return_value = "n"

        args = argparse.Namespace(
            credential_id="test_api", type="static", storage="file"
        )
        result = cmd_add(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Cancelled" in captured.out

    @patch("framework.credentials.cli._get_store")
    @patch("framework.credentials.cli.input")
    @patch("framework.credentials.cli.getpass")
    def test_add_duplicate_with_overwrite(
        self, mock_getpass, mock_input, mock_get_store, mock_store, sample_credential, capsys
    ):
        """Test adding duplicate credential with overwrite."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)
        mock_input.side_effect = ["y", "api_key", "", ""]
        mock_getpass.getpass.return_value = "new-secret-key"

        args = argparse.Namespace(
            credential_id="test_api", type="static", storage="file"
        )
        result = cmd_add(args)

        assert result == 0
        cred = mock_store.get_credential("test_api")
        assert cred.get_key("api_key") == "new-secret-key"

    @patch("framework.credentials.cli._get_store")
    @patch("framework.credentials.cli.input")
    @patch("framework.credentials.cli.getpass")
    def test_add_with_empty_keys(self, mock_getpass, mock_input, mock_get_store, mock_store, capsys):
        """Test adding credential with no keys."""
        mock_get_store.return_value = mock_store
        mock_input.return_value = ""

        args = argparse.Namespace(
            credential_id="empty_api", type="static", storage="file"
        )
        result = cmd_add(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "At least one key is required" in captured.err

    @patch("framework.credentials.cli._get_store")
    @patch("framework.credentials.cli.input")
    @patch("framework.credentials.cli.getpass")
    def test_add_with_invalid_expiration(
        self, mock_getpass, mock_input, mock_get_store, mock_store, capsys
    ):
        """Test adding credential with invalid expiration format."""
        mock_get_store.return_value = mock_store
        mock_input.side_effect = ["api_key", "invalid-date", ""]
        mock_getpass.getpass.return_value = "secret-key"

        args = argparse.Namespace(
            credential_id="invalid_exp", type="static", storage="file"
        )
        result = cmd_add(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Invalid date format" in captured.out or "Warning" in captured.out

    @patch("framework.credentials.cli._get_store")
    @patch("framework.credentials.cli.input")
    @patch("framework.credentials.cli.getpass")
    def test_add_oauth2_type(self, mock_getpass, mock_input, mock_get_store, mock_store, capsys):
        """Test adding OAuth2 credential type."""
        mock_get_store.return_value = mock_store
        mock_input.side_effect = ["access_token", "", ""]
        mock_getpass.getpass.return_value = "oauth-token"

        args = argparse.Namespace(
            credential_id="oauth_test", type="oauth2", storage="file"
        )
        result = cmd_add(args)

        assert result == 0
        cred = mock_store.get_credential("oauth_test")
        assert cred.credential_type == CredentialType.OAUTH2

    @patch("framework.credentials.cli._get_store")
    def test_add_keyboard_interrupt(self, mock_get_store, mock_store, capsys):
        """Test handling keyboard interrupt during add."""
        mock_get_store.return_value = mock_store

        with patch("framework.credentials.cli.input", side_effect=KeyboardInterrupt):
            args = argparse.Namespace(
                credential_id="interrupted", type="static", storage="file"
            )
            result = cmd_add(args)

            assert result == 1
            captured = capsys.readouterr()
            assert "Cancelled" in captured.err

    @patch("framework.credentials.cli._get_store")
    def test_add_error_handling(self, mock_get_store, capsys):
        """Test error handling in add command."""
        mock_get_store.side_effect = Exception("Storage error")

        args = argparse.Namespace(
            credential_id="error_test", type="static", storage="file"
        )
        with patch("framework.credentials.cli.input", return_value=""):
            result = cmd_add(args)

            assert result == 1
            captured = capsys.readouterr()
            assert "Error adding credential" in captured.err


class TestCmdDelete:
    """Tests for `hive creds delete` command."""

    @patch("framework.credentials.cli._get_store")
    @patch("framework.credentials.cli.input")
    def test_delete_with_confirmation(
        self, mock_input, mock_get_store, mock_store, sample_credential, capsys
    ):
        """Test deleting credential with confirmation."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)
        mock_input.return_value = "y"

        args = argparse.Namespace(credential_id="test_api", force=False)
        result = cmd_delete(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Successfully deleted credential 'test_api'" in captured.out
        assert not mock_store.is_available("test_api")

    @patch("framework.credentials.cli._get_store")
    @patch("framework.credentials.cli.input")
    def test_delete_without_confirmation(
        self, mock_input, mock_get_store, mock_store, sample_credential, capsys
    ):
        """Test deleting credential without confirmation."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)
        mock_input.return_value = "n"

        args = argparse.Namespace(credential_id="test_api", force=False)
        result = cmd_delete(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Cancelled" in captured.out
        assert mock_store.is_available("test_api")

    @patch("framework.credentials.cli._get_store")
    def test_delete_with_force_flag(
        self, mock_get_store, mock_store, sample_credential, capsys
    ):
        """Test deleting credential with --force flag."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)

        args = argparse.Namespace(credential_id="test_api", force=True)
        result = cmd_delete(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Successfully deleted credential 'test_api'" in captured.out
        assert not mock_store.is_available("test_api")

    @patch("framework.credentials.cli._get_store")
    def test_delete_nonexistent_credential(self, mock_get_store, mock_store, capsys):
        """Test deleting non-existent credential."""
        mock_get_store.return_value = mock_store

        args = argparse.Namespace(credential_id="nonexistent", force=False)
        result = cmd_delete(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    @patch("framework.credentials.cli._get_store")
    def test_delete_keyboard_interrupt(self, mock_get_store, mock_store, sample_credential, capsys):
        """Test handling keyboard interrupt during delete."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)

        with patch("framework.credentials.cli.input", side_effect=KeyboardInterrupt):
            args = argparse.Namespace(credential_id="test_api", force=False)
            result = cmd_delete(args)

            assert result == 1
            captured = capsys.readouterr()
            assert "Cancelled" in captured.err

    @patch("framework.credentials.cli._get_store")
    def test_delete_error_handling(self, mock_get_store, capsys):
        """Test error handling in delete command."""
        mock_get_store.side_effect = Exception("Storage error")

        args = argparse.Namespace(credential_id="test_api", force=False)
        result = cmd_delete(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error deleting credential" in captured.err


class TestCmdTest:
    """Tests for `hive creds test` command."""

    @patch("framework.credentials.cli._get_store")
    def test_test_valid_credential(
        self, mock_get_store, mock_store, sample_credential, capsys
    ):
        """Test validating a valid credential."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)
        mock_store.validate_credential = MagicMock(return_value=True)
        mock_store.validate_for_usage = MagicMock(return_value=[])

        args = argparse.Namespace(credential_id="test_api")
        result = cmd_test(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Status: valid" in captured.out
        assert "Credential is valid and ready to use" in captured.out

    @patch("framework.credentials.cli._get_store")
    def test_test_invalid_credential(
        self, mock_get_store, mock_store, sample_credential, capsys
    ):
        """Test validating an invalid credential."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)
        mock_store.validate_credential = MagicMock(return_value=False)
        mock_store.validate_for_usage = MagicMock(return_value=[])

        args = argparse.Namespace(credential_id="test_api")
        result = cmd_test(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Status: invalid" in captured.out
        assert "Credential validation failed" in captured.out

    @patch("framework.credentials.cli._get_store")
    def test_test_nonexistent_credential(self, mock_get_store, mock_store, capsys):
        """Test testing non-existent credential."""
        mock_get_store.return_value = mock_store

        args = argparse.Namespace(credential_id="nonexistent")
        result = cmd_test(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    @patch("framework.credentials.cli._get_store")
    def test_test_with_expired_keys(
        self, mock_get_store, mock_store, expired_credential, capsys
    ):
        """Test credential with expired keys."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(expired_credential)
        mock_store.validate_credential = MagicMock(return_value=True)
        mock_store.validate_for_usage = MagicMock(return_value=[])

        args = argparse.Namespace(credential_id="expired_api")
        result = cmd_test(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Warning: Expired keys" in captured.out

    @patch("framework.credentials.cli._get_store")
    def test_test_with_usage_errors(
        self, mock_get_store, mock_store, sample_credential, capsys
    ):
        """Test credential with usage validation errors."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)
        mock_store.validate_credential = MagicMock(return_value=True)
        mock_store.validate_for_usage = MagicMock(
            return_value=["Missing required key: client_id"]
        )

        args = argparse.Namespace(credential_id="test_api")
        result = cmd_test(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Validation errors" in captured.out
        assert "Missing required key" in captured.out

    @patch("framework.credentials.cli._get_store")
    def test_test_error_handling(self, mock_get_store, capsys):
        """Test error handling in test command."""
        mock_get_store.side_effect = Exception("Storage error")

        args = argparse.Namespace(credential_id="test_api")
        result = cmd_test(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error testing credential" in captured.err


class TestCmdRefresh:
    """Tests for `hive creds refresh` command."""

    @patch("framework.credentials.cli._get_store")
    def test_refresh_oauth2_credential(
        self, mock_get_store, mock_store, oauth_credential, capsys
    ):
        """Test refreshing an OAuth2 credential."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(oauth_credential)

        new_expires = datetime.now(UTC) + timedelta(hours=2)
        refreshed_cred = CredentialObject(
            id="test_oauth",
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token",
                    value=SecretStr("new-token"),
                    expires_at=new_expires,
                )
            },
        )
        mock_store.refresh_credential = MagicMock(return_value=refreshed_cred)

        args = argparse.Namespace(credential_id="test_oauth")
        result = cmd_refresh(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Successfully refreshed" in captured.out
        assert "New expiration" in captured.out

    @patch("framework.credentials.cli._get_store")
    def test_refresh_non_oauth2_credential(
        self, mock_get_store, mock_store, sample_credential, capsys
    ):
        """Test refreshing a non-OAuth2 credential fails."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)

        args = argparse.Namespace(credential_id="test_api")
        result = cmd_refresh(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not an OAuth2 credential" in captured.err

    @patch("framework.credentials.cli._get_store")
    def test_refresh_nonexistent_credential(self, mock_get_store, mock_store, capsys):
        """Test refreshing non-existent credential."""
        mock_get_store.return_value = mock_store

        args = argparse.Namespace(credential_id="nonexistent")
        result = cmd_refresh(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    @patch("framework.credentials.cli._get_store")
    def test_refresh_failure(self, mock_get_store, mock_store, oauth_credential, capsys):
        """Test refresh failure handling."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(oauth_credential)
        mock_store.refresh_credential = MagicMock(return_value=None)

        args = argparse.Namespace(credential_id="test_oauth")
        result = cmd_refresh(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Failed to refresh credential" in captured.err

    @patch("framework.credentials.cli._get_store")
    def test_refresh_no_expiration(
        self, mock_get_store, mock_store, oauth_credential, capsys
    ):
        """Test refreshing credential without expiration."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(oauth_credential)

        refreshed_cred = CredentialObject(
            id="test_oauth",
            credential_type=CredentialType.OAUTH2,
            keys={
                "access_token": CredentialKey(
                    name="access_token", value=SecretStr("new-token"), expires_at=None
                )
            },
        )
        mock_store.refresh_credential = MagicMock(return_value=refreshed_cred)

        args = argparse.Namespace(credential_id="test_oauth")
        result = cmd_refresh(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Successfully refreshed (no expiration set)" in captured.out

    @patch("framework.credentials.cli._get_store")
    def test_refresh_error_handling(self, mock_get_store, capsys):
        """Test error handling in refresh command."""
        mock_get_store.side_effect = Exception("Storage error")

        args = argparse.Namespace(credential_id="test_oauth")
        result = cmd_refresh(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error refreshing credential" in captured.err


class TestHelpCommands:
    """Tests for help command output."""

    def test_creds_help(self, capsys):
        """Test `hive creds --help` command."""
        parser = argparse.ArgumentParser(prog="hive")
        subparsers = parser.add_subparsers(dest="command")
        register_commands(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["creds", "--help"])

        assert exc_info.value.code == 0, "Help command should exit with code 0"
        captured = capsys.readouterr()
        assert "Manage stored credentials" in captured.out
        assert "list" in captured.out
        assert "show" in captured.out
        assert "add" in captured.out
        assert "delete" in captured.out
        assert "test" in captured.out
        assert "refresh" in captured.out

    def test_creds_list_help(self, capsys):
        """Test `hive creds list --help` command."""
        parser = argparse.ArgumentParser(prog="hive")
        subparsers = parser.add_subparsers(dest="command")
        register_commands(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["creds", "list", "--help"])

        assert exc_info.value.code == 0, "Help command should exit with code 0"
        captured = capsys.readouterr()
        assert "Display all credentials" in captured.out
        assert "--json" in captured.out

    def test_creds_show_help(self, capsys):
        """Test `hive creds show --help` command."""
        parser = argparse.ArgumentParser(prog="hive")
        subparsers = parser.add_subparsers(dest="command")
        register_commands(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["creds", "show", "--help"])

        assert exc_info.value.code == 0, "Help command should exit with code 0"
        captured = capsys.readouterr()
        assert "Display detailed information" in captured.out
        assert "credential_id" in captured.out
        assert "--json" in captured.out

    def test_creds_add_help(self, capsys):
        """Test `hive creds add --help` command."""
        parser = argparse.ArgumentParser(prog="hive")
        subparsers = parser.add_subparsers(dest="command")
        register_commands(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["creds", "add", "--help"])

        assert exc_info.value.code == 0, "Help command should exit with code 0"
        captured = capsys.readouterr()
        assert "Interactively create and save" in captured.out
        assert "credential_id" in captured.out
        assert "--type" in captured.out
        assert "--storage" in captured.out

    def test_creds_delete_help(self, capsys):
        """Test `hive creds delete --help` command."""
        parser = argparse.ArgumentParser(prog="hive")
        subparsers = parser.add_subparsers(dest="command")
        register_commands(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["creds", "delete", "--help"])

        assert exc_info.value.code == 0, "Help command should exit with code 0"
        captured = capsys.readouterr()
        assert "Remove a credential" in captured.out
        assert "credential_id" in captured.out
        assert "--force" in captured.out

    def test_creds_test_help(self, capsys):
        """Test `hive creds test --help` command."""
        parser = argparse.ArgumentParser(prog="hive")
        subparsers = parser.add_subparsers(dest="command")
        register_commands(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["creds", "test", "--help"])

        assert exc_info.value.code == 0, "Help command should exit with code 0"
        captured = capsys.readouterr()
        assert "Validate that a credential exists" in captured.out
        assert "credential_id" in captured.out

    def test_creds_refresh_help(self, capsys):
        """Test `hive creds refresh --help` command."""
        parser = argparse.ArgumentParser(prog="hive")
        subparsers = parser.add_subparsers(dest="command")
        register_commands(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["creds", "refresh", "--help"])

        assert exc_info.value.code == 0, "Help command should exit with code 0"
        captured = capsys.readouterr()
        assert "Manually trigger refresh" in captured.out
        assert "credential_id" in captured.out


class TestSnapshotOutputs:
    """Snapshot-style output tests for exact formatting verification."""

    @patch("framework.credentials.cli._get_store")
    def test_list_empty_output_snapshot(self, mock_get_store, mock_store, capsys):
        """Test exact output format for empty list."""
        mock_get_store.return_value = mock_store

        args = argparse.Namespace(json=False)
        exit_code = cmd_list(args)

        assert exit_code == 0, "Expected exit code 0"
        captured = capsys.readouterr()
        expected_output = "No credentials found.\n"
        assert captured.out == expected_output

    @patch("framework.credentials.cli._get_store")
    def test_list_empty_json_snapshot(self, mock_get_store, mock_store, capsys):
        """Test exact JSON output format for empty list."""
        mock_get_store.return_value = mock_store

        args = argparse.Namespace(json=True)
        exit_code = cmd_list(args)

        assert exit_code == 0, "Expected exit code 0"
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == {"credentials": []}

    @patch("framework.credentials.cli._get_store")
    def test_delete_success_output_snapshot(
        self, mock_get_store, mock_store, sample_credential, capsys
    ):
        """Test exact output format for successful delete."""
        mock_get_store.return_value = mock_store
        mock_store.save_credential(sample_credential)

        args = argparse.Namespace(credential_id="test_api", force=True)
        exit_code = cmd_delete(args)

        assert exit_code == 0, "Expected exit code 0"
        captured = capsys.readouterr()
        expected_output = "Successfully deleted credential 'test_api'\n"
        assert captured.out == expected_output

    @patch("framework.credentials.cli._get_store")
    @patch("framework.credentials.cli.input")
    @patch("framework.credentials.cli.getpass")
    def test_add_success_output_snapshot(
        self, mock_getpass, mock_input, mock_get_store, mock_store, capsys
    ):
        """Test exact output format for successful add."""
        mock_get_store.return_value = mock_store
        mock_input.side_effect = ["api_key", "", ""]
        mock_getpass.getpass.return_value = "secret-value"

        args = argparse.Namespace(
            credential_id="new_cred", type="static", storage="file"
        )
        exit_code = cmd_add(args)

        assert exit_code == 0, "Expected exit code 0"
        captured = capsys.readouterr()
        assert "Successfully saved credential 'new_cred'\n" in captured.out
