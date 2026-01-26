"""Sanitization strategies for key and collection names.

This module provides strategies for sanitizing keys and collection names to comply
with backend store requirements. Different stores have different character restrictions
and length limits, so multiple strategies are provided.

The strategies also prevent collision between user-provided keys and sanitized keys
by using reserved prefixes (H_ for hashed keys, S_ for sanitized keys) and validating
that user input doesn't use these prefixes.
"""

import hashlib
from abc import ABC, abstractmethod
from enum import Enum

from key_value.shared.errors.key_value import InvalidKeyError
from key_value.shared.utils.sanitize import sanitize_characters_in_string


class HashFragmentMode(Enum):
    """Mode for adding hash fragments to sanitized strings."""

    ALWAYS = "always"
    """Always add hash fragment, even if string wasn't modified."""

    ONLY_IF_CHANGED = "only_if_changed"
    """Only add hash fragment if the string was modified during sanitization."""

    NEVER = "never"
    """Never add hash fragment."""


class SanitizationStrategy(ABC):
    """Base class for key/collection sanitization strategies.

    Sanitization strategies convert user-provided keys and collection names into
    formats that are compatible with backend store requirements. This includes:
    - Replacing invalid characters
    - Truncating to maximum length
    - Adding hash fragments for uniqueness
    - Prefixing to prevent collisions with user keys
    """

    @abstractmethod
    def sanitize(self, value: str) -> str:
        """Sanitize a key or collection name for storage.

        Args:
            value: The user-provided key or collection name.

        Returns:
            The sanitized value suitable for storage.
        """

    @abstractmethod
    def validate(self, value: str) -> None:
        """Validate that a user-provided value doesn't use reserved patterns.

        Args:
            value: The user-provided key or collection name.

        Raises:
            InvalidKeyError: If the value uses reserved prefixes or patterns.
        """

    def try_unsanitize(self, value: str) -> str | None:  # noqa: ARG002
        """Attempt to reverse sanitization (for debugging/enumeration).

        This is optional and may not be possible for all strategies (e.g., hashing
        is irreversible). The default implementation returns None.

        Args:
            value: The sanitized value.

        Returns:
            The original value if recoverable, None otherwise.
        """
        return None


class PassthroughStrategy(SanitizationStrategy):
    """Pass-through strategy that performs no sanitization.

    Use this for stores that have no character or length restrictions (e.g., Redis,
    DynamoDB, MongoDB when using document fields for keys).
    """

    def sanitize(self, value: str) -> str:
        """Return the value unchanged."""
        return value

    def validate(self, value: str) -> None:
        """No validation needed for pass-through strategy."""

    def try_unsanitize(self, value: str) -> str | None:
        """Return the value unchanged since no sanitization occurred."""
        return value


MINIMUM_HASH_LENGTH = 8
MAXIMUM_HASH_LENGTH = 64


class AlwaysHashStrategy(SanitizationStrategy):
    """Strategy that always hashes keys."""

    def __init__(self, hash_length: int = 64) -> None:
        """Initialize the always hash strategy.

        Args:
            hash_length: The length of the hash to generate. Must be greater than 8 and less than 64.
        """
        if hash_length <= MINIMUM_HASH_LENGTH or hash_length > MAXIMUM_HASH_LENGTH:
            msg = f"hash_length must be greater than {MINIMUM_HASH_LENGTH} and less than {MAXIMUM_HASH_LENGTH}: {hash_length}"
            raise ValueError(msg)

        self.hash_length: int = hash_length

    def sanitize(self, value: str) -> str:
        """Hash the value."""
        return hashlib.sha256(value.encode()).hexdigest()[: self.hash_length]

    def validate(self, value: str) -> None:
        """No validation needed for always hash strategy."""

    def try_unsanitize(self, value: str) -> str | None:
        """Return the value unchanged since no sanitization occurred."""
        return value


class HashExcessLengthStrategy(SanitizationStrategy):
    """Strategy that hashes keys exceeding a maximum length.

    This strategy is used by stores like Memcached that accept any characters but
    have strict length limits. Keys exceeding the limit are hashed using SHA256
    and prefixed with 'H_' to prevent collisions with user-provided keys.

    Args:
        max_length: Maximum key length before hashing is applied. Defaults to 240.
    """

    def __init__(self, max_length: int = 240) -> None:
        """Initialize the hashing strategy.

        Args:
            max_length: Maximum key length before hashing is applied.
        """
        self.max_length = max_length

    def sanitize(self, value: str) -> str:
        """Hash the value if it exceeds max_length, otherwise return unchanged.

        Keys exceeding max_length are hashed using SHA256 and prefixed with 'H_'.
        The hash is truncated to (max_length - 2) characters to fit within the limit.

        Args:
            value: The key to sanitize.

        Returns:
            The original value if within limit, or 'H_' + hash if too long.
        """
        if len(value) > self.max_length:
            sha256_hash = hashlib.sha256(value.encode()).hexdigest()
            # Prefix with H_ and truncate to fit within max_length
            return f"H_{sha256_hash[: self.max_length - 2]}"
        return value

    def validate(self, value: str) -> None:
        """Validate that the value doesn't start with reserved 'H_' prefix.

        Args:
            value: The user-provided key.

        Raises:
            InvalidKeyError: If the value starts with 'H_' or 'S_'.
        """
        if value.startswith(("H_", "S_")):
            msg = f"Keys cannot start with reserved prefixes 'H_' or 'S_': {value}"
            raise InvalidKeyError(msg)


