from collections.abc import Sequence
from dataclasses import is_dataclass
from typing import Any, TypeVar, get_args, get_origin

from key_value.shared.type_checking.bear_spray import bear_spray
from pydantic.type_adapter import TypeAdapter

from key_value.aio.adapters.pydantic.base import BasePydanticAdapter
from key_value.aio.protocols.key_value import AsyncKeyValue

T = TypeVar("T")


class DataclassAdapter(BasePydanticAdapter[T]):
    """Adapter around a KVStore-compliant Store that allows type-safe persistence of dataclasses.

    This adapter works with both standard library dataclasses and Pydantic dataclasses,
    leveraging Pydantic's TypeAdapter for robust validation and serialization.
    """

    _inner_type: type[Any]

    # Beartype cannot handle the parameterized type annotation (type[T]) used here for this generic dataclass adapter.
    # Using @bear_spray to bypass beartype's runtime checks for this specific method.
    @bear_spray
    def __init__(
        self,
        key_value: AsyncKeyValue,
        dataclass_type: type[T],
        default_collection: str | None = None,
        raise_on_validation_error: bool = False,
    ) -> None:
        """Create a new DataclassAdapter.

        Args:
            key_value: The AsyncKeyValue to use.
            dataclass_type: The dataclass type to use. Can be a single dataclass or list[dataclass].
            default_collection: The default collection to use.
            raise_on_validation_error: Whether to raise a DeserializationError if validation fails during reads. Otherwise,
                                       calls will return None if validation fails.

        Raises:
            TypeError: If dataclass_type is not a dataclass type.
        """
        self._key_value = key_value

        origin = get_origin(dataclass_type)
        self._is_list_model = origin is not None and isinstance(origin, type) and issubclass(origin, Sequence)

        # Extract the inner type for list models
        if self._is_list_model:
            args = get_args(dataclass_type)
            if not args:
                msg = f"List type {dataclass_type} must have a type argument"
                raise TypeError(msg)
            self._inner_type = args[0]
        else:
            self._inner_type = dataclass_type

        # Validate that the inner type is a dataclass
        if not is_dataclass(self._inner_type):
            msg = f"{self._inner_type} is not a dataclass"
            raise TypeError(msg)

        self._type_adapter = TypeAdapter[T](dataclass_type)
        self._default_collection = default_collection
        self._raise_on_validation_error = raise_on_validation_error

    def _get_model_type_name(self) -> str:
        """Return the model type name for error messages."""
        return "dataclass"
