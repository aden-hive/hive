"""Low-level string sanitization functions.

This module provides low-level functions for sanitizing strings by replacing
or removing invalid characters. For higher-level sanitization strategies,
see the sanitization module.
"""

import hashlib
from enum import Enum

from key_value.aio._utils.beartype import bear_enforce

MINIMUM_MAX_LENGTH = 16

DEFAULT_HASH_FRAGMENT_SIZE = 8

DEFAULT_HASH_FRAGMENT_SEPARATOR = "-"
DEFAULT_REPLACEMENT_CHARACTER = "_"

LOWERCASE_ALPHABET = "abcdefghijklmnopqrstuvwxyz"
UPPERCASE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
NUMBERS = "0123456789"
ALPHANUMERIC_CHARACTERS = LOWERCASE_ALPHABET + UPPERCASE_ALPHABET + NUMBERS


def generate_hash_fragment(
    value: str,
    size: int = DEFAULT_HASH_FRAGMENT_SIZE,
) -> str:
    """Generate a hash fragment of the value."""

    return hashlib.sha256(value.encode()).hexdigest()[:size]


class HashFragmentMode(str, Enum):
    """Mode for adding hash fragments to sanitized strings."""

    ALWAYS = "always"
    NEVER = "never"
    ONLY_IF_CHANGED = "only_if_changed"


def sanitize_characters_in_string(value: str, allowed_characters: str, replace_with: str) -> str:
    """Replace characters in a string.

    If multiple characters are in a row that are not allowed, only
    the first one will be replaced. The rest will be removed. If all
    characters are not allowed, an empty string will be returned.

    Args:
        value: The value to replace characters in.
        allowed_characters: The characters that are allowed.
        replace_with: The characters to replace with.

    Returns:
        The sanitized string.
    """
    new_value = ""
    last_char_was_replaced = False

    for char in value:
        if char in allowed_characters:
            new_value += char
            last_char_was_replaced = False
        else:
            if last_char_was_replaced:
                continue

            new_value += replace_with
            last_char_was_replaced = True

    if len(new_value) == 1 and last_char_was_replaced:
        return ""

    return new_value


def _truncate_to_bytes(value: str, max_bytes: int, encoding: str = "utf-8") -> str:
    """Truncate a string to fit within max_bytes when encoded, without splitting multi-byte characters.

    Args:
        value: The string to truncate.
        max_bytes: The maximum number of bytes.
        encoding: The encoding to use (default: utf-8).

    Returns:
        The truncated string that fits within max_bytes.
    """
    encoded = value.encode(encoding)
    if len(encoded) <= max_bytes:
        return value

    # Binary search to find the longest substring that fits
    left, right = 0, len(value)
    result = ""

    while left <= right:
        mid = (left + right) // 2
        candidate = value[:mid]
        if len(candidate.encode(encoding)) <= max_bytes:
            result = candidate
            left = mid + 1
        else:
            right = mid - 1

    return result


