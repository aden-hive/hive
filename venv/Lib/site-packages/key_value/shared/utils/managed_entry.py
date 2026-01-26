import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, SupportsFloat

from typing_extensions import Self

from key_value.shared.errors import DeserializationError, SerializationError
from key_value.shared.type_checking.bear_spray import bear_enforce
from key_value.shared.utils.time_to_live import now, now_plus, seconds_to


@dataclass(kw_only=True)
class ManagedEntry:
    """A managed cache entry containing value data and TTL metadata.

    The entry supports either TTL seconds or absolute expiration datetime. On init:
    - If `ttl` is provided but `expires_at` is not, an `expires_at` will be computed.
    - If `expires_at` is provided but `ttl` is not, a live TTL will be computed on access.
    """

    value: Mapping[str, Any]

    created_at: datetime | None = field(default=None)
    expires_at: datetime | None = field(default=None)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at <= now()

    @property
    def ttl(self) -> float | None:
        if self.expires_at is None:
            return None
        return seconds_to(datetime=self.expires_at)

    @property
    def value_as_json(self) -> str:
        """Return the value as a JSON string."""
        return dump_to_json(obj=self.value_as_dict)

    @property
    def value_as_dict(self) -> dict[str, Any]:
        return verify_dict(obj=self.value)

    @property
    def created_at_isoformat(self) -> str | None:
        return self.created_at.isoformat() if self.created_at else None

    @property
    def expires_at_isoformat(self) -> str | None:
        return self.expires_at.isoformat() if self.expires_at else None

    @classmethod
    def from_ttl(cls, *, value: Mapping[str, Any], created_at: datetime | None = None, ttl: SupportsFloat) -> Self:
        return cls(
            value=value,
            created_at=created_at,
            expires_at=(now_plus(seconds=float(ttl)) if ttl else None),
        )


@bear_enforce
def dump_to_json(obj: dict[str, Any]) -> str:
    try:
        return json.dumps(obj, sort_keys=True)
    except (json.JSONDecodeError, TypeError) as e:
        msg: str = f"Failed to serialize object to JSON: {e}"
        raise SerializationError(msg) from e


@bear_enforce
def load_from_json(json_str: str) -> dict[str, Any]:
    try:
        return verify_dict(obj=json.loads(json_str))  # pyright: ignore[reportAny]

    except (json.JSONDecodeError, TypeError) as e:
        msg: str = f"Failed to deserialize JSON string: {e}"
        raise DeserializationError(msg) from e


@bear_enforce
def verify_dict(obj: Any) -> dict[str, Any]:
    if not isinstance(obj, Mapping):
        msg = "Object is not a Mapping"
        raise TypeError(msg)

    if not all(isinstance(key, str) for key in obj):  # pyright: ignore[reportUnknownVariableType]
        msg = "Object contains non-string keys"
        raise TypeError(msg)

    return dict(obj)  # pyright: ignore[reportUnknownArgumentType]


def estimate_serialized_size(value: Mapping[str, Any]) -> int:
    """Estimate the serialized size of a value without creating a ManagedEntry.

    This function provides a more efficient way to estimate the size of a value
    when serialized to JSON, without the overhead of creating a full ManagedEntry object.
    This is useful for size-based checks in wrappers.

    Args:
        value: The value mapping to estimate the size for.

    Returns:
        The estimated size in bytes when serialized to JSON.
    """
    return len(dump_to_json(obj=dict(value)))
