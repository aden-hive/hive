from typing import TYPE_CHECKING, Any, overload

from typing_extensions import override

from key_value.aio._utils.managed_entry import ManagedEntry
from key_value.aio._utils.sanitization import SanitizationStrategy
from key_value.aio._utils.sanitize import hash_excess_length
from key_value.aio.stores.base import (
    BaseContextManagerStore,
    BaseStore,
)

HTTP_NOT_FOUND = 404

# S3 key length limit is 1024 bytes
# Allocating 500 bytes each for collection and key stays well under the limit
MAX_COLLECTION_LENGTH = 500
MAX_KEY_LENGTH = 500

try:
    import aioboto3
    from aioboto3.session import Session
except ImportError as e:
    msg = "S3Store requires py-key-value-aio[s3]"
    raise ImportError(msg) from e

# aioboto3 generates types at runtime, so we use AioBaseClient at runtime but S3Client during static type checking
if TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client
else:
    from aiobotocore.client import AioBaseClient as S3Client


# Private helper functions to encapsulate S3/boto3 client interactions with type ignore comments
# These are module-level functions (not methods) so they are not exported with the store class


def _create_s3_session(
    *,
    region_name: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    aws_session_token: str | None = None,
) -> Session:
    """Create an aioboto3 session for S3."""
    return aioboto3.Session(
        region_name=region_name,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        aws_session_token=aws_session_token,
    )


def _create_s3_client_context(session: Session, *, endpoint_url: str | None = None) -> Any:
    """Create an S3 client context manager from a session."""
    return session.client(service_name="s3", endpoint_url=endpoint_url)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


async def _head_s3_bucket(client: S3Client, bucket_name: str) -> None:
    """Check if an S3 bucket exists."""
    await client.head_bucket(Bucket=bucket_name)


async def _create_s3_bucket(client: S3Client, bucket_name: str, *, region_name: str | None = None) -> None:
    """Create an S3 bucket.

    Args:
        client: The S3 client.
        bucket_name: The name of the bucket to create.
        region_name: The region for the bucket. If not us-east-1, LocationConstraint is set.
    """
    import contextlib

    with contextlib.suppress(client.exceptions.BucketAlreadyOwnedByYou):
        create_params: dict[str, Any] = {"Bucket": bucket_name}

        # For regions other than us-east-1, specify LocationConstraint
        if region_name and region_name != "us-east-1":
            create_params["CreateBucketConfiguration"] = {"LocationConstraint": region_name}

        await client.create_bucket(**create_params)


async def _get_s3_object(client: S3Client, bucket_name: str, key: str) -> bytes | None:
    """Get an object from S3.

    Returns:
        The object body as bytes, or None if not found.
    """
    try:
        response = await client.get_object(
            Bucket=bucket_name,
            Key=key,
        )

        async with response["Body"] as stream:
            return await stream.read()
    except client.exceptions.NoSuchKey:
        return None


async def _put_s3_object(
    client: S3Client,
    bucket_name: str,
    key: str,
    body: bytes,
    *,
    content_type: str = "application/json",
    metadata: dict[str, str] | None = None,
) -> None:
    """Put an object into S3."""
    await client.put_object(
        Bucket=bucket_name,
        Key=key,
        Body=body,
        ContentType=content_type,
        Metadata=metadata or {},
    )


async def _delete_s3_object(client: S3Client, bucket_name: str, key: str) -> None:
    """Delete an object from S3."""
    await client.delete_object(
        Bucket=bucket_name,
        Key=key,
    )


async def _head_s3_object(client: S3Client, bucket_name: str, key: str) -> bool:
    """Check if an object exists in S3.

    Returns:
        True if the object exists, False otherwise.
    """
    from botocore.exceptions import ClientError

    try:
        await client.head_object(
            Bucket=bucket_name,
            Key=key,
        )
    except ClientError as e:
        error = e.response.get("Error", {})  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        metadata = e.response.get("ResponseMetadata", {})  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        error_code = error.get("Code", "")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        http_status = metadata.get("HTTPStatusCode", 0)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

        if error_code in ("404", "NoSuchKey") or http_status == HTTP_NOT_FOUND:
            return False

        raise
    else:
        return True


