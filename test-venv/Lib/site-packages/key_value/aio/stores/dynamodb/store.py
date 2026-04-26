from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, overload

from typing_extensions import override

from key_value.aio._utils.managed_entry import ManagedEntry
from key_value.aio.stores.base import (
    BaseContextManagerStore,
    BaseStore,
)

try:
    import aioboto3
    from aioboto3.session import Session
except ImportError as e:
    msg = "DynamoDBStore requires py-key-value-aio[dynamodb]"
    raise ImportError(msg) from e

# aioboto3 generates types at runtime, so we use AioBaseClient at runtime but DynamoDBClient during static type checking
if TYPE_CHECKING:
    from types_aiobotocore_dynamodb.client import DynamoDBClient
else:
    from aiobotocore.client import AioBaseClient as DynamoDBClient

DEFAULT_PAGE_SIZE = 1000
PAGE_LIMIT = 1000


# Private helper functions to encapsulate DynamoDB/boto3 client interactions with type ignore comments
# These are module-level functions (not methods) so they are not exported with the store class


def _create_dynamodb_session(
    *,
    region_name: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    aws_session_token: str | None = None,
) -> Session:
    """Create an aioboto3 session for DynamoDB."""
    return aioboto3.Session(
        region_name=region_name,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        aws_session_token=aws_session_token,
    )


def _create_dynamodb_client_context(session: Session, *, endpoint_url: str | None = None) -> Any:
    """Create a DynamoDB client context manager from a session."""
    return session.client(service_name="dynamodb", endpoint_url=endpoint_url)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


async def _describe_dynamodb_table(client: DynamoDBClient, table_name: str) -> bool:
    """Check if a DynamoDB table exists.

    Returns:
        True if the table exists, False otherwise.
    """
    try:
        await client.describe_table(TableName=table_name)
    except client.exceptions.ResourceNotFoundException:
        return False
    else:
        return True


