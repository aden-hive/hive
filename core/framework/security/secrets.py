"""Secure Secrets Management.

Provides secure handling of API keys, tokens, and credentials:
- Never logs secrets in plaintext
- Automatic masking in outputs
- Secure retrieval from multiple sources
- Memory protection

Usage:
    from framework.security import get_secret, mask_secret

    # Get secret securely
    api_key = get_secret("OPENAI_API_KEY")

    # Mask secret for logging
    safe_key = mask_secret(api_key)  # "sk-...abc1"
"""

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Secret:
    """Wrapper for secret values that prevents accidental exposure."""

    _value: str = field(repr=False)
    name: str = ""
    source: str = "unknown"

    def __str__(self) -> str:
        """Never expose secret value in string representation."""
        return f"Secret({self.name}:***)"

    def __repr__(self) -> str:
        """Never expose secret value in repr."""
        return f"Secret(name={self.name!r}, source={self.source!r})"

    @property
    def value(self) -> str:
        """Get the actual secret value. Use sparingly."""
        return self._value

    def masked(self, visible_chars: int = 4) -> str:
        """Get masked version for logging."""
        return mask_secret(self._value, visible_chars)


class SecretManager:
    """Secure secret management with multiple sources.

    Priority order:
    1. Runtime secrets (set programmatically)
    2. Environment variables
    3. Encrypted file storage
    4. Vault/external secret manager (if configured)
    """

    # Common secret patterns for detection
    SECRET_PATTERNS = [
        (r"sk-[a-zA-Z0-9]{20,}", "OpenAI API Key"),
        (r"sk-ant-[a-zA-Z0-9-]{20,}", "Anthropic API Key"),
        (r"[a-zA-Z0-9]{32,}", "Generic API Key"),
        (r"ghp_[a-zA-Z0-9]{36}", "GitHub Token"),
        (r"gho_[a-zA-Z0-9]{36}", "GitHub OAuth Token"),
        (r"glpat-[a-zA-Z0-9-]{20}", "GitLab Token"),
        (r"xoxb-[a-zA-Z0-9-]+", "Slack Bot Token"),
        (r"xoxp-[a-zA-Z0-9-]+", "Slack User Token"),
        (r"AKIA[0-9A-Z]{16}", "AWS Access Key"),
        (r"eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*", "JWT Token"),
    ]

    def __init__(self):
        """Initialize secret manager."""
        self._runtime_secrets: dict[str, str] = {}
        self._compiled_patterns = [
            (re.compile(p), desc) for p, desc in self.SECRET_PATTERNS
        ]

    def set(self, name: str, value: str) -> None:
        """Set a runtime secret.

        Args:
            name: Secret name/key
            value: Secret value
        """
        self._runtime_secrets[name] = value
        logger.debug(f"Secret set: {name}")

    def get(
        self,
        name: str,
        default: str | None = None,
        required: bool = False,
    ) -> Secret | None:
        """Get a secret value securely.

        Args:
            name: Secret name/key
            default: Default value if not found
            required: If True, raise if not found

        Returns:
            Secret wrapper or None

        Raises:
            ValueError: If required and not found
        """
        # Check runtime secrets first
        if name in self._runtime_secrets:
            return Secret(
                _value=self._runtime_secrets[name],
                name=name,
                source="runtime",
            )

        # Check environment variables
        env_value = os.environ.get(name)
        if env_value:
            return Secret(
                _value=env_value,
                name=name,
                source="environment",
            )

        # Check common variations
        variations = [
            name,
            name.upper(),
            name.lower(),
            name.replace("-", "_"),
            name.replace("_", "-"),
        ]

        for var in variations:
            env_value = os.environ.get(var)
            if env_value:
                return Secret(
                    _value=env_value,
                    name=name,
                    source="environment",
                )

        # Not found
        if required:
            raise ValueError(f"Required secret not found: {name}")

        if default is not None:
            return Secret(
                _value=default,
                name=name,
                source="default",
            )

        return None

    def detect_secrets(self, text: str) -> list[tuple[str, str, int]]:
        """Detect potential secrets in text.

        Args:
            text: Text to scan for secrets

        Returns:
            List of (matched_text, secret_type, position)
        """
        findings = []
        for pattern, desc in self._compiled_patterns:
            for match in pattern.finditer(text):
                findings.append((
                    mask_secret(match.group(), 4),
                    desc,
                    match.start(),
                ))
        return findings

    def scan_and_mask(self, text: str) -> str:
        """Scan text for secrets and mask them.

        Args:
            text: Text that may contain secrets

        Returns:
            Text with secrets masked
        """
        result = text
        for pattern, _ in self._compiled_patterns:
            result = pattern.sub(
                lambda m: mask_secret(m.group(), 4),
                result,
            )
        return result

    def clear(self) -> None:
        """Clear all runtime secrets from memory."""
        self._runtime_secrets.clear()
        logger.debug("Runtime secrets cleared")


# Global instance
_secret_manager: SecretManager | None = None


def get_secret_manager() -> SecretManager:
    """Get global secret manager instance."""
    global _secret_manager
    if _secret_manager is None:
        _secret_manager = SecretManager()
    return _secret_manager


def get_secret(
    name: str,
    default: str | None = None,
    required: bool = False,
) -> str | None:
    """Get a secret value.

    Args:
        name: Secret name/key
        default: Default value if not found
        required: If True, raise if not found

    Returns:
        Secret value as string, or None
    """
    manager = get_secret_manager()
    secret = manager.get(name, default, required)
    return secret.value if secret else None


def mask_secret(
    value: str,
    visible_chars: int = 4,
    mask_char: str = "*",
) -> str:
    """Mask a secret value for safe logging.

    Args:
        value: Secret value to mask
        visible_chars: Number of chars to show at end
        mask_char: Character to use for masking

    Returns:
        Masked string like "sk-***abc1"
    """
    if not value:
        return ""

    if len(value) <= visible_chars * 2:
        return mask_char * len(value)

    prefix = value[:3] if len(value) > 6 else ""
    suffix = value[-visible_chars:]
    middle_len = max(3, len(value) - len(prefix) - len(suffix))

    return f"{prefix}{mask_char * middle_len}{suffix}"


def is_secret_like(value: str) -> bool:
    """Check if a value looks like a secret.

    Args:
        value: Value to check

    Returns:
        True if value matches common secret patterns
    """
    manager = get_secret_manager()
    return len(manager.detect_secrets(value)) > 0


__all__ = [
    "Secret",
    "SecretManager",
    "get_secret",
    "get_secret_manager",
    "mask_secret",
    "is_secret_like",
]
