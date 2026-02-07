"""Input Validation and Sanitization.

Provides defense-in-depth input validation to prevent:
- Injection attacks (SQL, command, code)
- Prompt injection attempts
- Buffer overflow via large inputs
- Malformed data exploitation

Usage:
    from framework.security import validate_input, InputValidator

    # Quick validation
    result = validate_input(user_data, max_length=10000)
    if not result.is_valid:
        raise ValueError(result.errors)

    # Custom validator
    validator = InputValidator(config)
    result = validator.validate(data, schema=MySchema)
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Any, TypeVar
from enum import StrEnum

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ThreatType(StrEnum):
    """Types of security threats detected."""

    INJECTION = "injection"
    PROMPT_INJECTION = "prompt_injection"
    CODE_INJECTION = "code_injection"
    SQL_INJECTION = "sql_injection"
    COMMAND_INJECTION = "command_injection"
    XSS = "xss"
    PATH_TRAVERSAL = "path_traversal"
    OVERSIZED = "oversized"
    MALFORMED = "malformed"


@dataclass
class ValidationResult:
    """Result of input validation."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    threats_detected: list[ThreatType] = field(default_factory=list)
    sanitized_value: Any = None

    def raise_if_invalid(self, message: str = "Validation failed") -> None:
        """Raise ValueError if validation failed."""
        if not self.is_valid:
            raise ValueError(f"{message}: {'; '.join(self.errors)}")


