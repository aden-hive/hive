"""Serialization adapter base class for converting ManagedEntry objects to/from store-specific formats.

This module provides the SerializationAdapter ABC that store implementations should use
to define their own serialization strategy. Store-specific adapter implementations
should be defined within their respective store modules.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Literal, TypeVar

from key_value.shared.errors import DeserializationError, SerializationError
from key_value.shared.type_checking.bear_spray import bear_enforce
from key_value.shared.utils.managed_entry import ManagedEntry, dump_to_json, load_from_json, verify_dict

T = TypeVar("T")


@bear_enforce
def key_must_be(dictionary: dict[str, Any], /, key: str, expected_type: type[T]) -> T | None:
    if key not in dictionary:
        return None
    if not isinstance(dictionary[key], expected_type):
        msg = f"{key} must be a {expected_type.__name__}"
        raise TypeError(msg)
    return dictionary[key]


@bear_enforce
def parse_datetime_str(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        msg = f"Invalid datetime string: {value}"
        raise DeserializationError(message=msg) from None


class SerializationAdapter(ABC):
    """Base class for store-specific serialization adapters.

    Adapters encapsulate the logic for converting between ManagedEntry objects
    and store-specific storage formats. This provides a consistent interface
    while allowing each store to optimize its serialization strategy.
    """

    _date_format: Literal["isoformat", "datetime"] | None = "isoformat"
    _value_format: Literal["string", "dict"] | None = "dict"

    def __init__(
        self, *, date_format: Literal["isoformat", "datetime"] | None = "isoformat", value_format: Literal["string", "dict"] | None = "dict"
    ) -> None:
        self._date_format = date_format
        self._value_format = value_format

    def load_json(self, json_str: str) -> ManagedEntry:
        """Convert a JSON string to a ManagedEntry."""
        loaded_data: dict[str, Any] = load_from_json(json_str=json_str)

        return self.load_dict(data=loaded_data)

    @abstractmethod
    def prepare_load(self, data: dict[str, Any]) -> dict[str, Any]:
        """Prepare data for loading.

        This method is used by subclasses to handle any required transformations before loading the data into a ManagedEntry."""

    def load_dict(self, data: dict[str, Any]) -> ManagedEntry:
        """Convert a dictionary to a ManagedEntry."""

        data = self.prepare_load(data=data)

        managed_entry_proto: dict[str, Any] = {}

        if self._date_format == "isoformat":
            if created_at := key_must_be(data, key="created_at", expected_type=str):
                managed_entry_proto["created_at"] = parse_datetime_str(value=created_at)
            if expires_at := key_must_be(data, key="expires_at", expected_type=str):
                managed_entry_proto["expires_at"] = parse_datetime_str(value=expires_at)

        if self._date_format == "datetime":
            if created_at := key_must_be(data, key="created_at", expected_type=datetime):
                managed_entry_proto["created_at"] = created_at
            if expires_at := key_must_be(data, key="expires_at", expected_type=datetime):
                managed_entry_proto["expires_at"] = expires_at

        if "value" not in data:
            msg = "Value field not found"
            raise DeserializationError(message=msg)

        value = data["value"]

        managed_entry_value: dict[str, Any] = {}

        if isinstance(value, str):
            managed_entry_value = load_from_json(json_str=value)
        elif isinstance(value, dict):
            managed_entry_value = verify_dict(obj=value)
        else:
            msg = "Value field is not a string or dictionary"
            raise DeserializationError(message=msg)

        return ManagedEntry(
            value=managed_entry_value,
            created_at=managed_entry_proto.get("created_at"),
            expires_at=managed_entry_proto.get("expires_at"),
        )

    @abstractmethod
    def prepare_dump(self, data: dict[str, Any]) -> dict[str, Any]:
        """Prepare data for dumping to a dictionary.

        This method is used by subclasses to handle any required transformations before dumping the data to a dictionary."""

    def dump_dict(
        self,
        entry: ManagedEntry,
        exclude_none: bool = True,
        *,
        key: str | None = None,
        collection: str | None = None,
        version: int = 1,
    ) -> dict[str, Any]:
        """Convert a ManagedEntry to a dictionary.

        Args:
            entry: The ManagedEntry to serialize
            exclude_none: Whether to exclude None values from the output
            key: Optional unsanitized key name to include in the document
            collection: Optional unsanitized collection name to include in the document
            version: Document schema version (default: 1)

        Returns:
            A dictionary representation of the ManagedEntry with optional metadata fields
        """

        data: dict[str, Any] = {
            "version": version,
            "value": entry.value_as_dict if self._value_format == "dict" else entry.value_as_json,
        }

        if key is not None:
            data["key"] = key

        if collection is not None:
            data["collection"] = collection

        if self._date_format == "isoformat":
            data["created_at"] = entry.created_at_isoformat
            data["expires_at"] = entry.expires_at_isoformat

        if self._date_format == "datetime":
            data["created_at"] = entry.created_at
            data["expires_at"] = entry.expires_at

        if exclude_none:
            data = {k: v for k, v in data.items() if v is not None}

        return self.prepare_dump(data=data)

    def dump_json(
        self,
        entry: ManagedEntry,
        exclude_none: bool = True,
        *,
        key: str | None = None,
        collection: str | None = None,
        version: int = 1,
    ) -> str:
        """Convert a ManagedEntry to a JSON string.

        Args:
            entry: The ManagedEntry to serialize
            exclude_none: Whether to exclude None values from the output
            key: Optional unsanitized key name to include in the document
            collection: Optional unsanitized collection name to include in the document
            version: Document schema version (default: 1)

        Returns:
            A JSON string representation of the ManagedEntry with optional metadata fields
        """
        if self._date_format == "datetime":
            msg = 'dump_json is incompatible with date_format="datetime"; use date_format="isoformat" or dump_dict().'
            raise SerializationError(msg)
        return dump_to_json(obj=self.dump_dict(entry=entry, exclude_none=exclude_none, key=key, collection=collection, version=version))


class BasicSerializationAdapter(SerializationAdapter):
    """Basic serialization adapter that does not perform any transformations."""

    def __init__(
        self, *, date_format: Literal["isoformat", "datetime"] | None = "isoformat", value_format: Literal["string", "dict"] | None = "dict"
    ) -> None:
        super().__init__(date_format=date_format, value_format=value_format)

    def prepare_load(self, data: dict[str, Any]) -> dict[str, Any]:
        return data

    def prepare_dump(self, data: dict[str, Any]) -> dict[str, Any]:
        return data
