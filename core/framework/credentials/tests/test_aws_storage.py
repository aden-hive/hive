from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Generator
from unittest.mock import MagicMock, patch

import pytest
from framework.credentials.models import CredentialKey, CredentialObject
from framework.credentials.storage import AWSSecretsManagerStorage
from framework.credentials.store import CredentialStore
from pydantic import SecretStr

if TYPE_CHECKING:
    from botocore.client import BaseClient


class TestAWSSecretsManagerStorage:
    @pytest.fixture
    def mock_boto3(self) -> Generator[MagicMock, None, None]:
        """Mock boto3 client with common AWS Secrets Manager exceptions."""
        with patch("boto3.client") as mock:
            mock_client = mock.return_value
            # Setup exception mocks that match botocore behavior
            mock_client.exceptions.ResourceExistsException = type(
                "ResourceExistsException", (Exception,), {}
            )
            mock_client.exceptions.ResourceNotFoundException = type(
                "ResourceNotFoundException", (Exception,), {}
            )
            yield mock

    @pytest.fixture
    def storage(self, mock_boto3: MagicMock) -> AWSSecretsManagerStorage:
        """Initialize storage with mocked client."""
        return AWSSecretsManagerStorage(region_name="us-east-1", prefix="test/")

    def test_get_secret_name(self, storage: AWSSecretsManagerStorage) -> None:
        assert storage._get_secret_name("my-cred") == "test/my-cred"

    def test_save_new_secret(self, storage: AWSSecretsManagerStorage, mock_boto3: MagicMock) -> None:
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

    def test_save_existing_secret(self, storage: AWSSecretsManagerStorage, mock_boto3: MagicMock) -> None:
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

    def test_load_secret(self, storage: AWSSecretsManagerStorage, mock_boto3: MagicMock) -> None:
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

    def test_load_secret_not_found(self, storage: AWSSecretsManagerStorage, mock_boto3: MagicMock) -> None:
        mock_client = mock_boto3.return_value
        mock_client.get_secret_value.side_effect = mock_client.exceptions.ResourceNotFoundException

        assert storage.load("missing") is None

    def test_load_all_for_provider(self, storage: AWSSecretsManagerStorage, mock_boto3: MagicMock) -> None:
        mock_client = mock_boto3.return_value

        # Mock list_all response
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {"SecretList": [{"Name": "test/cred1"}, {"Name": "test/cred2"}]},
        ]

        # Mock load responses
        def side_effect(SecretId: str) -> dict[str, str]:
            pid = "google" if "cred1" in SecretId else "slack"
            return {
                "SecretString": json.dumps(
                    {
                        "id": SecretId.split("/")[-1],
                        "provider_id": pid,
                        "keys": {"k": {"name": "k", "value": "v"}},
                    }
                )
            }

        mock_client.get_secret_value.side_effect = side_effect

        creds = storage.load_all_for_provider("google")
        assert len(creds) == 1
        assert creds[0].id == "cred1"

    def test_load_by_alias(self, storage: AWSSecretsManagerStorage, mock_boto3: MagicMock) -> None:
        mock_client = mock_boto3.return_value

        # Mock list_all response
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {"SecretList": [{"Name": "test/cred1"}]},
        ]

        # Mock load response with alias
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps(
                {
                    "id": "cred1",
                    "provider_id": "google",
                    "tags": ["personal"],
                    "keys": {"_alias": {"name": "_alias", "value": "my-alias"}},
                }
            )
        }

        # Match by special _alias key
        cred = storage.load_by_alias("google", "my-alias")
        assert cred is not None
        assert cred.id == "cred1"

        # Match by tag
        cred = storage.load_by_alias("google", "personal")
        assert cred is not None
        assert cred.id == "cred1"

    def test_delete_secret(self, storage: AWSSecretsManagerStorage, mock_boto3: MagicMock) -> None:
        mock_client = mock_boto3.return_value

        assert storage.delete("my-cred")
        mock_client.delete_secret.assert_called_once_with(
            SecretId="test/my-cred", RecoveryWindowInDays=7
        )

    def test_list_all(self, storage: AWSSecretsManagerStorage, mock_boto3: MagicMock) -> None:
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

    def test_exists(self, storage: AWSSecretsManagerStorage, mock_boto3: MagicMock) -> None:
        mock_client = mock_boto3.return_value

        assert storage.exists("my-cred")
        mock_client.describe_secret.assert_called_once_with(SecretId="test/my-cred")

    def test_exists_not_found(self, storage: AWSSecretsManagerStorage, mock_boto3: MagicMock) -> None:
        mock_client = mock_boto3.return_value
        mock_client.describe_secret.side_effect = mock_client.exceptions.ResourceNotFoundException

        assert not storage.exists("missing")


class TestCredentialStoreAWS:
    """Test CredentialStore integration with AWS storage."""

    @patch("boto3.client")
    def test_with_aws_storage_factory(self, mock_boto3: MagicMock) -> None:
        store = CredentialStore.with_aws_storage(region_name="us-west-2", prefix="hive/")
        assert isinstance(store._storage, AWSSecretsManagerStorage)
        assert store._storage.region_name == "us-west-2"
        assert store._storage.prefix == "hive/"
