"""
Tests for credential storage path traversal hardening.

Validates that EncryptedFileStorage._cred_path() prevents path traversal
attacks via malicious credential IDs.
"""

import os

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def storage(tmp_path):
    """Create an EncryptedFileStorage instance with a temp directory."""
    os.environ["HIVE_CREDENTIAL_KEY"] = Fernet.generate_key().decode()
    from framework.credentials.storage import EncryptedFileStorage

    return EncryptedFileStorage(base_path=str(tmp_path))


class TestCredPathSanitization:
    """Verify _cred_path() hardens against path traversal."""

    def test_normal_id(self, storage):
        """Normal alphanumeric IDs should work."""
        path = storage._cred_path("github_oauth")
        assert path.name == "github_oauth.enc"
        assert "credentials" in str(path)

    def test_hyphenated_id(self, storage):
        """Hyphens are allowed."""
        path = storage._cred_path("brave-search")
        assert path.name == "brave-search.enc"

    def test_path_traversal_dots(self, storage):
        """../../etc/passwd should be sanitized to underscores."""
        path = storage._cred_path("../../etc/passwd")
        assert ".." not in path.name
        assert "/" not in str(path.name)
        assert "\\" not in str(path.name)
        # The name should be sanitized to something like ______etc_passwd.enc
        assert path.name == "______etc_passwd.enc"

    def test_backslash_traversal(self, storage):
        """Backslash traversal should be sanitized."""
        path = storage._cred_path("..\\..\\windows\\system32")
        assert "\\" not in path.name
        assert ".." not in path.name

    def test_nul_byte_stripped(self, storage):
        """NUL bytes should be stripped before sanitization."""
        path = storage._cred_path("test\x00evil")
        assert "\x00" not in str(path)
        assert path.name == "testevil.enc"

    def test_empty_after_sanitization_raises(self, storage):
        """IDs that produce only underscores still resolve (the regex allows _)."""
        # ../../../ becomes _________ which is valid (not empty)
        path = storage._cred_path("../../../")
        assert ".." not in path.name
        assert "/" not in str(path.name)

    def test_slash_only_sanitized(self, storage):
        """Pure slash IDs become underscores after sanitization."""
        path = storage._cred_path("///")
        assert path.name == "___.enc"

    def test_dots_only(self, storage):
        """Dots-only credential IDs should be sanitized to underscores."""
        path = storage._cred_path("...")
        assert path.name == "___.enc"

    def test_unicode_normalized(self, storage):
        """Unicode characters should be replaced with underscores."""
        path = storage._cred_path("tëst_crédential")
        # Non-ASCII chars become underscores
        assert "ë" not in path.name
        assert "é" not in path.name

    def test_url_encoded_traversal(self, storage):
        """URL-encoded path components should be sanitized."""
        path = storage._cred_path("%2e%2e%2f%2e%2e%2fetc%2fpasswd")
        assert ".." not in path.name
        assert "/" not in path.name

    def test_resolved_path_stays_within_creds_dir(self, storage):
        """The resolved path must be within the credentials directory."""
        # Normal case: stays within
        path = storage._cred_path("valid_credential")
        creds_dir = (storage.base_path / "credentials").resolve()
        assert path.resolve().is_relative_to(creds_dir)
