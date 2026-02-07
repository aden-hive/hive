"""Security Configuration for Hive Framework.

Centralized security settings with secure defaults and validation.
"""

import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SecurityLevel(StrEnum):
    """Security strictness levels."""

    DEVELOPMENT = "development"  # Relaxed for local dev
    STAGING = "staging"  # Moderate security
    PRODUCTION = "production"  # Maximum security


@dataclass
class SecurityConfig:
    """Centralized security configuration.

    Uses secure defaults appropriate for production.
    Override only when explicitly needed.
    """

    # Security level
    level: SecurityLevel = SecurityLevel.PRODUCTION

    # Input validation
    max_input_length: int = 100_000  # 100KB max input
    max_output_length: int = 500_000  # 500KB max output
    max_memory_value_size: int = 1_000_000  # 1MB max memory value
    validate_all_inputs: bool = True
    sanitize_all_outputs: bool = True

    # Encryption
    encryption_algorithm: str = "AES-256-GCM"
    key_derivation_iterations: int = 100_000
    encrypt_secrets_at_rest: bool = True
    encrypt_logs: bool = False  # Only in high-security environments

    # Secrets
    mask_secrets_in_logs: bool = True
    secret_patterns: list[str] = field(default_factory=lambda: [
        r"(?i)(api[_-]?key|apikey)",
        r"(?i)(secret|password|passwd|pwd)",
        r"(?i)(token|bearer|auth)",
        r"(?i)(credential|cred)",
        r"sk-[a-zA-Z0-9]{20,}",  # OpenAI keys
        r"sk-ant-[a-zA-Z0-9-]{20,}",  # Anthropic keys
    ])

    # Audit
    audit_all_operations: bool = True
    audit_retention_days: int = 90
    audit_include_request_data: bool = False  # Privacy concern

    # Rate limiting (additional security layer)
    enable_request_throttling: bool = True
    max_requests_per_minute: int = 100
    max_tokens_per_minute: int = 100_000

    # Injection prevention
    block_code_injection: bool = True
    block_prompt_injection: bool = True
    block_sql_patterns: bool = True
    block_script_tags: bool = True

    # Network security
    allowed_hosts: list[str] = field(default_factory=list)
    blocked_ips: list[str] = field(default_factory=list)
    require_https: bool = True

    # Session security
    session_timeout_seconds: int = 3600  # 1 hour
    max_concurrent_sessions: int = 10
    rotate_session_tokens: bool = True

    @classmethod
    def for_development(cls) -> "SecurityConfig":
        """Relaxed config for local development."""
        return cls(
            level=SecurityLevel.DEVELOPMENT,
            validate_all_inputs=False,
            encrypt_secrets_at_rest=False,
            audit_all_operations=False,
            require_https=False,
        )

    @classmethod
    def for_production(cls) -> "SecurityConfig":
        """Maximum security for production."""
        return cls(
            level=SecurityLevel.PRODUCTION,
            # All defaults are already production-ready
        )

    def validate(self) -> list[str]:
        """Validate configuration, return list of warnings."""
        warnings = []

        if self.level == SecurityLevel.PRODUCTION:
            if not self.validate_all_inputs:
                warnings.append("Input validation disabled in production")
            if not self.encrypt_secrets_at_rest:
                warnings.append("Secret encryption disabled in production")
            if not self.require_https:
                warnings.append("HTTPS not required in production")
            if not self.mask_secrets_in_logs:
                warnings.append("Secret masking disabled in production")

        return warnings


# Global configuration
_security_config: SecurityConfig | None = None


def configure_security(
    level: SecurityLevel | str | None = None,
    **overrides: Any,
) -> SecurityConfig:
    """Configure security settings.

    Call once at application startup.

    Args:
        level: Security level (development/staging/production)
        **overrides: Override specific settings

    Returns:
        The configured SecurityConfig
    """
    global _security_config

    if level is None:
        # Auto-detect from environment
        env = os.environ.get("HIVE_ENV", "production").lower()
        valid_levels = [e.value for e in SecurityLevel]
        level = SecurityLevel(env) if env in valid_levels else SecurityLevel.PRODUCTION

    if isinstance(level, str):
        level = SecurityLevel(level)

    if level == SecurityLevel.DEVELOPMENT:
        config = SecurityConfig.for_development()
    else:
        config = SecurityConfig.for_production()

    # Apply overrides
    for key, value in overrides.items():
        if hasattr(config, key):
            setattr(config, key, value)

    # Validate and warn
    warnings = config.validate()
    if warnings:
        import logging
        logger = logging.getLogger(__name__)
        for warning in warnings:
            logger.warning(f"Security warning: {warning}")

    _security_config = config
    return config


def get_security_config() -> SecurityConfig:
    """Get the current security configuration."""
    global _security_config

    if _security_config is None:
        _security_config = configure_security()

    return _security_config


__all__ = [
    "SecurityConfig",
    "SecurityLevel",
    "configure_security",
    "get_security_config",
]