class HybridSanitizationStrategy(SanitizationStrategy):
    """Strategy that replaces invalid characters and adds hash fragments.

    This strategy is used by stores with character restrictions (e.g., Elasticsearch,
    Keyring, Windows Registry). Invalid characters are replaced with a safe character,
    and a hash fragment is added for uniqueness. The result is prefixed with 'S_' to
    prevent collisions with user-provided keys.

    Args:
        max_length: Maximum length after sanitization. Defaults to 240.
        allowed_characters: List of allowed characters. Defaults to alphanumeric + dash + underscore.
        replacement_character: Character to use for invalid characters. Defaults to underscore.
        hash_fragment_mode: When to add hash fragments. Defaults to ONLY_IF_CHANGED.
        hash_fragment_length: Length of hash fragment. Defaults to 8.
    """

    def __init__(
        self,
        max_length: int = 240,
        allowed_characters: str | None = None,
        replacement_character: str = "_",
        hash_fragment_mode: HashFragmentMode = HashFragmentMode.ONLY_IF_CHANGED,
        hash_fragment_length: int = 8,
    ) -> None:
        """Initialize the character sanitization strategy.

        Args:
            max_length: Maximum length after sanitization.
            allowed_characters: String of allowed characters. Defaults to None (all characters allowed).
            replacement_character: Character to use for invalid characters.
            hash_fragment_mode: When to add hash fragments.
            hash_fragment_length: Length of hash fragment.
        """
        self.max_length = max_length
        self.allowed_characters: str | None = allowed_characters
        self.replacement_character = replacement_character
        self.hash_fragment_mode = hash_fragment_mode
        self.hash_fragment_length = hash_fragment_length

    def sanitize(self, value: str) -> str:
        """Replace invalid characters and add hash fragment if needed.

        The sanitization process:
        1. Replace invalid characters with replacement_character
        2. If changed (and mode is ONLY_IF_CHANGED), add hash fragment
        3. Truncate to max_length (accounting for prefix and hash fragment)
        4. Prefix with 'S_' if sanitization occurred

        Args:
            value: The key or collection name to sanitize.

        Returns:
            The sanitized value with 'S_' prefix if modified.
        """
        sanitized: str = value
        if self.allowed_characters:
            sanitized = sanitize_characters_in_string(
                value=value, allowed_characters=self.allowed_characters, replace_with=self.replacement_character
            )

        # Check if sanitization occurred
        changed = sanitized != value

        # Determine if we need to add hash fragment
        add_hash = self.hash_fragment_mode == HashFragmentMode.ALWAYS or (
            self.hash_fragment_mode == HashFragmentMode.ONLY_IF_CHANGED and changed
        )

        if add_hash:
            # Generate hash fragment
            hash_fragment = hashlib.sha256(value.encode()).hexdigest()[: self.hash_fragment_length]

            # Calculate space needed for 'S_' prefix + '-' separator + hash
            overhead = 2 + 1 + self.hash_fragment_length  # 'S_' + '-' + hash

            # Truncate sanitized value to fit within max_length
            max_value_length = self.max_length - overhead
            if len(sanitized) > max_value_length:
                sanitized = sanitized[:max_value_length]

            # Add prefix, hash fragment, and return
            return f"S_{sanitized}-{hash_fragment}"

        # No hash needed - but still need to enforce max_length and prefix if changed
        needs_truncation = len(sanitized) > self.max_length
        if needs_truncation:
            sanitized = sanitized[: self.max_length]
            changed = True

        if changed:
            # Add S_ prefix since we modified the input
            prefixed = f"S_{sanitized}"
            # Ensure the prefixed result fits within max_length
            if len(prefixed) > self.max_length:
                sanitized = sanitized[: self.max_length - 2]
                prefixed = f"S_{sanitized}"
            return prefixed

        return sanitized

    def validate(self, value: str) -> None:
        """Validate that the value doesn't start with reserved prefixes.

        Args:
            value: The user-provided key or collection name.

        Raises:
            InvalidKeyError: If the value starts with 'H_' or 'S_'.
        """
        if value.startswith(("H_", "S_")):
            msg = f"Keys cannot start with reserved prefixes 'H_' or 'S_': {value}"
            raise InvalidKeyError(msg)
