"""
Output Cleaner - Framework-level I/O validation and cleaning.

Validates node outputs match expected schemas and uses fast LLM
to clean malformed outputs before they flow to the next node.

This prevents cascading failures and dramatically improves execution success rates.

Features:
- Heuristic repair (fast, no LLM call)
- LLM-based repair (fallback for complex cases)
- Pattern caching: Remembers successful cleanings to skip redundant LLM calls
- Failure tracking: Avoids repeatedly attempting cleanings that consistently fail
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


def _generate_cache_key(
    source_node_id: str,
    target_node_id: str,
    validation_errors: list[str],
    output_structure: dict[str, Any],
) -> str:
    """
    Generate a deterministic cache key for a cleaning pattern.

    The key is based on:
    - Source and target node IDs (the edge)
    - The specific validation errors encountered
    - The structure of the output (keys and value types, not actual values)

    This allows us to cache cleaning transformations and reuse them
    when the same pattern of errors occurs on the same edge.
    """
    # Extract output structure (keys and types only, not values)
    structure = {k: type(v).__name__ for k, v in output_structure.items()}

    # Sort errors for deterministic hashing
    sorted_errors = sorted(validation_errors)

    # Build the key components
    key_data = {
        "edge": f"{source_node_id}->{target_node_id}",
        "errors": sorted_errors,
        "structure": structure,
    }

    # Create a hash for compact storage
    key_str = json.dumps(key_data, sort_keys=True)
    return hashlib.sha256(key_str.encode()).hexdigest()[:16]


def _heuristic_repair(text: str) -> dict | None:
    """
    Attempt to repair JSON without an LLM call.

    Handles common errors:
    - Markdown code blocks
    - Python booleans/None (True -> true)
    - Single quotes instead of double quotes
    """
    if not isinstance(text, str):
        return None

    # 1. Strip Markdown code blocks
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    text = text.strip()

    # 2. Find outermost JSON-like structure (greedy match)
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if match:
        candidate = match.group(1)

        # 3. Common fixes
        # Fix Python constants
        candidate = re.sub(r"\bTrue\b", "true", candidate)
        candidate = re.sub(r"\bFalse\b", "false", candidate)
        candidate = re.sub(r"\bNone\b", "null", candidate)

        # 4. Attempt load
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # 5. Advanced: Try swapping single quotes if double quotes fail
            # This is risky but effective for simple dicts
            try:
                if "'" in candidate and '"' not in candidate:
                    candidate_swapped = candidate.replace("'", '"')
                    return json.loads(candidate_swapped)
            except json.JSONDecodeError:
                pass

    return None


@dataclass
class CleansingConfig:
    """Configuration for output cleansing."""

    enabled: bool = True
    fast_model: str = "cerebras/llama-3.3-70b"  # Fast, cheap model for cleaning
    max_retries: int = 2
    cache_successful_patterns: bool = True
    fallback_to_raw: bool = True  # If cleaning fails, pass raw output
    log_cleanings: bool = True  # Log when cleansing happens

    # Cache configuration
    max_cache_size: int = 1000  # Maximum number of cached patterns
    max_failure_count: int = 3  # Skip cleaning after this many failures for same pattern
    cache_ttl_seconds: int = 3600  # Cache entries expire after 1 hour (0 = no expiry)


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

    Uses heuristics and fast LLM to clean malformed outputs
    before they flow to the next node.
    """

    def __init__(self, config: CleansingConfig, llm_provider=None):
        """
        Initialize the output cleaner.

        Args:
            config: Cleansing configuration
            llm_provider: Optional LLM provider.
        """
        import time

        self.config = config
        # Cache structure: {cache_key: {"transformation": {...}, "timestamp": float}}
        self.success_cache: dict[str, dict[str, Any]] = {}
        # Failure tracking: {cache_key: {"count": int, "last_error": str, "timestamp": float}}
        self.failure_count: dict[str, dict[str, Any]] = {}
        self.cleansing_count = 0  # Track total cleanings performed
        self.cache_hits = 0  # Track cache hits
        self.cache_misses = 0  # Track cache misses
        self.skipped_due_to_failures = 0  # Track skipped cleanings
        self._init_time = time.time()

        # Initialize LLM provider for cleaning
        if llm_provider:
            self.llm = llm_provider
        elif config.enabled:
            # Create dedicated fast LLM provider for cleaning
            try:
                import os

                from framework.llm.litellm import LiteLLMProvider

                api_key = os.environ.get("CEREBRAS_API_KEY")
                if api_key:
                    self.llm = LiteLLMProvider(
                        api_key=api_key,
                        model=config.fast_model,
                        temperature=0.0,  # Deterministic cleaning
                    )
                    logger.info(
                        f"✓ Initialized OutputCleaner with {config.fast_model}"
                    )
                else:
                    logger.warning(
                        "⚠ CEREBRAS_API_KEY not found, output cleaning will be disabled"
                    )
                    self.llm = None
            except ImportError:
                logger.warning("⚠ LiteLLMProvider not available, output cleaning disabled")
                self.llm = None
        else:
            self.llm = None

    def validate_output(
        self,
        output: dict[str, Any],
        source_node_id: str,
        target_node_spec: Any,  # NodeSpec
    ) -> ValidationResult:
        """
        Validate output matches target node's expected input schema.

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
        Use heuristics and fast LLM to clean malformed output.

        Now with caching: remembers successful cleanings and skips LLM calls
        when the same error pattern is encountered again.

        Args:
            output: Raw output from source node
            source_node_id: ID of source node
            target_node_spec: Target node spec (for schema)
            validation_errors: Errors from validation

        Returns:
            Cleaned output matching target schema
        """
        import time

        if not self.config.enabled:
            logger.warning("⚠ Output cleansing disabled in config")
            return output

        # Generate cache key for this cleaning pattern
        cache_key = _generate_cache_key(
            source_node_id,
            target_node_spec.id,
            validation_errors,
            output,
        )

        # --- PHASE 0: Check Cache ---
        if self.config.cache_successful_patterns:
            # Check if we've successfully cleaned this pattern before
            cached = self._get_cached_transformation(cache_key)
            if cached is not None:
                self.cache_hits += 1
                if self.config.log_cleanings:
                    logger.info(
                        f"⚡ Cache hit for {source_node_id} → {target_node_spec.id} "
                        f"(key: {cache_key[:8]}..., total hits: {self.cache_hits})"
                    )
                # Apply the cached transformation
                return self._apply_cached_transformation(output, cached)

            self.cache_misses += 1

            # Check if this pattern has failed too many times
            if self._should_skip_cleaning(cache_key):
                self.skipped_due_to_failures += 1
                if self.config.log_cleanings:
                    failure_info = self.failure_count.get(cache_key, {})
                    logger.warning(
                        f"⏭ Skipping cleaning for {source_node_id} → {target_node_spec.id}: "
                        f"pattern failed {failure_info.get('count', 0)} times "
                        f"(last error: {failure_info.get('last_error', 'unknown')[:50]}...)"
                    )
                if self.config.fallback_to_raw:
                    return output
                else:
                    raise RuntimeError(
                        f"Cleaning pattern {cache_key[:8]} has failed too many times"
                    )

        # --- PHASE 1: Fast Heuristic Repair (Avoids LLM call) ---
        # Often the output is just a string containing JSON, or has minor syntax errors
        # If output is a dictionary but malformed, we might need to serialize it first
        # to try and fix the underlying string representation if it came from raw text

        # Heuristic: Check if any value is actually a JSON string that should be promoted
        # This handles the "JSON Parsing Trap" where LLM returns {"key": "{\"nested\": ...}"}
        heuristic_fixed = False
        fixed_output = output.copy()

        for key, value in output.items():
            if isinstance(value, str):
                repaired = _heuristic_repair(value)
                if repaired and isinstance(repaired, (dict, list)):
                    # Check if this repaired structure looks like what we want
                    # e.g. if the key is 'data' and the string contained valid JSON
                    fixed_output[key] = repaired
                    heuristic_fixed = True

        # If we fixed something, re-validate manually to see if it's enough
        if heuristic_fixed:
            logger.info("⚡ Heuristic repair applied (nested JSON expansion)")
            # Cache this heuristic fix too (it's a valid transformation)
            if self.config.cache_successful_patterns:
                self._cache_transformation(cache_key, output, fixed_output, "heuristic")
            return fixed_output

        # --- PHASE 2: LLM-based Repair ---
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

            # Apply heuristic repair to the LLM's output too (just in case)
            cleaned = _heuristic_repair(cleaned_text)

            if not cleaned:
                # Fallback to standard load if heuristic returns None (unlikely for LLM output)
                cleaned = json.loads(cleaned_text)

            if isinstance(cleaned, dict):
                self.cleansing_count += 1
                if self.config.log_cleanings:
                    logger.info(
                        f"✓ Output cleaned successfully (total cleanings: {self.cleansing_count})"
                    )

                # Cache this successful transformation
                if self.config.cache_successful_patterns:
                    self._cache_transformation(cache_key, output, cleaned, "llm")
                    if self.config.log_cleanings:
                        logger.debug(
                            f"📦 Cached transformation for key {cache_key[:8]}... "
                            f"(cache size: {len(self.success_cache)})"
                        )

                return cleaned
            else:
                logger.warning(
                    f"⚠ Cleaned output is not a dict: {type(cleaned)}"
                )
                # Track this as a failure
                self._record_failure(cache_key, f"Cleaned output is not a dict: {type(cleaned)}")
                if self.config.fallback_to_raw:
                    return output
                else:
                    raise ValueError(
                        f"Cleaning produced {type(cleaned)}, expected dict"
                    )

        except json.JSONDecodeError as e:
            logger.error(f"✗ Failed to parse cleaned JSON: {e}")
            # Track this failure
            self._record_failure(cache_key, f"JSON parse error: {e}")
            if self.config.fallback_to_raw:
                logger.info("↩ Falling back to raw output")
                return output
            else:
                raise

        except Exception as e:
            logger.error(f"✗ Output cleaning failed: {e}")
            # Track this failure
            self._record_failure(cache_key, str(e))
            if self.config.fallback_to_raw:
                logger.info("↩ Falling back to raw output")
                return output
            else:
                raise

    def _get_cached_transformation(self, cache_key: str) -> dict[str, Any] | None:
        """
        Retrieve a cached transformation if it exists and is not expired.

        Args:
            cache_key: The cache key to look up

        Returns:
            The cached transformation data, or None if not found/expired
        """
        import time

        if cache_key not in self.success_cache:
            return None

        cached = self.success_cache[cache_key]

        # Check TTL if configured
        if self.config.cache_ttl_seconds > 0:
            age = time.time() - cached.get("timestamp", 0)
            if age > self.config.cache_ttl_seconds:
                # Expired, remove from cache
                del self.success_cache[cache_key]
                logger.debug(f"🗑 Cache entry {cache_key[:8]}... expired (age: {age:.0f}s)")
                return None

        return cached.get("transformation")

    def _apply_cached_transformation(
        self,
        output: dict[str, Any],
        transformation: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Apply a cached transformation to the output.

        The transformation stores the mapping of how keys were transformed.
        For simple cases, we just return the cached cleaned output directly.
        For more complex cases, we apply the learned transformation rules.

        Args:
            output: The raw output to transform
            transformation: The cached transformation data

        Returns:
            The transformed output
        """
        # For now, we use a simple approach: if the transformation type is "direct",
        # we have stored key mappings that we can apply.
        # For "llm" transformations, we store the output structure template.

        transform_type = transformation.get("type", "direct")

        if transform_type == "direct":
            # Direct key mapping stored
            result = {}
            key_map = transformation.get("key_map", {})
            for target_key, source_info in key_map.items():
                if source_info["source_key"] in output:
                    value = output[source_info["source_key"]]
                    # Apply any necessary transformations
                    if source_info.get("parse_json") and isinstance(value, str):
                        try:
                            value = json.loads(value)
                        except json.JSONDecodeError:
                            pass
                    result[target_key] = value
            return result

        elif transform_type in ("heuristic", "llm"):
            # For heuristic/LLM transformations, we stored a template
            # Try to apply the same fix pattern
            template = transformation.get("template", {})
            fixed_keys = transformation.get("fixed_keys", [])

            result = output.copy()
            for key in fixed_keys:
                if key in output and isinstance(output[key], str):
                    # Try the same heuristic repair that worked before
                    repaired = _heuristic_repair(output[key])
                    if repaired:
                        result[key] = repaired

            # If we have a template with expected keys, ensure they exist
            for key in template.get("expected_keys", []):
                if key not in result:
                    # Try to find the value in nested structures
                    for v in output.values():
                        if isinstance(v, dict) and key in v:
                            result[key] = v[key]
                            break

            return result

        # Fallback: return output as-is (shouldn't happen)
        return output

    def _cache_transformation(
        self,
        cache_key: str,
        original_output: dict[str, Any],
        cleaned_output: dict[str, Any],
        transform_type: str,
    ) -> None:
        """
        Cache a successful transformation for future reuse.

        Args:
            cache_key: The cache key
            original_output: The original malformed output
            cleaned_output: The successfully cleaned output
            transform_type: "heuristic" or "llm"
        """
        import time

        # Enforce max cache size (LRU-style: remove oldest entries)
        if len(self.success_cache) >= self.config.max_cache_size:
            # Remove the oldest 10% of entries
            entries = sorted(
                self.success_cache.items(),
                key=lambda x: x[1].get("timestamp", 0),
            )
            num_to_remove = max(1, len(entries) // 10)
            for key, _ in entries[:num_to_remove]:
                del self.success_cache[key]
            logger.debug(f"🗑 Evicted {num_to_remove} old cache entries")

        # Determine which keys were fixed
        fixed_keys = []
        for key in original_output:
            if key in cleaned_output:
                orig_val = original_output[key]
                clean_val = cleaned_output[key]
                # If the value changed type or structure, it was "fixed"
                if type(orig_val) != type(clean_val):
                    fixed_keys.append(key)
                elif isinstance(orig_val, str) and isinstance(clean_val, dict):
                    fixed_keys.append(key)

        transformation = {
            "type": transform_type,
            "fixed_keys": fixed_keys,
            "template": {
                "expected_keys": list(cleaned_output.keys()),
            },
        }

        self.success_cache[cache_key] = {
            "transformation": transformation,
            "timestamp": time.time(),
        }

    def _should_skip_cleaning(self, cache_key: str) -> bool:
        """
        Check if we should skip cleaning based on failure history.

        Args:
            cache_key: The cache key to check

        Returns:
            True if this pattern has failed too many times
        """
        if cache_key not in self.failure_count:
            return False

        failure_info = self.failure_count[cache_key]
        return failure_info.get("count", 0) >= self.config.max_failure_count

    def _record_failure(self, cache_key: str, error_message: str) -> None:
        """
        Record a cleaning failure for tracking.

        Args:
            cache_key: The cache key
            error_message: Description of the failure
        """
        import time

        if cache_key not in self.failure_count:
            self.failure_count[cache_key] = {
                "count": 0,
                "last_error": "",
                "timestamp": 0,
            }

        self.failure_count[cache_key]["count"] += 1
        self.failure_count[cache_key]["last_error"] = error_message
        self.failure_count[cache_key]["timestamp"] = time.time()

        if self.config.log_cleanings:
            count = self.failure_count[cache_key]["count"]
            logger.debug(
                f"📊 Failure #{count} for pattern {cache_key[:8]}...: {error_message[:50]}"
            )

    def clear_cache(self) -> dict[str, int]:
        """
        Clear the transformation cache and failure tracking.

        Returns:
            Stats about what was cleared
        """
        stats = {
            "cache_entries_cleared": len(self.success_cache),
            "failure_entries_cleared": len(self.failure_count),
        }
        self.success_cache.clear()
        self.failure_count.clear()
        logger.info(f"🧹 Cache cleared: {stats}")
        return stats

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
        """
        Get comprehensive cleansing and caching statistics.

        Returns:
            Dict with cleaning stats, cache performance, and failure tracking
        """
        import time

        total_requests = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total_requests * 100) if total_requests > 0 else 0

        # Calculate estimated LLM calls saved
        # Each cache hit saves one LLM call (assuming heuristic doesn't fix it)
        llm_calls_saved = self.cache_hits

        # Calculate uptime
        uptime_seconds = time.time() - self._init_time

        return {
            # Cleaning stats
            "total_cleanings": self.cleansing_count,
            "skipped_due_to_failures": self.skipped_due_to_failures,

            # Cache performance
            "cache_size": len(self.success_cache),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate_percent": round(hit_rate, 1),
            "llm_calls_saved": llm_calls_saved,

            # Failure tracking
            "tracked_failure_patterns": len(self.failure_count),
            "failure_details": {
                k: {"count": v["count"], "last_error": v["last_error"][:100]}
                for k, v in self.failure_count.items()
            },

            # Runtime info
            "uptime_seconds": round(uptime_seconds, 1),
            "config": {
                "max_cache_size": self.config.max_cache_size,
                "max_failure_count": self.config.max_failure_count,
                "cache_ttl_seconds": self.config.cache_ttl_seconds,
            },
        }