def _get_s3_client_region(client: S3Client) -> str | None:
    """Get the region name from an S3 client."""
    return getattr(client.meta, "region_name", None)


def _get_botocore_error_code(e: Exception) -> str:
    """Get the error code from a botocore ClientError."""
    from botocore.exceptions import ClientError

    if not isinstance(e, ClientError):
        return ""
    return e.response.get("Error", {}).get("Code", "")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


def _get_botocore_http_status(e: Exception) -> int:
    """Get the HTTP status code from a botocore ClientError."""
    from botocore.exceptions import ClientError

    if not isinstance(e, ClientError):
        return 0
    return e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


class S3KeySanitizationStrategy(SanitizationStrategy):
    """Sanitization strategy for S3 keys with byte-aware length limits.

    S3 has a maximum key length of 1024 bytes (UTF-8 encoded). This strategy
    hashes keys that exceed the specified byte limit to ensure compliance.

    Args:
        max_bytes: Maximum key length in bytes. Defaults to 500.
    """

    def __init__(self, max_bytes: int = MAX_KEY_LENGTH) -> None:
        """Initialize the S3 key sanitization strategy.

        Args:
            max_bytes: Maximum key length in bytes.
        """
        self.max_bytes = max_bytes

    def sanitize(self, value: str) -> str:
        """Hash the value if it exceeds max_bytes when UTF-8 encoded.

        Args:
            value: The key to sanitize.

        Returns:
            The original value if within limit, or truncated+hashed if too long.
        """
        return hash_excess_length(value, self.max_bytes, length_is_bytes=True)

    def validate(self, value: str) -> None:
        """No validation needed for S3 keys."""


class S3CollectionSanitizationStrategy(S3KeySanitizationStrategy):
    """Sanitization strategy for S3 collection names with byte-aware length limits.

    This is identical to S3KeySanitizationStrategy but uses a default of 500 bytes
    for collection names to match the S3 key format {collection}/{key}.
    """

    def __init__(self, max_bytes: int = MAX_COLLECTION_LENGTH) -> None:
        """Initialize the S3 collection sanitization strategy.

        Args:
            max_bytes: Maximum collection name length in bytes.
        """
        super().__init__(max_bytes=max_bytes)


