"""
tests for credential key rotation.

tests the rotation mechanism for re-encrypting credentials with a new key.
"""

import pytest
from pydantic import SecretStr

from framework.credentials.models import CredentialKey, CredentialObject
from framework.credentials.storage import EncryptedFileStorage
from framework.credentials.store import CredentialStore


class TestKeyRotation:
    """test encryption key rotation"""

    @pytest.fixture
    def storage_path(self, tmp_path):
        """get temp path for storage"""
        return tmp_path / "credentials"

    @pytest.fixture
    def initial_key(self):
        """generate an initial encryption key"""
        from cryptography.fernet import Fernet

        return Fernet.generate_key()

    @pytest.fixture
    def new_key(self):
        """generate a new encryption key for rotation"""
        from cryptography.fernet import Fernet

        return Fernet.generate_key()

    @pytest.fixture
    def sample_credential(self):
        """create a sample credential for testing"""
        return CredentialObject(
            id="test-cred",
            keys={
                "api_key": CredentialKey(
                    name="api_key",
                    value=SecretStr("super-secret-value-123"),
                ),
                "secret": CredentialKey(
                    name="secret",
                    value=SecretStr("another-secret"),
                ),
            },
        )

    def test_rotate_key_success(self, storage_path, initial_key, new_key, sample_credential):
        """test successful key rotation"""
        # create storage with initial key
        storage = EncryptedFileStorage(storage_path, encryption_key=initial_key)

        # save a credential
        storage.save(sample_credential)

        # verify we can load it
        loaded = storage.load("test-cred")
        assert loaded is not None
        assert loaded.get_key("api_key") == "super-secret-value-123"

        # rotate to new key
        results = storage.rotate_key(new_key)

        assert results["test-cred"] is True

        # verify we can still load with new key
        loaded_after = storage.load("test-cred")
        assert loaded_after is not None
        assert loaded_after.get_key("api_key") == "super-secret-value-123"
        assert loaded_after.get_key("secret") == "another-secret"

    def test_rotate_key_multiple_credentials(self, storage_path, initial_key, new_key):
        """test rotating key for multiple credentials"""
        storage = EncryptedFileStorage(storage_path, encryption_key=initial_key)

        # save multiple credentials
        for i in range(5):
            cred = CredentialObject(
                id=f"cred-{i}",
                keys={
                    "key": CredentialKey(name="key", value=SecretStr(f"value-{i}")),
                },
            )
            storage.save(cred)

        # rotate key
        results = storage.rotate_key(new_key)

        # all should succeed
        assert len(results) == 5
        assert all(success for success in results.values())

        # verify all can still be loaded
        for i in range(5):
            loaded = storage.load(f"cred-{i}")
            assert loaded is not None
            assert loaded.get_key("key") == f"value-{i}"

    def test_rotate_key_empty_storage(self, storage_path, initial_key, new_key):
        """test rotating with no credentials"""
        storage = EncryptedFileStorage(storage_path, encryption_key=initial_key)

        # no credentials saved
        results = storage.rotate_key(new_key)

        assert results == {}

    def test_rotate_key_invalid_format(self, storage_path, initial_key):
        """test that invalid key format is rejected"""
        storage = EncryptedFileStorage(storage_path, encryption_key=initial_key)

        with pytest.raises(ValueError) as exc:
            storage.rotate_key(b"too-short")

        assert "invalid" in str(exc.value).lower()

    def test_rotate_key_old_key_no_longer_works(self, storage_path, initial_key, new_key):
        """after rotation, old key should not decrypt credentials"""
        storage = EncryptedFileStorage(storage_path, encryption_key=initial_key)

        # save credential
        cred = CredentialObject(
            id="test",
            keys={"key": CredentialKey(name="key", value=SecretStr("secret"))},
        )
        storage.save(cred)

        # rotate to new key
        storage.rotate_key(new_key)

        # create new storage instance with old key
        old_storage = EncryptedFileStorage(storage_path, encryption_key=initial_key)

        # should fail to decrypt (raises CredentialDecryptionError)
        from framework.credentials.models import CredentialDecryptionError

        with pytest.raises(CredentialDecryptionError):
            old_storage.load("test")


class TestKeyRotationViaStore:
    """test key rotation through the CredentialStore interface"""

    @pytest.fixture
    def storage_path(self, tmp_path):
        return tmp_path / "credentials"

    @pytest.fixture
    def initial_key(self):
        from cryptography.fernet import Fernet

        return Fernet.generate_key()

    @pytest.fixture
    def new_key(self):
        from cryptography.fernet import Fernet

        return Fernet.generate_key()

    def test_store_rotate_key(self, storage_path, initial_key, new_key):
        """test rotating key via CredentialStore"""
        storage = EncryptedFileStorage(storage_path, encryption_key=initial_key)
        store = CredentialStore(storage=storage)

        # save credential via store
        cred = CredentialObject(
            id="api-key",
            keys={"token": CredentialKey(name="token", value=SecretStr("my-token"))},
        )
        store.save_credential(cred)

        # rotate
        results = store.rotate_encryption_key(new_key)

        assert results["api-key"] is True

        # cache should be cleared, reload from storage
        loaded = store.get_credential("api-key")
        assert loaded is not None
        assert loaded.get_key("token") == "my-token"

    def test_store_rotate_key_wrong_storage_type(self):
        """test that rotation fails with non-encrypted storage"""
        from framework.credentials.storage import InMemoryStorage

        store = CredentialStore(storage=InMemoryStorage())

        with pytest.raises(ValueError) as exc:
            store.rotate_encryption_key(b"some-key")

        assert "EncryptedFileStorage" in str(exc.value)