@bear_enforce
def sanitize_string(
    value: str,
    max_length: int,
    allowed_characters: str | None = None,
    replacement_character: str = DEFAULT_REPLACEMENT_CHARACTER,
    hash_fragment_separator: str = DEFAULT_HASH_FRAGMENT_SEPARATOR,
    hash_fragment_mode: HashFragmentMode = HashFragmentMode.ONLY_IF_CHANGED,
    hash_fragment_length: int = DEFAULT_HASH_FRAGMENT_SIZE,
    length_is_bytes: bool = False,
) -> str:
    """Sanitize the value, replacing characters and optionally adding a fragment a hash of the value if requested.

    If the entire value is sanitized and hash_fragment_mode is HashFragmentMode.ALWAYS or HashFragmentMode.ONLY_IF_CHANGED,
    the value returned will be the hash fragment only.

    If the entire value is sanitized and hash_fragment_mode is HashFragmentMode.NEVER, an error will be raised.

    Args:
        value: The value to sanitize.
        max_length: The maximum length of the value (with hash fragment). Interpreted as bytes if length_is_bytes is True.
        allowed_characters: The allowed characters in the value.
        replacement_character: The character to replace invalid characters with.
        hash_fragment_separator: The separator to add between the value and the hash fragment.
        hash_fragment_mode: The mode to add the hash fragment.
        hash_fragment_length: The length of the hash fragment.
        length_is_bytes: If True, max_length is interpreted as bytes instead of characters.

    Returns:
        The sanitized string.
    """
    if max_length < MINIMUM_MAX_LENGTH:
        msg = f"max_length must be greater than or equal to {MINIMUM_MAX_LENGTH}"
        raise ValueError(msg)

    if hash_fragment_length > max_length // 2:
        msg = "hash_fragment_length must be less than or equal to half of max_length"
        raise ValueError(msg)

    hash_fragment: str = generate_hash_fragment(value=value, size=hash_fragment_length)
    hash_fragment_size_required: int = (
        len((hash_fragment_separator + hash_fragment).encode("utf-8"))
        if length_is_bytes
        else len(hash_fragment_separator) + len(hash_fragment)
    )

    sanitized_value: str = (
        sanitize_characters_in_string(value=value, allowed_characters=allowed_characters, replace_with=replacement_character)
        if allowed_characters
        else value
    )

    actual_max_length: int

    if hash_fragment_mode == HashFragmentMode.ALWAYS:
        actual_max_length = max_length - hash_fragment_size_required
        sanitized_value = _truncate_to_bytes(sanitized_value, actual_max_length) if length_is_bytes else sanitized_value[:actual_max_length]

        if not sanitized_value:
            return hash_fragment

        return sanitized_value + hash_fragment_separator + hash_fragment

    if hash_fragment_mode == HashFragmentMode.ONLY_IF_CHANGED:
        sanitized_value = _truncate_to_bytes(sanitized_value, max_length) if length_is_bytes else sanitized_value[:max_length]

        if value == sanitized_value:
            return value

        actual_max_length = max_length - hash_fragment_size_required
        sanitized_value = _truncate_to_bytes(sanitized_value, actual_max_length) if length_is_bytes else sanitized_value[:actual_max_length]

        if not sanitized_value:
            return hash_fragment

        return sanitized_value + hash_fragment_separator + hash_fragment

    if not sanitized_value:
        msg = "Entire value was sanitized and hash_fragment_mode is HashFragmentMode.NEVER"
        raise ValueError(msg)

    return _truncate_to_bytes(sanitized_value, max_length) if length_is_bytes else sanitized_value[:max_length]


@bear_enforce
def hash_excess_length(value: str, max_length: int, length_is_bytes: bool = False) -> str:
    """Hash part of the value if it exceeds the maximum length.

    This operation will truncate the value to the maximum length minus 8 characters
    and will swap the last 8 characters with the first 8 characters of the generated hash.

    Args:
        value: The value to hash.
        max_length: The maximum length of the value. Must be greater than or equal to 16.
            If length_is_bytes is True, this is interpreted as bytes.
        length_is_bytes: If True, max_length is interpreted as bytes instead of characters.

    Returns:
        The hashed value if the value exceeds the maximum length, otherwise the original value.
    """
    if max_length < MINIMUM_MAX_LENGTH:
        msg = f"max_length must be greater than or equal to {MINIMUM_MAX_LENGTH}"
        raise ValueError(msg)

    # Check if truncation is needed
    current_length = len(value.encode("utf-8")) if length_is_bytes else len(value)
    if current_length <= max_length:
        return value

    # Truncate to max_length - 8 to make room for hash
    truncated_value = _truncate_to_bytes(value, max_length - 8) if length_is_bytes else value[: max_length - 8]

    hash_of_value = hashlib.sha256(value.encode()).hexdigest()
    first_eight_of_hash = hash_of_value[:8]

    return truncated_value + first_eight_of_hash
