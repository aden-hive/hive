import time
from datetime import datetime, timedelta, timezone
from typing import Any, SupportsFloat, overload

from key_value.shared.errors import InvalidTTLError
from key_value.shared.type_checking.bear_spray import bear_enforce


def epoch_to_datetime(epoch: float) -> datetime:
    """Convert an epoch timestamp to a datetime object."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def now_as_epoch() -> float:
    """Get the current time as epoch seconds."""
    return time.time()


def now() -> datetime:
    """Get the current time as a datetime object."""
    return datetime.now(tz=timezone.utc)


def seconds_to(datetime: datetime) -> float:
    """Get the number of seconds between the current time and a datetime object."""
    return (datetime - now()).total_seconds()


def now_plus(seconds: float) -> datetime:
    """Get the current time plus a number of seconds as a datetime object."""
    return datetime.now(tz=timezone.utc) + timedelta(seconds=seconds)


def try_parse_datetime_str(value: Any) -> datetime | None:  # pyright: ignore[reportAny]
    try:
        if isinstance(value, str):
            return datetime.fromisoformat(value)
    except ValueError:
        return None

    return None


@overload
def prepare_ttl(t: SupportsFloat) -> float: ...


@overload
def prepare_ttl(t: SupportsFloat | None) -> float | None: ...


def prepare_ttl(t: SupportsFloat | None) -> float | None:
    """Prepare a TTL for use in a put operation.

    If a TTL is provided, it will be validated and returned as a float.
    If a None is provided, None will be returned.

    If the provided TTL is not a float or float-adjacent type, an InvalidTTLError will be raised. In addition,
    if a bool is provided, an InvalidTTLError will be raised. If the user passes TTL=True, true becomes `1` and the
    entry immediately expires which is likely not what the user intended.
    """
    try:
        return _validate_ttl(t=t)
    except TypeError as e:
        raise InvalidTTLError(ttl=t, extra_info={"type": type(t).__name__}) from e


@bear_enforce
def _validate_ttl(t: SupportsFloat | None) -> float | None:
    if t is None:
        return None

    if isinstance(t, bool):
        raise InvalidTTLError(ttl=t, extra_info={"type": type(t).__name__})

    ttl = float(t)

    if ttl <= 0:
        raise InvalidTTLError(ttl=t)

    return ttl


def prepare_entry_timestamps(ttl: SupportsFloat | None) -> tuple[datetime, float | None, datetime | None]:
    created_at: datetime = now()

    ttl_seconds: float | None = prepare_ttl(t=ttl)

    expires_at: datetime | None = None
    if ttl_seconds is not None:
        expires_at = created_at + timedelta(seconds=ttl_seconds)

    return created_at, ttl_seconds, expires_at
