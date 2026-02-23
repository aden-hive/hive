"""Pre-flight credential validation with actionable error messages.

This module provides user-friendly error messages when LLM provider
credentials are missing, invalid, or expired. Instead of cryptic errors
like ``completion() got unexpected keyword argument 'model'``, users see
clear instructions on what to fix and how.

Resolves: https://github.com/aden-hive/hive/issues/4391

Example::

    from framework.credentials.validator import CredentialValidator

    # Validate before making LLM calls
    error = CredentialValidator.validate("anthropic")
    if error:
        print(error.format_message())
        raise error.to_exception()
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

from framework.credentials.models import CredentialError


# ---------------------------------------------------------------------------
# Provider registry — maps provider names to their credential metadata.
# ---------------------------------------------------------------------------

_PROVIDER_REGISTRY: dict[str, dict] = {
    "anthropic": {
        "display_name": "Anthropic",
        "env_var": "ANTHROPIC_API_KEY",
        "console_url": "https://console.anthropic.com/settings/keys",
        "config_example": '{\n  "anthropic_api_key": "sk-ant-your-key"\n}',
        "key_pattern": r"^sk-ant-",
        "key_hint": "starts with 'sk-ant-'",
    },
    "openai": {
        "display_name": "OpenAI",
        "env_var": "OPENAI_API_KEY",
        "console_url": "https://platform.openai.com/api-keys",
        "config_example": '{\n  "openai_api_key": "sk-your-key"\n}',
        "key_pattern": r"^sk-",
        "key_hint": "starts with 'sk-'",
    },
    "gemini": {
        "display_name": "Google Gemini",
        "env_var": "GEMINI_API_KEY",
        "console_url": "https://aistudio.google.com/apikey",
        "config_example": '{\n  "gemini_api_key": "your-key"\n}',
        "key_pattern": r"^AI",
        "key_hint": "starts with 'AI'",
    },
    "mistral": {
        "display_name": "Mistral AI",
        "env_var": "MISTRAL_API_KEY",
        "console_url": "https://console.mistral.ai/api-keys/",
        "config_example": '{\n  "mistral_api_key": "your-key"\n}',
        "key_pattern": r".",
        "key_hint": "",
    },
    "groq": {
        "display_name": "Groq",
        "env_var": "GROQ_API_KEY",
        "console_url": "https://console.groq.com/keys",
        "config_example": '{\n  "groq_api_key": "gsk_your-key"\n}',
        "key_pattern": r"^gsk_",
        "key_hint": "starts with 'gsk_'",
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "env_var": "DEEPSEEK_API_KEY",
        "console_url": "https://platform.deepseek.com/api_keys",
        "config_example": '{\n  "deepseek_api_key": "your-key"\n}',
        "key_pattern": r".",
        "key_hint": "",
    },
}

# Model prefix → provider mapping for auto-detection.
_MODEL_PROVIDER_MAP: list[tuple[str, str]] = [
    ("claude", "anthropic"),
    ("anthropic/", "anthropic"),
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("chatgpt", "openai"),
    ("openai/", "openai"),
    ("gemini", "gemini"),
    ("gemini/", "gemini"),
    ("mistral", "mistral"),
    ("groq/", "groq"),
    ("llama", "groq"),
    ("mixtral", "groq"),
    ("deepseek", "deepseek"),
]


@dataclass
class CredentialIssue:
    """User-friendly credential error with fix instructions.

    Attributes:
        provider: Human-readable provider name (e.g., "Anthropic").
        env_var: Environment variable name (e.g., "ANTHROPIC_API_KEY").
        error_type: One of "missing", "invalid", or "expired".
        console_url: URL where the user can obtain/regenerate keys.
        config_example: Example JSON for ``~/.hive/config.json``.
        key_hint: Hint about expected key format.
    """

    provider: str
    env_var: str
    error_type: str  # "missing", "invalid", "expired"
    console_url: str
    config_example: str
    key_hint: str = ""
    extra_details: list[str] = field(default_factory=list)

    def format_message(self) -> str:
        """Generate actionable error message with step-by-step fix instructions.

        Returns:
            A multi-line string with a nicely formatted error box.
        """
        if self.error_type == "missing":
            return self._format_missing()
        elif self.error_type == "invalid":
            return self._format_invalid()
        elif self.error_type == "expired":
            return self._format_expired()
        return self._format_missing()  # Fallback

    def _format_missing(self) -> str:
        """Format message for a missing credential."""
        lines = [
            "",
            "╔══════════════════════════════════════════════════════════════╗",
            f"║  ❌ {self.provider} API Key Not Found",
            "╚══════════════════════════════════════════════════════════════╝",
            "",
            f"The {self.provider} API requires an API key, but none was found.",
            "",
            f"📍 Missing: {self.env_var} environment variable",
            "",
            "🔧 How to Fix:",
            "",
            "  1. Get your API key:",
            f"     👉 {self.console_url}",
            "",
            "  2. Set the environment variable:",
            "",
            "     # Linux/Mac:",
            f'     export {self.env_var}="your-api-key-here"',
            "",
            "     # Windows:",
            f"     set {self.env_var}=your-api-key-here",
            "",
            "  3. Or add to config file:",
            "",
            "     # ~/.hive/config.json",
            f"     {self.config_example}",
            "",
            "  4. Verify setup:",
            "     hive doctor  # Run diagnostic check",
            "",
            "📚 Full guide: https://docs.hive.aden.ai/credentials",
            "",
        ]
        return "\n".join(lines)

    def _format_invalid(self) -> str:
        """Format message for an invalid credential."""
        # Safely show last 4 chars of the key for identification
        current_key = os.getenv(self.env_var, "")
        masked = f"...{current_key[-4:]}" if len(current_key) > 4 else "(set but short)"

        lines = [
            "",
            "╔══════════════════════════════════════════════════════════════╗",
            f"║  ❌ {self.provider} API Key Invalid",
            "╚══════════════════════════════════════════════════════════════╝",
            "",
            f"The {self.provider} API key doesn't match the expected format.",
            "",
            f"🔧 How to Fix:",
            "",
            f"  1. Check if your key is correct:",
            f"     Current: {self.env_var}={masked}",
        ]

        if self.key_hint:
            lines.append(f"     Expected: key {self.key_hint}")

        lines.extend([
            "",
            "  2. Generate a new key:",
            f"     👉 {self.console_url}",
            "",
            "  3. Update your environment variable:",
            f'     export {self.env_var}="new-key-here"',
            "",
            "  4. Common issues:",
            "     • Extra spaces or newlines in the key value",
            "     • Using a revoked or deleted key",
            "     • Copying only part of the key",
            "",
            "📚 More help: https://docs.hive.aden.ai/troubleshooting",
            "",
        ])
        return "\n".join(lines)

    def _format_expired(self) -> str:
        """Format message for an expired credential."""
        lines = [
            "",
            "╔══════════════════════════════════════════════════════════════╗",
            f"║  ❌ {self.provider} Credentials Expired",
            "╚══════════════════════════════════════════════════════════════╝",
            "",
            f"Your {self.provider} credentials have expired or been revoked.",
            "",
            "🔧 How to Fix:",
            "",
            "  1. Generate new credentials:",
            f"     👉 {self.console_url}",
            "",
            "  2. Update configuration:",
            f'     export {self.env_var}="new-key-here"',
            "",
            "📚 Credential rotation guide: https://docs.hive.aden.ai/rotation",
            "",
        ]
        return "\n".join(lines)

    def to_exception(self) -> CredentialError:
        """Convert this issue into a ``CredentialError`` with the formatted message.

        Returns:
            A CredentialError whose string representation is the human-readable
            actionable error message.
        """
        return CredentialError(self.format_message())


class CredentialValidator:
    """Validates LLM credentials before use and provides helpful errors.

    Uses a registry of known providers to check environment variables for
    presence and basic format validity.

    Example::

        error = CredentialValidator.validate("anthropic")
        if error:
            print(error.format_message())

        # Or validate by model name
        error = CredentialValidator.validate_for_model("claude-3-haiku-20240307")
        if error:
            raise error.to_exception()
    """

    PROVIDERS = _PROVIDER_REGISTRY

    @classmethod
    def get_provider_for_model(cls, model: str) -> Optional[str]:
        """Determine the provider name from a model identifier.

        Args:
            model: Model string (e.g., "claude-3-haiku-20240307",
                   "gpt-4o-mini", "gemini/gemini-1.5-flash").

        Returns:
            Provider key (e.g., "anthropic") or None if unrecognised.
        """
        model_lower = model.lower()
        for prefix, provider in _MODEL_PROVIDER_MAP:
            if model_lower.startswith(prefix):
                return provider
        return None

    @classmethod
    def validate(cls, provider: str) -> Optional[CredentialIssue]:
        """Validate credentials for a provider.

        Args:
            provider: Provider key (e.g., "anthropic", "openai").

        Returns:
            A ``CredentialIssue`` if validation fails, ``None`` if valid.
        """
        if provider not in cls.PROVIDERS:
            return None  # Unknown provider — skip validation

        config = cls.PROVIDERS[provider]
        api_key = os.getenv(config["env_var"])

        # Phase 1: Check presence
        if not api_key or not api_key.strip():
            return CredentialIssue(
                provider=config["display_name"],
                env_var=config["env_var"],
                error_type="missing",
                console_url=config["console_url"],
                config_example=config["config_example"],
                key_hint=config.get("key_hint", ""),
            )

        # Phase 2: Basic format check (only if pattern is meaningful)
        pattern = config.get("key_pattern", ".")
        if pattern != "." and not re.match(pattern, api_key.strip()):
            return CredentialIssue(
                provider=config["display_name"],
                env_var=config["env_var"],
                error_type="invalid",
                console_url=config["console_url"],
                config_example=config["config_example"],
                key_hint=config.get("key_hint", ""),
            )

        return None  # Valid!

    @classmethod
    def validate_for_model(cls, model: str) -> Optional[CredentialIssue]:
        """Validate credentials based on a model name.

        Convenience method that auto-detects the provider from the model
        string and validates accordingly.

        Args:
            model: Model identifier (e.g., "claude-3-haiku-20240307").

        Returns:
            A ``CredentialIssue`` if validation fails, ``None`` if valid.
        """
        provider = cls.get_provider_for_model(model)
        if provider is None:
            return None  # Can't determine provider — skip
        return cls.validate(provider)

    @classmethod
    def validate_multiple(cls, providers: list[str]) -> list[CredentialIssue]:
        """Validate credentials for multiple providers.

        Args:
            providers: List of provider keys to validate.

        Returns:
            List of ``CredentialIssue`` objects for all failures.
        """
        issues = []
        for provider in providers:
            issue = cls.validate(provider)
            if issue is not None:
                issues.append(issue)
        return issues

    @classmethod
    def format_multiple_issues(cls, issues: list[CredentialIssue]) -> str:
        """Format multiple credential issues into a single summary.

        Args:
            issues: List of credential issues to format.

        Returns:
            Combined human-readable error string.
        """
        if not issues:
            return ""

        parts = []
        for issue in issues:
            parts.append(issue.format_message())

        header = (
            "\n╔══════════════════════════════════════════════════════════════╗\n"
            f"║  ❌ {len(issues)} Credential Issue(s) Found\n"
            "╚══════════════════════════════════════════════════════════════╝\n"
        )
        return header + "\n".join(parts)