async def _create_dynamodb_table(client: DynamoDBClient, table_name: str, *, table_config: dict[str, Any] | None = None) -> None:
    """Create a DynamoDB table with the standard schema.

    Args:
        client: The DynamoDB client.
        table_name: The name of the table to create.
        table_config: Additional configuration to pass to create_table().
    """
    # Start with user-provided configuration, then overlay required parameters
    create_table_params: dict[str, Any] = {**(table_config or {})}

    # Override with required configuration that cannot be changed
    create_table_params.update(
        {
            "TableName": table_name,
            "KeySchema": [
                {"AttributeName": "collection", "KeyType": "HASH"},  # Partition key
                {"AttributeName": "key", "KeyType": "RANGE"},  # Sort key
            ],
            "AttributeDefinitions": [
                {"AttributeName": "collection", "AttributeType": "S"},
                {"AttributeName": "key", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",  # On-demand billing
        }
    )

    await client.create_table(**create_table_params)

    # Wait for table to be active
    waiter = client.get_waiter("table_exists")
    await waiter.wait(TableName=table_name)


async def _describe_dynamodb_ttl(client: DynamoDBClient, table_name: str) -> str | None:
    """Get the TTL status of a DynamoDB table.

    Returns:
        The TTL status string, or None if not available.
    """
    ttl_response = await client.describe_time_to_live(TableName=table_name)
    return ttl_response.get("TimeToLiveDescription", {}).get("TimeToLiveStatus")


async def _enable_dynamodb_ttl(client: DynamoDBClient, table_name: str, attribute_name: str = "ttl") -> None:
    """Enable TTL on a DynamoDB table."""
    await client.update_time_to_live(
        TableName=table_name,
        TimeToLiveSpecification={
            "Enabled": True,
            "AttributeName": attribute_name,
        },
    )


async def _put_dynamodb_item(client: DynamoDBClient, table_name: str, item: dict[str, Any]) -> None:
    """Put an item into a DynamoDB table."""
    await client.put_item(
        TableName=table_name,
        Item=item,
    )


async def _delete_dynamodb_item(client: DynamoDBClient, table_name: str, key: dict[str, Any]) -> dict[str, Any] | None:
    """Delete an item from a DynamoDB table.

    Returns:
        The deleted item attributes if ReturnValues=ALL_OLD was used, or None.
    """
    response = await client.delete_item(
        TableName=table_name,
        Key=key,
        ReturnValues="ALL_OLD",
    )
    return response.get("Attributes")


class DynamoDBStore(BaseContextManagerStore, BaseStore):
    """DynamoDB-based key-value store.

    This store uses a single DynamoDB table with a composite primary key:
    - collection (partition key)
    - key (sort key)
    """

    _session: aioboto3.Session
    _table_name: str
    _endpoint_url: str | None
    _raw_client: Any  # DynamoDB client from aioboto3
    _client: DynamoDBClient | None
    _table_config: dict[str, Any]
    _auto_create: bool

    @overload
    def __init__(
        self,
        *,
        client: DynamoDBClient,
        table_name: str,
        default_collection: str | None = None,
        table_config: dict[str, Any] | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the DynamoDB store.

        Args:
            client: The DynamoDB client to use. You must have entered the context manager before passing this in.
            table_name: The name of the DynamoDB table to use.
            default_collection: The default collection to use if no collection is provided.
            table_config: Additional configuration to pass to create_table(). Merged with defaults.
            auto_create: Whether to automatically create the table if it doesn't exist. Defaults to True.
        """

    @overload
    def __init__(
        self,
        *,
        table_name: str,
        region_name: str | None = None,
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_session_token: str | None = None,
        default_collection: str | None = None,
        table_config: dict[str, Any] | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the DynamoDB store.

        Args:
            table_name: The name of the DynamoDB table to use.
            region_name: AWS region name. Defaults to None (uses AWS default).
            endpoint_url: Custom endpoint URL (useful for local DynamoDB). Defaults to None.
            aws_access_key_id: AWS access key ID. Defaults to None (uses AWS default credentials).
            aws_secret_access_key: AWS secret access key. Defaults to None (uses AWS default credentials).
            aws_session_token: AWS session token. Defaults to None (uses AWS default credentials).
            default_collection: The default collection to use if no collection is provided.
            table_config: Additional configuration to pass to create_table(). Merged with defaults.
            auto_create: Whether to automatically create the table if it doesn't exist. Defaults to True.
        """

    def __init__(
        self,
        *,
        client: DynamoDBClient | None = None,
        table_name: str,
        region_name: str | None = None,
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_session_token: str | None = None,
        default_collection: str | None = None,
        table_config: dict[str, Any] | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the DynamoDB store.

        Args:
            client: The DynamoDB client to use. If provided, the store will not manage the client's
                lifecycle (will not enter/exit its context manager). The caller is responsible for
                managing the client's lifecycle and must ensure the client is already entered.
            table_name: The name of the DynamoDB table to use.
            region_name: AWS region name. Defaults to None (uses AWS default).
            endpoint_url: Custom endpoint URL (useful for local DynamoDB). Defaults to None.
            aws_access_key_id: AWS access key ID. Defaults to None (uses AWS default credentials).
            aws_secret_access_key: AWS secret access key. Defaults to None (uses AWS default credentials).
            aws_session_token: AWS session token. Defaults to None (uses AWS default credentials).
            default_collection: The default collection to use if no collection is provided.
            table_config: Additional configuration to pass to create_table(). Merged with defaults.
                Examples: SSESpecification, Tags, StreamSpecification, etc.
                Note: Critical parameters (TableName, KeySchema, AttributeDefinitions, BillingMode)
                cannot be overridden as they are required for store operation.
            auto_create: Whether to automatically create the table if it doesn't exist. Defaults to True.
                When False, raises ValueError if the table doesn't exist.
        """
        self._table_name = table_name
        self._table_config = table_config or {}
        self._auto_create = auto_create
        client_provided = client is not None

        if client:
            self._client = client
            self._raw_client = None
        else:
            session = _create_dynamodb_session(
                region_name=region_name,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                aws_session_token=aws_session_token,
            )

            self._raw_client = _create_dynamodb_client_context(session, endpoint_url=endpoint_url)

            self._client = None

        super().__init__(
            default_collection=default_collection,
            client_provided_by_user=client_provided,
        )

    @property
    def _connected_client(self) -> DynamoDBClient:
        if not self._client:
            msg = "Client not connected"
            raise ValueError(msg)
        return self._client

    @override
    async def _setup(self) -> None:
        """Setup the DynamoDB client and ensure table exists."""
        # Register client cleanup if we own the client
        if not self._client_provided_by_user and self._raw_client is not None:
            self._client = await self._exit_stack.enter_async_context(self._raw_client)

        table_exists = await _describe_dynamodb_table(self._connected_client, self._table_name)

        if not table_exists:
            if not self._auto_create:
                msg = f"Table '{self._table_name}' does not exist. Either create the table manually or set auto_create=True."
                raise ValueError(msg)

            await _create_dynamodb_table(self._connected_client, self._table_name, table_config=self._table_config)

        # Enable TTL on the table if not already enabled
        ttl_status = await _describe_dynamodb_ttl(self._connected_client, self._table_name)

        # Only enable TTL if it's currently disabled
        if ttl_status == "DISABLED":
            await _enable_dynamodb_ttl(self._connected_client, self._table_name)

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        """Retrieve a managed entry from DynamoDB."""
        response = await self._connected_client.get_item(
            TableName=self._table_name,
            Key={
                "collection": {"S": collection},
                "key": {"S": key},
            },
        )

        item = response.get("Item")
        if not item:
            return None

        json_value = item.get("value", {}).get("S")
        if not json_value:
            return None

        managed_entry: ManagedEntry = self._serialization_adapter.load_json(json_str=json_value)

        expires_at_epoch = item.get("ttl", {}).get("N")

        # Our managed entry may carry a TTL, but the TTL in DynamoDB takes precedence.
        if expires_at_epoch:
            managed_entry.expires_at = datetime.fromtimestamp(int(expires_at_epoch), tz=timezone.utc)

        return managed_entry

    @override
    async def _put_managed_entry(
        self,
        *,
        key: str,
        collection: str,
        managed_entry: ManagedEntry,
    ) -> None:
        """Store a managed entry in DynamoDB."""
        json_value = self._serialization_adapter.dump_json(entry=managed_entry, key=key, collection=collection)

        item: dict[str, Any] = {
            "collection": {"S": collection},
            "key": {"S": key},
            "value": {"S": json_value},
        }

        # Add TTL if present
        if managed_entry.expires_at is not None:
            # DynamoDB TTL expects a Unix timestamp
            ttl_timestamp = int(managed_entry.expires_at.timestamp())
            item["ttl"] = {"N": str(ttl_timestamp)}

        await _put_dynamodb_item(self._connected_client, self._table_name, item)

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        """Delete a managed entry from DynamoDB."""
        deleted_item = await _delete_dynamodb_item(
            self._connected_client,
            self._table_name,
            {
                "collection": {"S": collection},
                "key": {"S": key},
            },
        )

        # Return True if an item was actually deleted
        return deleted_item is not None

    # No need to override _close - the exit stack handles all cleanup automatically