class InputValidator:
    """Comprehensive input validator with threat detection."""

    # Dangerous patterns for injection detection
    INJECTION_PATTERNS = {
        ThreatType.SQL_INJECTION: [
            r"(?i)\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|ALTER|CREATE)\b.*\b(FROM|INTO|TABLE|DATABASE)\b",
            r"(?i)(\-\-|\/\*|\*\/|;)",  # SQL comments
            r"(?i)\bOR\b\s+\d+\s*=\s*\d+",  # OR 1=1
            r"(?i)'\s*OR\s*'",  # String-based injection
        ],
        ThreatType.COMMAND_INJECTION: [
            r"[;&|`$]",  # Shell metacharacters
            r"(?i)\b(bash|sh|cmd|powershell|exec|eval|system)\b",
            r"\$\([^)]+\)",  # Command substitution
            r"`[^`]+`",  # Backtick execution
        ],
        ThreatType.CODE_INJECTION: [
            r"(?i)\b(__import__|exec|eval|compile|globals|locals)\s*\(",
            r"(?i)\bimport\s+(os|subprocess|sys|shutil)",
            r"(?i)\bopen\s*\([^)]*['\"]w['\"]",  # File write
        ],
        ThreatType.XSS: [
            r"<script\b[^>]*>",
            r"javascript\s*:",
            r"on\w+\s*=",  # Event handlers
            r"<\s*iframe",
        ],
        ThreatType.PATH_TRAVERSAL: [
            r"\.\./",
            r"\.\.\\",
            r"%2e%2e%2f",  # URL encoded
            r"%2e%2e/",
            r"\.\.%2f",
        ],
        ThreatType.PROMPT_INJECTION: [
            r"(?i)ignore\s+(all\s+)?previous\s+instructions",
            r"(?i)disregard\s+(all\s+)?previous",
            r"(?i)forget\s+(everything|all)",
            r"(?i)you\s+are\s+now\s+a",
            r"(?i)new\s+instruction[s]?\s*:",
            r"(?i)system\s*prompt\s*:",
            r"(?i)\[SYSTEM\]",
            r"(?i)<\|system\|>",
            r"(?i)###\s*instruction",
        ],
    }

    def __init__(self, config: Any = None):
        """Initialize validator with optional config."""
        from framework.security.config import get_security_config

        self.config = config or get_security_config()
        self._compiled_patterns: dict[ThreatType, list[re.Pattern]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns for performance."""
        for threat_type, patterns in self.INJECTION_PATTERNS.items():
            self._compiled_patterns[threat_type] = [
                re.compile(p) for p in patterns
            ]

    def validate(
        self,
        value: Any,
        *,
        max_length: int | None = None,
        check_injections: bool = True,
        check_prompt_injection: bool = True,
        allowed_types: tuple | None = None,
        schema: Any = None,
    ) -> ValidationResult:
        """Validate input value comprehensively.

        Args:
            value: The value to validate
            max_length: Maximum allowed length for strings
            check_injections: Check for injection patterns
            check_prompt_injection: Check for prompt injection
            allowed_types: Tuple of allowed types
            schema: Optional Pydantic schema for validation

        Returns:
            ValidationResult with validation outcome
        """
        result = ValidationResult(is_valid=True)

        # Type check
        if allowed_types and not isinstance(value, allowed_types):
            result.is_valid = False
            result.errors.append(
                f"Invalid type: expected {allowed_types}, got {type(value).__name__}"
            )
            return result

        # Handle different types
        if isinstance(value, str):
            self._validate_string(value, result, max_length, check_injections, check_prompt_injection)
        elif isinstance(value, dict):
            self._validate_dict(value, result, max_length, check_injections, check_prompt_injection)
        elif isinstance(value, list):
            self._validate_list(value, result, max_length, check_injections, check_prompt_injection)

        # Schema validation
        if schema and result.is_valid:
            self._validate_schema(value, schema, result)

        return result

    def _validate_string(
        self,
        value: str,
        result: ValidationResult,
        max_length: int | None,
        check_injections: bool,
        check_prompt_injection: bool,
    ) -> None:
        """Validate string value."""
        max_len = max_length or self.config.max_input_length

        # Length check
        if len(value) > max_len:
            result.is_valid = False
            result.errors.append(f"Input too long: {len(value)} > {max_len}")
            result.threats_detected.append(ThreatType.OVERSIZED)
            return

        # Injection checks
        if check_injections and self.config.block_code_injection:
            for threat_type, patterns in self._compiled_patterns.items():
                if threat_type == ThreatType.PROMPT_INJECTION and not check_prompt_injection:
                    continue

                for pattern in patterns:
                    if pattern.search(value):
                        result.is_valid = False
                        result.threats_detected.append(threat_type)
                        result.errors.append(f"Potential {threat_type.value} detected")
                        logger.warning(
                            f"Security: {threat_type.value} pattern detected",
                            extra={"pattern": pattern.pattern[:50]},
                        )
                        break

    def _validate_dict(
        self,
        value: dict,
        result: ValidationResult,
        max_length: int | None,
        check_injections: bool,
        check_prompt_injection: bool,
    ) -> None:
        """Recursively validate dictionary values."""
        for key, val in value.items():
            # Validate key
            if isinstance(key, str):
                self._validate_string(key, result, max_length, check_injections, check_prompt_injection)
            # Validate value
            if isinstance(val, str):
                self._validate_string(val, result, max_length, check_injections, check_prompt_injection)
            elif isinstance(val, dict):
                self._validate_dict(val, result, max_length, check_injections, check_prompt_injection)
            elif isinstance(val, list):
                self._validate_list(val, result, max_length, check_injections, check_prompt_injection)

    def _validate_list(
        self,
        value: list,
        result: ValidationResult,
        max_length: int | None,
        check_injections: bool,
        check_prompt_injection: bool,
    ) -> None:
        """Recursively validate list items."""
        for item in value:
            if isinstance(item, str):
                self._validate_string(item, result, max_length, check_injections, check_prompt_injection)
            elif isinstance(item, dict):
                self._validate_dict(item, result, max_length, check_injections, check_prompt_injection)
            elif isinstance(item, list):
                self._validate_list(item, result, max_length, check_injections, check_prompt_injection)

    def _validate_schema(
        self,
        value: Any,
        schema: Any,
        result: ValidationResult,
    ) -> None:
        """Validate against Pydantic schema."""
        try:
            schema.model_validate(value)
        except Exception as e:
            result.is_valid = False
            result.errors.append(f"Schema validation failed: {e}")


# Convenience function
def validate_input(
    value: Any,
    **kwargs,
) -> ValidationResult:
    """Validate input with default settings.

    Quick validation function for common use cases.
    """
    validator = InputValidator()
    return validator.validate(value, **kwargs)


def validate_node_output(
    output: dict[str, Any],
    expected_keys: list[str],
) -> ValidationResult:
    """Validate node output for security concerns."""
    validator = InputValidator()
    result = validator.validate(output, check_prompt_injection=False)

    # Check for unexpected keys (potential injection)
    if output:
        unexpected = set(output.keys()) - set(expected_keys)
        if unexpected:
            result.warnings.append(f"Unexpected output keys: {unexpected}")

    return result


__all__ = [
    "InputValidator",
    "ValidationResult",
    "ThreatType",
    "validate_input",
    "validate_node_output",
]
