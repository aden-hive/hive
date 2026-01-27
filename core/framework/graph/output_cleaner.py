"""
Output Cleaner - Framework-level I/O validation and cleaning.

Validates node outputs match expected schemas and uses fast LLM
to clean malformed outputs before they flow to the next node.

This prevents cascading failures and dramatically improves execution success rates.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CleansingConfig:
    """Configuration for output cleansing."""

    enabled: bool = True
    # Model to use - if not specified, auto-detect from available providers
    fast_model: str | None = None
    # Explicit API key override (optional - will auto-detect from env if not set)
    api_key: str | None = None
    max_retries: int = 2
    cache_successful_patterns: bool = True
    fallback_to_raw: bool = True  # If cleaning fails, pass raw output
    log_cleanings: bool = True  # Log when cleansing happens


# Provider detection order (fast, cheap models preferred for cleaning tasks)
# Each tuple: (env_var, model, display_name)
PROVIDER_CONFIG = [
    ("CEREBRAS_API_KEY", "cerebras/llama-3.3-70b", "Cerebras"),
    ("GROQ_API_KEY", "groq/llama-3.3-70b-versatile", "Groq"),
    ("OPENAI_API_KEY", "gpt-4o-mini", "OpenAI"),
    ("ANTHROPIC_API_KEY", "claude-3-haiku-20240307", "Anthropic"),
    ("GEMINI_API_KEY", "gemini/gemini-1.5-flash", "Google Gemini"),
    ("TOGETHER_API_KEY", "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo", "Together AI"),
]


def _detect_provider() -> tuple[str | None, str | None, str | None]:
    """
    Auto-detect available LLM provider from environment variables.

    Checks for API keys in priority order, preferring fast/cheap providers
    suitable for output cleaning tasks.

    Returns:
        Tuple of (api_key, model, provider_name) or (None, None, None) if no provider found
    """
    import os

    for env_var, model, name in PROVIDER_CONFIG:
        api_key = os.environ.get(env_var)
        if api_key:
            return api_key, model, name
    return None, None, None


@dataclass
class ValidationResult:
    """Result of output validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cleaned_output: dict[str, Any] | None = None


