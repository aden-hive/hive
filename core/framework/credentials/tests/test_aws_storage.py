import json
from unittest.mock import MagicMock, patch

import pytest
from core.framework.credentials.models import CredentialKey, CredentialObject
from core.framework.credentials.storage import AWSSecretsManagerStorage
from core.framework.credentials.store import CredentialStore
from pydantic import SecretStr


class TestAWSSecretsManagerStorage:
    @pytest.fixture
    def mock_boto3(self):
        with patch("boto3.client") as mock:
            # Setup common exception mocks
            mock_client = mock.return_value
            mock_client.exceptions.ResourceExistsException = type(
                "ResourceExistsException", (Exception,), {}
            )
            mock_client.exceptions.ResourceNotFoundException = type(
                "ResourceNotFoundException", (Exception,), {}
            )
            yield mock

    @pytest.fixture
    def storage(self, mock_boto3):
        return AWSSecretsManagerStorage(region_name="us-east-1", prefix="test/")

    def test_get_secret_name(self, storage):
        assert storage._get_secret_name("my-cred") == "test/my-cred"

    def test_save_new_secret(self, storage, mock_boto3):
        mock_client = mock_boto3.return_value
        cred = CredentialObject(
            id="my-cred",
            keys={"api_key": CredentialKey(name="api_key", value=SecretStr("secret-val"))},
        )

        storage.save(cred)

        mock_client.create_secret.assert_called_once()
        kwargs = mock_client.create_secret.call_args[1]
        assert kwargs["Name"] == "test/my-cred"
        assert "secret-val" in kwargs["SecretString"]

    def test_save_existing_secret(self, storage, mock_boto3):
        mock_client = mock_boto3.return_value
        # Simulate secret already exists on create attempt
        mock_client.create_secret.side_effect = mock_client.exceptions.ResourceExistsException

        cred = CredentialObject(
            id="my-cred",
            keys={"api_key": CredentialKey(name="api_key", value=SecretStr("new-val"))},
        )
        storage.save(cred)

        mock_client.put_secret_value.assert_called_once()
        kwargs = mock_client.put_secret_value.call_args[1]
        assert kwargs["SecretId"] == "test/my-cred"
        assert "new-val" in kwargs["SecretString"]

    def test_load_secret(self, storage, mock_boto3):
        mock_client = mock_boto3.return_value
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps(
                {
                    "id": "my-cred",
                    "keys": {"api_key": {"name": "api_key", "value": "secret-val"}},
                }
            )
        }

        cred = storage.load("my-cred")
        assert cred is not None
        assert cred.id == "my-cred"
        assert cred.get_key("api_key") == "secret-val"

    def test_load_secret_not_found(self, storage, mock_boto3):
        mock_client = mock_boto3.return_value
        mock_client.get_secret_value.side_effect = mock_client.exceptions.ResourceNotFoundException

        assert storage.load("missing") is None

    def test_delete_secret(self, storage, mock_boto3):
        mock_client = mock_boto3.return_value

        assert storage.delete("my-cred")
        mock_client.delete_secret.assert_called_once_with(
            SecretId="test/my-cred", RecoveryWindowInDays=7
        )

    def test_list_all(self, storage, mock_boto3):
        mock_client = mock_boto3.return_value
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {"SecretList": [{"Name": "test/cred1"}, {"Name": "test/cred2"}]},
            {"SecretList": [{"Name": "other/cred3"}]},  # Should be filtered out
        ]

        creds = storage.list_all()
        assert "cred1" in creds
        assert "cred2" in creds
        assert "cred3" not in creds

    def test_exists(self, storage, mock_boto3):
        mock_client = mock_boto3.return_value

        assert storage.exists("my-cred")
        mock_client.describe_secret.assert_called_once_with(SecretId="test/my-cred")

    def test_exists_not_found(self, storage, mock_boto3):
        mock_client = mock_boto3.return_value
        mock_client.describe_secret.side_effect = mock_client.exceptions.ResourceNotFoundException

        assert not storage.exists("missing")


class TestCredentialStoreAWS:
    """Test CredentialStore integration with AWS storage."""

    @patch("boto3.client")
    def test_with_aws_storage_factory(self, mock_boto3):
        store = CredentialStore.with_aws_storage(region_name="us-west-2", prefix="hive/")
        assert isinstance(store._storage, AWSSecretsManagerStorage)
        assert store._storage.region_name == "us-west-2"
        assert store._storage.prefix == "hive/"