class S3Store(BaseContextManagerStore, BaseStore):
    """AWS S3-based key-value store.

    This store uses AWS S3 to store key-value pairs as objects. Each entry is stored
    as a separate S3 object with the path format: {collection}/{key}. The ManagedEntry
    is serialized to JSON and stored as the object body. TTL information is stored in
    S3 object metadata and checked client-side during retrieval (S3 lifecycle policies
    can be configured separately for background cleanup, but don't provide atomic TTL+retrieval).

    By default, collections and keys are not sanitized. This means you must ensure that
    the combined "{collection}/{key}" path does not exceed S3's 1024-byte limit when UTF-8 encoded.

    To handle long collection or key names, use the S3CollectionSanitizationStrategy and
    S3KeySanitizationStrategy which will hash values exceeding the byte limit.

    Example:
        Basic usage with automatic AWS credentials:

        >>> async with S3Store(bucket_name="my-kv-store") as store:
        ...     await store.put(key="user:123", value={"name": "Alice"}, ttl=3600)
        ...     user = await store.get(key="user:123")

        With sanitization for long keys/collections:

        >>> async with S3Store(
        ...     bucket_name="my-kv-store",
        ...     collection_sanitization_strategy=S3CollectionSanitizationStrategy(),
        ...     key_sanitization_strategy=S3KeySanitizationStrategy(),
        ... ) as store:
        ...     await store.put(key="very_long_key" * 100, value={"data": "test"})

        With custom AWS credentials:

        >>> async with S3Store(
        ...     bucket_name="my-kv-store",
        ...     region_name="us-west-2",
        ...     aws_access_key_id="...",
        ...     aws_secret_access_key="...",
        ... ) as store:
        ...     await store.put(key="config", value={"setting": "value"})

        For local testing with LocalStack:

        >>> async with S3Store(
        ...     bucket_name="test-bucket",
        ...     endpoint_url="http://localhost:4566",
        ... ) as store:
        ...     await store.put(key="test", value={"data": "test"})
    """

    _bucket_name: str
    _endpoint_url: str | None
    _raw_client: Any
    _client: S3Client | None

    @overload
    def __init__(
        self,
        *,
        client: S3Client,
        bucket_name: str,
        default_collection: str | None = None,
        collection_sanitization_strategy: SanitizationStrategy | None = None,
        key_sanitization_strategy: SanitizationStrategy | None = None,
    ) -> None:
        """Initialize the S3 store with a pre-configured client.

        Note: When you provide an existing client, you retain ownership and must manage
        its lifecycle yourself. The store will not close the client when the store is closed.

        Args:
            client: The S3 client to use. You must have entered the context manager before passing this in.
            bucket_name: The name of the S3 bucket to use.
            default_collection: The default collection to use if no collection is provided.
            collection_sanitization_strategy: Strategy for sanitizing collection names. Defaults to None (no sanitization).
            key_sanitization_strategy: Strategy for sanitizing keys. Defaults to None (no sanitization).
        """

    @overload
    def __init__(
        self,
        *,
        bucket_name: str,
        region_name: str | None = None,
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_session_token: str | None = None,
        default_collection: str | None = None,
        collection_sanitization_strategy: SanitizationStrategy | None = None,
        key_sanitization_strategy: SanitizationStrategy | None = None,
    ) -> None:
        """Initialize the S3 store with AWS credentials.

        Args:
            bucket_name: The name of the S3 bucket to use.
            region_name: AWS region name. Defaults to None (uses AWS default).
            endpoint_url: Custom endpoint URL (useful for LocalStack/MinIO). Defaults to None.
            aws_access_key_id: AWS access key ID. Defaults to None (uses AWS default credentials).
            aws_secret_access_key: AWS secret access key. Defaults to None (uses AWS default credentials).
            aws_session_token: AWS session token. Defaults to None (uses AWS default credentials).
            default_collection: The default collection to use if no collection is provided.
            collection_sanitization_strategy: Strategy for sanitizing collection names. Defaults to None (no sanitization).
            key_sanitization_strategy: Strategy for sanitizing keys. Defaults to None (no sanitization).
        """

    def __init__(
        self,
        *,
        client: S3Client | None = None,
        bucket_name: str,
        region_name: str | None = None,
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_session_token: str | None = None,
        default_collection: str | None = None,
        collection_sanitization_strategy: SanitizationStrategy | None = None,
        key_sanitization_strategy: SanitizationStrategy | None = None,
    ) -> None:
        """Initialize the S3 store.

        Args:
            client: The S3 client to use. Defaults to None (creates a new client).
            bucket_name: The name of the S3 bucket to use.
            region_name: AWS region name. Defaults to None (uses AWS default).
            endpoint_url: Custom endpoint URL (useful for LocalStack/MinIO). Defaults to None.
            aws_access_key_id: AWS access key ID. Defaults to None (uses AWS default credentials).
            aws_secret_access_key: AWS secret access key. Defaults to None (uses AWS default credentials).
            aws_session_token: AWS session token. Defaults to None (uses AWS default credentials).
            default_collection: The default collection to use if no collection is provided.
            collection_sanitization_strategy: Strategy for sanitizing collection names. Defaults to None (no sanitization).
            key_sanitization_strategy: Strategy for sanitizing keys. Defaults to None (no sanitization).
        """
        self._bucket_name = bucket_name
        self._endpoint_url = endpoint_url
        client_provided = client is not None

        if client:
            self._client = client
            self._raw_client = None
        else:
            session = _create_s3_session(
                region_name=region_name,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                aws_session_token=aws_session_token,
            )

            self._raw_client = _create_s3_client_context(session, endpoint_url=endpoint_url)
            self._client = None

        super().__init__(
            default_collection=default_collection,
            collection_sanitization_strategy=collection_sanitization_strategy,
            key_sanitization_strategy=key_sanitization_strategy,
            client_provided_by_user=client_provided,
        )

    @property
    def _connected_client(self) -> S3Client:
        """Get the connected S3 client.

        Raises:
            ValueError: If the client is not connected.

        Returns:
            The connected S3 client.
        """
        if not self._client:
            msg = "Client not connected"
            raise ValueError(msg)
        return self._client

    @override
    async def _setup(self) -> None:
        """Setup the S3 client and ensure bucket exists.

        This method creates the S3 bucket if it doesn't already exist. It uses the
        HeadBucket operation to check for bucket existence and creates it if not found.
        """
        # Register client cleanup if we own the client
        if not self._client_provided_by_user and self._raw_client is not None:
            self._client = await self._exit_stack.enter_async_context(self._raw_client)

        from botocore.exceptions import ClientError

        try:
            await _head_s3_bucket(self._connected_client, self._bucket_name)
        except ClientError as e:
            error_code = _get_botocore_error_code(e)
            http_status = _get_botocore_http_status(e)

            if error_code in ("404", "NoSuchBucket") or http_status == HTTP_NOT_FOUND:
                # Skip region specification for custom endpoints (LocalStack, MinIO)
                region_name = None if self._endpoint_url else _get_s3_client_region(self._connected_client)
                await _create_s3_bucket(self._connected_client, self._bucket_name, region_name=region_name)
            else:
                raise

    def _get_s3_key(self, *, collection: str, key: str) -> str:
        """Generate the S3 object key for a given collection and key.

        The collection and key are sanitized using the configured sanitization strategies
        before being combined into the S3 object key format: {collection}/{key}.

        Args:
            collection: The collection name.
            key: The key within the collection.

        Returns:
            The S3 object key in format: {collection}/{key}
        """
        sanitized_collection, sanitized_key = self._sanitize_collection_and_key(collection=collection, key=key)
        return f"{sanitized_collection}/{sanitized_key}"

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        """Retrieve a managed entry from S3.

        This method fetches the object from S3, deserializes the JSON body to a ManagedEntry,
        and checks for client-side TTL expiration. If the entry has expired, it is deleted
        and None is returned.

        Args:
            key: The key to retrieve.
            collection: The collection to retrieve from.

        Returns:
            The ManagedEntry if found and not expired, otherwise None.
        """
        s3_key = self._get_s3_key(collection=collection, key=key)

        body_bytes = await _get_s3_object(self._connected_client, self._bucket_name, s3_key)
        if body_bytes is None:
            return None

        json_value = body_bytes.decode("utf-8")
        managed_entry = self._serialization_adapter.load_json(json_str=json_value)

        if managed_entry.is_expired:
            await _delete_s3_object(self._connected_client, self._bucket_name, s3_key)
            return None
        return managed_entry

    @override
    async def _put_managed_entry(
        self,
        *,
        key: str,
        collection: str,
        managed_entry: ManagedEntry,
    ) -> None:
        """Store a managed entry in S3.

        This method serializes the ManagedEntry to JSON and stores it as an S3 object.
        TTL information is stored in the object metadata for potential use by S3 lifecycle
        policies (though lifecycle policies don't support atomic TTL+retrieval, so client-side
        checking is still required).

        Args:
            key: The key to store.
            collection: The collection to store in.
            managed_entry: The ManagedEntry to store.
        """
        s3_key = self._get_s3_key(collection=collection, key=key)
        json_value = self._serialization_adapter.dump_json(entry=managed_entry)

        metadata: dict[str, str] = {}
        if managed_entry.expires_at:
            metadata["expires-at"] = managed_entry.expires_at.isoformat()
        if managed_entry.created_at:
            metadata["created-at"] = managed_entry.created_at.isoformat()

        await _put_s3_object(
            self._connected_client,
            self._bucket_name,
            s3_key,
            json_value.encode("utf-8"),
            content_type="application/json",
            metadata=metadata,
        )

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        """Delete a managed entry from S3.

        Args:
            key: The key to delete.
            collection: The collection to delete from.

        Returns:
            True if an object was deleted, False if the object didn't exist.
        """
        s3_key = self._get_s3_key(collection=collection, key=key)

        from botocore.exceptions import ClientError

        try:
            exists = await _head_s3_object(self._connected_client, self._bucket_name, s3_key)
            if not exists:
                return False
        except ClientError as e:
            error_code = _get_botocore_error_code(e)

            if error_code in ("403", "AccessDenied"):
                # Can't check existence but try to delete anyway
                await _delete_s3_object(self._connected_client, self._bucket_name, s3_key)
                return True

            raise

        await _delete_s3_object(self._connected_client, self._bucket_name, s3_key)
        return True

    # No need to override _close - the exit stack handles all cleanup automatically
