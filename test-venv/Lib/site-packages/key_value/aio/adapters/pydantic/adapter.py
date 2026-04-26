from typing import Any, TypeVar

from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic.type_adapter import TypeAdapter
from pydantic_core import PydanticOmit
from typing_extensions import TypeForm

from key_value.aio._utils.beartype import bear_spray
from key_value.aio.adapters.pydantic.base import BasePydanticAdapter
from key_value.aio.protocols.key_value import AsyncKeyValue

T = TypeVar("T")


class _SkipInvalidJsonSchema(GenerateJsonSchema):
    """Schema generator that skips fields that can't be represented in JSON schema.

    This handles models with Callable fields, custom validators, or other types
    that cannot be converted to JSON schema. Such fields are omitted from the
    schema rather than raising an error.
    """

    def handle_invalid_for_json_schema(self, schema: Any, error_info: str) -> JsonSchemaValue:  # noqa: ARG002
        raise PydanticOmit


class PydanticAdapter(BasePydanticAdapter[T]):
    """Adapter for persisting any pydantic-serializable type.

    This is the "less safe" adapter that accepts any Python type that Pydantic can serialize.
    Unlike BaseModelAdapter (which is constrained to BaseModel types), this adapter can handle:
    - Pydantic BaseModel instances
    - Dataclasses (standard and Pydantic)
    - TypedDict
    - Primitive types (int, str, float, bool, etc.)
    - Collection types (list, dict, set, tuple, etc.)
    - Datetime and other common types

    Types that serialize to dicts (BaseModel, dataclass, TypedDict, dict) are stored directly.
    Other types are wrapped in {"items": value} to ensure consistent dict-based storage.
    """

    # Beartype cannot handle the parameterized type annotation (TypeForm[T]) used here for this generic adapter.
    # Using @bear_spray to bypass beartype's runtime checks for this specific method.
    @bear_spray
    def __init__(
        self,
        key_value: AsyncKeyValue,
        pydantic_model: TypeForm[T],
        default_collection: str | None = None,
        raise_on_validation_error: bool = False,
    ) -> None:
        """Create a new PydanticAdapter.

        Args:
            key_value: The KVStore to use.
            pydantic_model: The type to serialize/deserialize. Can be any pydantic-serializable type.
            default_collection: The default collection to use.
            raise_on_validation_error: Whether to raise a DeserializationError if validation fails during reads.
                                       Otherwise, calls will return None if validation fails.
        """
        self._key_value = key_value
        self._type_adapter = TypeAdapter[T](pydantic_model)
        self._default_collection = default_collection
        self._raise_on_validation_error = raise_on_validation_error

        # Determine if this type needs wrapping
        self._needs_wrapping = self._check_needs_wrapping()

    @bear_spray
    def _check_needs_wrapping(self) -> bool:
        """Check if a type needs to be wrapped in {"items": ...} for storage.

        Types that serialize to dicts don't need wrapping. Other types do.

        Returns:
            True if the type needs wrapping, False otherwise.
        """
        # Return the negated condition directly (fixes SIM103)
        return not self._serializes_to_dict()

    @bear_spray
    def _serializes_to_dict(self) -> bool:
        """Check if a type serializes to a dict by inspecting the TypeAdapter's JSON schema.

        This uses Pydantic's TypeAdapter.json_schema() to reliably determine the output structure.
        Types that produce a JSON object (schema type "object") are dict-serializable.

        Uses a custom schema generator to skip fields that can't be represented in JSON schema
        (e.g., Callable fields), avoiding PydanticInvalidForJsonSchema errors.

        Returns:
            True if the type serializes to a dict (JSON object), False otherwise.
        """
        schema = self._type_adapter.json_schema(schema_generator=_SkipInvalidJsonSchema)
        return schema.get("type") == "object"

    def _get_model_type_name(self) -> str:
        """Return the model type name for error messages."""
        return "pydantic-serializable value"
