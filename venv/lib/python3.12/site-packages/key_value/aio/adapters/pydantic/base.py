import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Generic, SupportsFloat, TypeVar, overload

from key_value.shared.errors import DeserializationError, SerializationError
from pydantic import ValidationError
from pydantic.type_adapter import TypeAdapter
from pydantic_core import PydanticSerializationError

from key_value.aio.protocols.key_value import AsyncKeyValue

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BasePydanticAdapter(Generic[T], ABC):
    """Base adapter using Pydantic TypeAdapter for validation and serialization.

    This abstract base class provides shared functionality for adapters that use
    Pydantic's TypeAdapter for validation and serialization. Concrete subclasses
    must implement _get_model_type_name() to provide appropriate error messages.
    """

    _key_value: AsyncKeyValue
    _is_list_model: bool
    _type_adapter: TypeAdapter[T]
    _default_collection: str | None
    _raise_on_validation_error: bool

    @abstractmethod
    def _get_model_type_name(self) -> str:
        """Return the model type name for error messages.

        Returns:
            A string describing the model type (e.g., "Pydantic model", "dataclass").
        """
        ...

    def _validate_model(self, value: dict[str, Any]) -> T | None:
        """Validate and deserialize a dict into the configured model type.

        This method handles both single models and list models. For list models, it expects the value
        to contain an "items" key with the list data, following the convention used by `_serialize_model`.
        If validation fails and `raise_on_validation_error` is False, returns None instead of raising.

        Args:
            value: The dict to validate and convert to a model.

        Returns:
            The validated model instance, or None if validation fails and errors are suppressed.

        Raises:
            DeserializationError: If validation fails and `raise_on_validation_error` is True.
        """
        try:
            if self._is_list_model:
                if "items" not in value:
                    if self._raise_on_validation_error:
                        msg = f"Invalid {self._get_model_type_name()} payload: missing 'items' wrapper"
                        raise DeserializationError(msg)

                    # Log the missing 'items' wrapper when not raising
                    logger.error(
                        "Missing 'items' wrapper for list %s",
                        self._get_model_type_name(),
                        extra={
                            "model_type": self._get_model_type_name(),
                            "error": "missing 'items' wrapper",
                        },
                        exc_info=False,
                    )
                    return None
                return self._type_adapter.validate_python(value["items"])

            return self._type_adapter.validate_python(value)
        except ValidationError as e:
            if self._raise_on_validation_error:
                details = e.errors(include_input=False)
                msg = f"Invalid {self._get_model_type_name()}: {details}"
                raise DeserializationError(msg) from e

            # Log the validation error when not raising
            error_details = e.errors(include_input=False)
            logger.error(
                "Validation failed for %s",
                self._get_model_type_name(),
                extra={
                    "model_type": self._get_model_type_name(),
                    "error_count": len(error_details),
                    "errors": error_details,
                },
                exc_info=True,
            )
            return None

    def _serialize_model(self, value: T) -> dict[str, Any]:
        """Serialize a model to a dict for storage.

        This method handles both single models and list models. For list models, it wraps the serialized
        list in a dict with an "items" key (e.g., {"items": [...]}) to ensure consistent dict-based storage
        format across all value types. This wrapping convention is expected by `_validate_model` during
        deserialization.

        Args:
            value: The model instance to serialize.

        Returns:
            A dict representation of the model suitable for storage.

        Raises:
            SerializationError: If the model cannot be serialized.
        """
        try:
            if self._is_list_model:
                return {"items": self._type_adapter.dump_python(value, mode="json")}

            return self._type_adapter.dump_python(value, mode="json")  # pyright: ignore[reportAny]
        except PydanticSerializationError as e:
            msg = f"Invalid {self._get_model_type_name()}: {e}"
            raise SerializationError(msg) from e

    @overload
    async def get(self, key: str, *, collection: str | None = None, default: T) -> T: ...

    @overload
    async def get(self, key: str, *, collection: str | None = None, default: None = None) -> T | None: ...

    async def get(self, key: str, *, collection: str | None = None, default: T | None = None) -> T | None:
        """Get and validate a model by key.

        Args:
            key: The key to retrieve.
            collection: The collection to use. If not provided, uses the default collection.
            default: The default value to return if the key doesn't exist or validation fails.

        Returns:
            The parsed model instance if found and valid, or the default value if key doesn't exist or validation fails.

        Raises:
            DeserializationError: If the stored data cannot be validated as the model and the adapter is configured to
            raise on validation error.

        Note:
            When raise_on_validation_error=False and validation fails, returns the default value (which may be None).
            When raise_on_validation_error=True and validation fails, raises DeserializationError.
        """
        collection = collection or self._default_collection

        value = await self._key_value.get(key=key, collection=collection)
        if value is not None:
            validated = self._validate_model(value=value)
            if validated is not None:
                return validated

        return default

    @overload
    async def get_many(self, keys: Sequence[str], *, collection: str | None = None, default: T) -> list[T]: ...

    @overload
    async def get_many(self, keys: Sequence[str], *, collection: str | None = None, default: None = None) -> list[T | None]: ...

    async def get_many(self, keys: Sequence[str], *, collection: str | None = None, default: T | None = None) -> list[T] | list[T | None]:
        """Batch get and validate models by keys, preserving order.

        Args:
            keys: The list of keys to retrieve.
            collection: The collection to use. If not provided, uses the default collection.
            default: The default value to return for keys that don't exist or fail validation.

        Returns:
            A list of parsed model instances, with default values for missing keys or validation failures.

        Raises:
            DeserializationError: If the stored data cannot be validated as the model and the adapter is configured to
            raise on validation error.

        Note:
            When raise_on_validation_error=False and validation fails for any key, that position in the returned list
            will contain the default value (which may be None). The method returns a complete list matching the order
            and length of the input keys, with defaults substituted for missing or invalid entries.
        """
        collection = collection or self._default_collection

        values: list[dict[str, Any] | None] = await self._key_value.get_many(keys=keys, collection=collection)

        result: list[T | None] = []
        for value in values:
            if value is None:
                result.append(default)
            else:
                validated = self._validate_model(value=value)
                result.append(validated if validated is not None else default)
        return result

    async def put(self, key: str, value: T, *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        """Serialize and store a model.

        Propagates SerializationError if the model cannot be serialized.
        """
        collection = collection or self._default_collection

        value_dict: dict[str, Any] = self._serialize_model(value=value)

        await self._key_value.put(key=key, value=value_dict, collection=collection, ttl=ttl)

    async def put_many(
        self, keys: Sequence[str], values: Sequence[T], *, collection: str | None = None, ttl: SupportsFloat | None = None
    ) -> None:
        """Serialize and store multiple models, preserving order alignment with keys."""
        collection = collection or self._default_collection

        value_dicts: list[dict[str, Any]] = [self._serialize_model(value=value) for value in values]

        await self._key_value.put_many(keys=keys, values=value_dicts, collection=collection, ttl=ttl)

    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        """Delete a model by key. Returns True if a value was deleted, else False."""
        collection = collection or self._default_collection

        return await self._key_value.delete(key=key, collection=collection)

    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        """Delete multiple models by key. Returns the count of deleted entries."""
        collection = collection or self._default_collection

        return await self._key_value.delete_many(keys=keys, collection=collection)

    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[T | None, float | None]:
        """Get a model and its TTL seconds if present.

        Args:
            key: The key to retrieve.
            collection: The collection to use. If not provided, uses the default collection.

        Returns:
            A tuple of (model, ttl_seconds). Returns (None, None) if the key is missing or validation fails.

        Note:
            When validation fails and raise_on_validation_error=False, returns (None, None) even if TTL data exists.
            When validation fails and raise_on_validation_error=True, raises DeserializationError.
        """
        collection = collection or self._default_collection

        entry: dict[str, Any] | None
        ttl_info: float | None

        entry, ttl_info = await self._key_value.ttl(key=key, collection=collection)

        if entry is None:
            return (None, None)

        validated_model = self._validate_model(value=entry)
        if validated_model is not None:
            return (validated_model, ttl_info)

        return (None, None)

    async def ttl_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[tuple[T | None, float | None]]:
        """Batch get models with TTLs. Each element is (model|None, ttl_seconds|None)."""
        collection = collection or self._default_collection

        entries: list[tuple[dict[str, Any] | None, float | None]] = await self._key_value.ttl_many(keys=keys, collection=collection)

        return [(self._validate_model(value=entry) if entry is not None else None, ttl_info) for entry, ttl_info in entries]
