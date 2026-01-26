from collections.abc import Sequence

from key_value.shared.type_checking.bear_spray import bear_enforce

DEFAULT_COMPOUND_SEPARATOR = "::"
DEFAULT_PREFIX_SEPARATOR = "__"


def compound_string(first: str, second: str, separator: str | None = None) -> str:
    separator = separator or DEFAULT_COMPOUND_SEPARATOR
    return f"{first}{separator}{second}"


def uncompound_string(string: str, separator: str | None = None) -> tuple[str, str]:
    separator = separator or DEFAULT_COMPOUND_SEPARATOR
    if separator not in string:
        msg: str = f"String {string} is not a compound identifier"
        raise TypeError(msg) from None

    split_key: list[str] = string.split(separator, 1)

    if len(split_key) != 2:  # noqa: PLR2004
        msg = f"String {string} is not a compound identifier"
        raise TypeError(msg) from None

    return split_key[0], split_key[1]


def uncompound_strings(strings: Sequence[str], separator: str | None = None) -> list[tuple[str, str]]:
    separator = separator or DEFAULT_COMPOUND_SEPARATOR
    return [uncompound_string(string=string, separator=separator) for string in strings]


@bear_enforce
def compound_key(collection: str, key: str, separator: str | None = None) -> str:
    separator = separator or DEFAULT_COMPOUND_SEPARATOR
    return compound_string(first=collection, second=key, separator=separator)


@bear_enforce
def uncompound_key(key: str, separator: str | None = None) -> tuple[str, str]:
    separator = separator or DEFAULT_COMPOUND_SEPARATOR
    return uncompound_string(string=key, separator=separator)


def prefix_key(key: str, prefix: str, separator: str | None = None) -> str:
    separator = separator or DEFAULT_PREFIX_SEPARATOR
    return compound_string(first=prefix, second=key, separator=separator)


def unprefix_key(key: str, prefix: str, separator: str | None = None) -> str:
    separator = separator or DEFAULT_PREFIX_SEPARATOR
    if not key.startswith(prefix + separator):
        msg = f"Key {key} is not prefixed with {prefix}{separator}"
        raise ValueError(msg)
    return key[len(prefix + separator) :]


def prefix_collection(collection: str, prefix: str, separator: str | None = None) -> str:
    separator = separator or DEFAULT_PREFIX_SEPARATOR
    return compound_string(first=prefix, second=collection, separator=separator)


def unprefix_collection(collection: str, prefix: str, separator: str | None = None) -> str:
    separator = separator or DEFAULT_PREFIX_SEPARATOR
    if not collection.startswith(prefix + separator):
        msg = f"Collection {collection} is not prefixed with {prefix}{separator}"
        raise ValueError(msg)
    return collection[len(prefix + separator) :]


def get_collections_from_compound_keys(compound_keys: Sequence[str], separator: str | None = None) -> list[str]:
    """Return a unique list of collections from a list of compound keys."""
    separator = separator or DEFAULT_COMPOUND_SEPARATOR
    return list({key_collection for key_collection, _ in uncompound_strings(strings=compound_keys, separator=separator)})


def get_keys_from_compound_keys(compound_keys: Sequence[str], collection: str, separator: str | None = None) -> list[str]:
    """Return all keys from a list of compound keys for a given collection."""
    separator = separator or DEFAULT_COMPOUND_SEPARATOR
    return [key for key_collection, key in uncompound_strings(strings=compound_keys, separator=separator) if key_collection == collection]