class OutputCleaner:
    """
    Framework-level output validation and cleaning.

    Uses fast LLM (llama-3.3-70b) to clean malformed outputs
    before they flow to the next node.

    Example:
        cleaner = OutputCleaner(
            config=CleansingConfig(enabled=True),
            llm_provider=llm,
        )

        # Validate output
        validation = cleaner.validate_output(
            output=node_output,
            source_node_id="analyze",
            target_node_spec=next_node_spec,
        )

        if not validation.valid:
            # Clean the output
            cleaned = cleaner.clean_output(
                output=node_output,
                source_node_id="analyze",
                target_node_spec=next_node_spec,
                validation_errors=validation.errors,
            )
    """

    def __init__(self, config: CleansingConfig, llm_provider=None):
        """
        Initialize the output cleaner.

        Args:
            config: Cleansing configuration
            llm_provider: Optional LLM provider. If None and cleaning is enabled,
                         will auto-detect from available providers in environment.
        """
        self.config = config
        self.success_cache: dict[str, Any] = {}  # Cache successful patterns
        self.failure_count: dict[str, int] = {}  # Track edge failures
        self.cleansing_count = 0  # Track total cleanings performed

        # Initialize LLM provider for cleaning
        if llm_provider:
            self.llm = llm_provider
        elif config.enabled:
            self._initialize_llm()
        else:
            self.llm = None

    def _initialize_llm(self):
        """Initialize LLM provider with auto-detection or explicit config."""
        try:
            from framework.llm.litellm import LiteLLMProvider

            # Case 1: Explicit API key and model configured
            if self.config.api_key and self.config.fast_model:
                self.llm = LiteLLMProvider(
                    api_key=self.config.api_key,
                    model=self.config.fast_model,
                    temperature=0.0,  # Deterministic cleaning
                )
                logger.info(
                    f"✓ Initialized OutputCleaner with {self.config.fast_model} (explicit config)"
                )
                return

            # Case 2: Auto-detect provider from environment
            api_key, model, provider_name = _detect_provider()

            # Allow model override even with auto-detected provider
            if self.config.fast_model:
                model = self.config.fast_model

            if api_key and model:
                self.llm = LiteLLMProvider(
                    api_key=api_key,
                    model=model,
                    temperature=0.0,  # Deterministic cleaning
                )
                logger.info(
                    f"✓ Initialized OutputCleaner with {model} ({provider_name})"
                )
            else:
                logger.warning(
                    "⚠ No LLM provider found for output cleaning. "
                    "Set one of: CEREBRAS_API_KEY, GROQ_API_KEY, OPENAI_API_KEY, "
                    "ANTHROPIC_API_KEY, GEMINI_API_KEY, or TOGETHER_API_KEY"
                )
                self.llm = None

        except ImportError:
            logger.warning("⚠ LiteLLMProvider not available, output cleaning disabled")
            self.llm = None

    def validate_output(
        self,
        output: dict[str, Any],
        source_node_id: str,
        target_node_spec: Any,  # NodeSpec
    ) -> ValidationResult:
        """
        Validate output matches target node's expected input schema.

        Args:
            output: Output from source node
            source_node_id: ID of source node
            target_node_spec: Spec of target node (for input_keys)

        Returns:
            ValidationResult with errors and optionally cleaned output
        """
        errors = []
        warnings = []

        # Check 1: Required input keys present
        for key in target_node_spec.input_keys:
            if key not in output:
                errors.append(f"Missing required key: '{key}'")
                continue

            value = output[key]

            # Check 2: Detect if value is JSON string (the JSON parsing trap!)
            if isinstance(value, str):
                # Try parsing as JSON to detect the trap
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, dict):
                        if key in parsed:
                            # Key exists in parsed JSON - classic parsing failure!
                            errors.append(
                                f"Key '{key}' contains JSON string with nested '{key}' field - "
                                f"likely parsing failure from LLM node"
                            )
                        elif len(value) > 100:
                            # Large JSON string, but doesn't contain the key
                            warnings.append(
                                f"Key '{key}' contains JSON string ({len(value)} chars)"
                            )
                except json.JSONDecodeError:
                    # Not JSON, check if suspiciously large
                    if len(value) > 500:
                        warnings.append(
                            f"Key '{key}' contains large string ({len(value)} chars), "
                            f"possibly entire LLM response"
                        )

            # Check 3: Type validation (if schema provided)
            if hasattr(target_node_spec, "input_schema") and target_node_spec.input_schema:
                expected_schema = target_node_spec.input_schema.get(key)
                if expected_schema:
                    expected_type = expected_schema.get("type")
                    if expected_type and not self._type_matches(value, expected_type):
                        actual_type = type(value).__name__
                        errors.append(
                            f"Key '{key}': expected type '{expected_type}', got '{actual_type}'"
                        )

        # Warnings don't make validation fail, but errors do
        is_valid = len(errors) == 0

        if not is_valid and self.config.log_cleanings:
            logger.warning(
                f"⚠ Output validation failed for {source_node_id} → {target_node_spec.id}: "
                f"{len(errors)} error(s), {len(warnings)} warning(s)"
            )

        return ValidationResult(
            valid=is_valid,
            errors=errors,
            warnings=warnings,
        )

    def clean_output(
        self,
        output: dict[str, Any],
        source_node_id: str,
        target_node_spec: Any,  # NodeSpec
        validation_errors: list[str],
    ) -> dict[str, Any]:
        """
        Use fast LLM to clean malformed output.

        Args:
            output: Raw output from source node
            source_node_id: ID of source node
            target_node_spec: Target node spec (for schema)
            validation_errors: Errors from validation

        Returns:
            Cleaned output matching target schema

        Raises:
            Exception: If cleaning fails and fallback_to_raw is False
        """
        if not self.config.enabled:
            logger.warning("⚠ Output cleansing disabled in config")
            return output

        if not self.llm:
            logger.warning("⚠ No LLM provider available for cleansing")
            return output

        # Build schema description for target node
        schema_desc = self._build_schema_description(target_node_spec)

        # Create cleansing prompt
        prompt = f"""Clean this malformed agent output to match the expected schema.

VALIDATION ERRORS:
{chr(10).join(f"- {e}" for e in validation_errors)}

EXPECTED SCHEMA for node '{target_node_spec.id}':
{schema_desc}

RAW OUTPUT from node '{source_node_id}':
{json.dumps(output, indent=2, default=str)}

INSTRUCTIONS:
1. Extract values that match the expected schema keys
2. If a value is a JSON string, parse it and extract the correct field
3. Convert types to match the schema (string, dict, list, number, boolean)
4. Remove extra fields not in the expected schema
5. Ensure all required keys are present

Return ONLY valid JSON matching the expected schema. No explanations, no markdown."""

        try:
            if self.config.log_cleanings:
                logger.info(
                    f"🧹 Cleaning output from '{source_node_id}' using {self.config.fast_model}"
                )

            response = self.llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "You clean malformed agent outputs. "
                    "Return only valid JSON matching the schema."
                ),
                max_tokens=2048,  # Sufficient for cleaning most outputs
            )

            # Parse cleaned output
            cleaned_text = response.content.strip()

            # Remove markdown if present
            if cleaned_text.startswith("```"):
                match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned_text, re.DOTALL)
                if match:
                    cleaned_text = match.group(1).strip()

            cleaned = json.loads(cleaned_text)

            if isinstance(cleaned, dict):
                self.cleansing_count += 1
                if self.config.log_cleanings:
                    logger.info(
                        f"✓ Output cleaned successfully (total cleanings: {self.cleansing_count})"
                    )
                return cleaned
            else:
                logger.warning(f"⚠ Cleaned output is not a dict: {type(cleaned)}")
                if self.config.fallback_to_raw:
                    return output
                else:
                    raise ValueError(f"Cleaning produced {type(cleaned)}, expected dict")

        except json.JSONDecodeError as e:
            logger.error(f"✗ Failed to parse cleaned JSON: {e}")
            if self.config.fallback_to_raw:
                logger.info("↩ Falling back to raw output")
                return output
            else:
                raise

        except Exception as e:
            logger.error(f"✗ Output cleaning failed: {e}")
            if self.config.fallback_to_raw:
                logger.info("↩ Falling back to raw output")
                return output
            else:
                raise

    def _build_schema_description(self, node_spec: Any) -> str:
        """Build human-readable schema description from NodeSpec."""
        lines = ["{"]

        for key in node_spec.input_keys:
            # Get type hint and description if available
            if hasattr(node_spec, "input_schema") and node_spec.input_schema:
                schema = node_spec.input_schema.get(key, {})
                type_hint = schema.get("type", "any")
                description = schema.get("description", "")
                required = schema.get("required", True)

                line = f'  "{key}": {type_hint}'
                if description:
                    line += f"  // {description}"
                if required:
                    line += " (required)"
                lines.append(line + ",")
            else:
                # No schema, just show the key
                lines.append(f'  "{key}": any  // (required)')

        lines.append("}")
        return "\n".join(lines)

    def _type_matches(self, value: Any, expected_type: str) -> bool:
        """Check if value matches expected type."""
        type_map = {
            "string": str,
            "str": str,
            "int": int,
            "integer": int,
            "float": float,
            "number": (int, float),
            "bool": bool,
            "boolean": bool,
            "dict": dict,
            "object": dict,
            "list": list,
            "array": list,
            "any": object,  # Matches everything
        }

        expected_class = type_map.get(expected_type.lower())
        if expected_class:
            return isinstance(value, expected_class)

        # Unknown type, allow it
        return True

    def get_stats(self) -> dict[str, Any]:
        """Get cleansing statistics."""
        return {
            "total_cleanings": self.cleansing_count,
            "failure_count": dict(self.failure_count),
            "cache_size": len(self.success_cache),
        }
