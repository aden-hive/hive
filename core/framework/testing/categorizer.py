"""
Error categorization for test failures.

Categorizes errors to guide iteration strategy:
- LOGIC_ERROR: Goal definition is wrong → update success_criteria/constraints
- IMPLEMENTATION_ERROR: Code bug → fix nodes/edges in Agent stage
- EDGE_CASE: New scenario discovered → add new test only
- TIMEOUT_ERROR: Agent exceeded time budget → optimize node logic or increase timeout
- AUTH_ERROR: Missing or invalid API credentials → run `hive credentials set`
- RATE_LIMIT_ERROR: LLM/tool API quota hit → add retry logic or reduce test parallelism
- TOOL_ERROR: External tool call failed → check tool config, network, or API key
- IMPORT_ERROR: Missing Python package → add to pyproject.toml / run `uv add <pkg>`
"""

import re
from typing import Any

from framework.testing.test_result import ErrorCategory, TestResult


class ErrorCategorizer:
    """
    Categorize test failures for guiding iteration.

    Uses pattern matching heuristics to classify errors.
    Each category has different implications for how to fix.
    """

    # Patterns indicating goal/criteria definition is wrong
    LOGIC_ERROR_PATTERNS = [
        r"goal not achieved",
        r"constraint violated:?\s*core",
        r"fundamental assumption",
        r"success criteria mismatch",
        r"criteria not met",
        r"expected behavior incorrect",
        r"specification error",
        r"requirement mismatch",
    ]

    # Patterns indicating code/implementation bug
    IMPLEMENTATION_ERROR_PATTERNS = [
        r"TypeError",
        r"AttributeError",
        r"KeyError",
        r"IndexError",
        r"ValueError",
        r"NameError",
        r"RuntimeError",
        r"NullPointerException",
        r"NoneType.*has no attribute",
        r"tool call failed",
        r"node execution error",
        r"agent execution failed",
        r"assertion.*failed",
        r"AssertionError",
        r"expected.*but got",
        r"unexpected.*type",
        r"missing required",
        r"invalid.*argument",
    ]

    # Patterns indicating edge case / new scenario
    EDGE_CASE_PATTERNS = [
        r"boundary condition",
        r"unexpected format",
        r"unexpected response",
        r"rare input",
        r"empty.*result",
        r"null.*value",
        r"empty.*response",
        r"no.*results",
        r"unicode.*error",
        r"encoding.*error",
        r"special.*character",
    ]

    # Patterns indicating a timeout (agent took too long)
    TIMEOUT_ERROR_PATTERNS = [
        r"timeout",
        r"timed out",
        r"deadline.*exceeded",
        r"max.*execution.*time",
        r"asyncio.*TimeoutError",
        r"concurrent\.futures\.TimeoutError",
        r"ReadTimeout",
        r"ConnectTimeout",
        r"request.*timeout",
        r"connection.*timeout",
    ]

    # Patterns indicating missing or invalid credentials
    AUTH_ERROR_PATTERNS = [
        r"401",
        r"403",
        r"Unauthorized",
        r"Forbidden",
        r"authentication.*failed",
        r"invalid.*api.*key",
        r"api.*key.*invalid",
        r"permission.*denied",
        r"access.*denied",
        r"credentials.*missing",
        r"missing.*credentials",
        r"OPENAI_API_KEY",
        r"ANTHROPIC_API_KEY",
        r"BRAVE_SEARCH_API_KEY",
        r"token.*expired",
        r"invalid.*token",
    ]

    # Patterns indicating rate limiting / quota
    RATE_LIMIT_ERROR_PATTERNS = [
        r"rate.*limit",
        r"quota.*exceeded",
        r"429",
        r"too many requests",
        r"retry.*exhausted",
        r"backoff",
        r"throttl",
        r"RateLimitError",
    ]

    # Patterns indicating an external tool call failed
    TOOL_ERROR_PATTERNS = [
        r"tool.*error",
        r"tool.*failed",
        r"mcp.*error",
        r"integration.*error",
        r"external.*service.*error",
        r"API.*error",
        r"requests\.exceptions",
        r"ConnectionError",
        r"HTTPError",
        r"SSLError",
        r"socket\.error",
    ]

    # Patterns indicating a missing Python package
    IMPORT_ERROR_PATTERNS = [
        r"ImportError",
        r"ModuleNotFoundError",
        r"No module named",
        r"cannot import name",
    ]

    def __init__(self):
        """Initialize categorizer with compiled patterns."""
        self._logic_patterns = [re.compile(p, re.IGNORECASE) for p in self.LOGIC_ERROR_PATTERNS]
        self._impl_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.IMPLEMENTATION_ERROR_PATTERNS
        ]
        self._edge_patterns = [re.compile(p, re.IGNORECASE) for p in self.EDGE_CASE_PATTERNS]
        self._timeout_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.TIMEOUT_ERROR_PATTERNS
        ]
        self._auth_patterns = [re.compile(p, re.IGNORECASE) for p in self.AUTH_ERROR_PATTERNS]
        self._rate_limit_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.RATE_LIMIT_ERROR_PATTERNS
        ]
        self._tool_patterns = [re.compile(p, re.IGNORECASE) for p in self.TOOL_ERROR_PATTERNS]
        self._import_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.IMPORT_ERROR_PATTERNS
        ]

    def categorize(self, result: TestResult) -> ErrorCategory | None:
        """
        Categorize a test failure.

        Args:
            result: TestResult to categorize

        Returns:
            ErrorCategory if test failed, None if passed
        """
        if result.passed:
            return None

        # Combine error sources for analysis
        error_text = self._get_error_text(result)

        # Check patterns in priority order — most actionable infra errors first
        # so developers get specific guidance instead of generic "review manually"

        # Import errors must come before implementation errors (ImportError was
        # previously lumped in — moved here for specificity)
        for pattern in self._import_patterns:
            if pattern.search(error_text):
                return ErrorCategory.IMPORT_ERROR

        # Auth errors: always actionable — run `hive credentials set`
        for pattern in self._auth_patterns:
            if pattern.search(error_text):
                return ErrorCategory.AUTH_ERROR

        # Rate limit errors: transient, different fix from auth
        for pattern in self._rate_limit_patterns:
            if pattern.search(error_text):
                return ErrorCategory.RATE_LIMIT_ERROR

        # Timeout errors: agent too slow, not a code bug per se
        for pattern in self._timeout_patterns:
            if pattern.search(error_text):
                return ErrorCategory.TIMEOUT_ERROR

        # External tool errors: network / API issues
        for pattern in self._tool_patterns:
            if pattern.search(error_text):
                return ErrorCategory.TOOL_ERROR

        # Logic errors (wrong goal definition)
        for pattern in self._logic_patterns:
            if pattern.search(error_text):
                return ErrorCategory.LOGIC_ERROR

        # Implementation errors (code bugs)
        for pattern in self._impl_patterns:
            if pattern.search(error_text):
                return ErrorCategory.IMPLEMENTATION_ERROR

        # Edge cases (new scenarios)
        for pattern in self._edge_patterns:
            if pattern.search(error_text):
                return ErrorCategory.EDGE_CASE

        # Default to implementation error (most common)
        return ErrorCategory.IMPLEMENTATION_ERROR

    def categorize_with_confidence(self, result: TestResult) -> tuple[ErrorCategory | None, float]:
        """
        Categorize with a confidence score.

        Args:
            result: TestResult to categorize

        Returns:
            Tuple of (category, confidence 0-1)
        """
        if result.passed:
            return None, 1.0

        error_text = self._get_error_text(result)

        # Count pattern matches for each category
        logic_matches = sum(1 for p in self._logic_patterns if p.search(error_text))
        impl_matches = sum(1 for p in self._impl_patterns if p.search(error_text))
        edge_matches = sum(1 for p in self._edge_patterns if p.search(error_text))

        total_matches = logic_matches + impl_matches + edge_matches

        if total_matches == 0:
            # No pattern matches, default to implementation with low confidence
            return ErrorCategory.IMPLEMENTATION_ERROR, 0.3

        # Calculate confidence based on match dominance
        if logic_matches >= impl_matches and logic_matches >= edge_matches:
            confidence = logic_matches / total_matches if total_matches > 0 else 0.5
            return ErrorCategory.LOGIC_ERROR, min(0.9, 0.5 + confidence * 0.4)

        if impl_matches >= logic_matches and impl_matches >= edge_matches:
            confidence = impl_matches / total_matches if total_matches > 0 else 0.5
            return ErrorCategory.IMPLEMENTATION_ERROR, min(0.9, 0.5 + confidence * 0.4)

        confidence = edge_matches / total_matches if total_matches > 0 else 0.5
        return ErrorCategory.EDGE_CASE, min(0.9, 0.5 + confidence * 0.4)

    def _get_error_text(self, result: TestResult) -> str:
        """Extract all error text from a result for analysis."""
        parts = []

        if result.error_message:
            parts.append(result.error_message)

        if result.stack_trace:
            parts.append(result.stack_trace)

        # Include log messages
        for log in result.runtime_logs:
            if log.get("level") in ("ERROR", "CRITICAL", "WARNING"):
                parts.append(str(log.get("msg", "")))

        return " ".join(parts)

    def get_fix_suggestion(self, category: ErrorCategory) -> str:
        """
        Get a fix suggestion based on error category.

        Args:
            category: ErrorCategory from categorization

        Returns:
            Human-readable fix suggestion
        """
        suggestions = {
            ErrorCategory.LOGIC_ERROR: (
                "Review and update success_criteria or constraints in the Goal definition. "
                "The goal specification may not accurately describe the desired behavior."
            ),
            ErrorCategory.IMPLEMENTATION_ERROR: (
                "Fix the code in agent nodes/edges. "
                "There's a bug in the implementation that needs to be corrected."
            ),
            ErrorCategory.EDGE_CASE: (
                "Add a new test for this edge case scenario. "
                "This is a valid scenario that wasn't covered by existing tests."
            ),
            ErrorCategory.TIMEOUT_ERROR: (
                "The agent exceeded its time budget. Options: (1) optimize slow node logic, "
                "(2) increase the execution timeout in your entry point config, "
                "(3) add caching to avoid redundant LLM calls."
            ),
            ErrorCategory.AUTH_ERROR: (
                "A credential is missing or invalid. Run `hive credentials list` to see what's "
                "configured, then `hive credentials set <KEY>` to add or update it. "
                "Check that the key is active and has the required permissions."
            ),
            ErrorCategory.RATE_LIMIT_ERROR: (
                "An API rate limit or quota was hit. Options: (1) reduce test parallelism "
                "(`hive test-run --concurrency 1`), (2) add exponential backoff retry logic "
                "to your node, (3) upgrade your API plan or use a different key."
            ),
            ErrorCategory.TOOL_ERROR: (
                "An external tool call failed (network, API, or config issue). "
                "Check: (1) your internet connection, (2) the tool's API key/config, "
                "(3) whether the external service is down, (4) any firewall/proxy settings."
            ),
            ErrorCategory.IMPORT_ERROR: (
                "A required Python package is missing. Run `uv add <package-name>` from "
                "your agent directory to install it, then re-run the test."
            ),
        }
        return suggestions.get(category, "Review the test and agent implementation.")

    def get_iteration_guidance(self, category: ErrorCategory) -> dict[str, Any]:
        """
        Get detailed iteration guidance based on error category.

        Returns a dict with:
        - stage: Which stage to return to (Goal, Agent, Eval, Config)
        - action: What action to take
        - restart_required: Whether full 3-step flow restart is needed
        """
        guidance = {
            ErrorCategory.LOGIC_ERROR: {
                "stage": "Goal",
                "action": "Update success_criteria or constraints",
                "restart_required": True,
                "description": (
                    "The goal definition is incorrect. Update the success criteria "
                    "or constraints, then restart the full Goal → Agent → Eval flow."
                ),
            },
            ErrorCategory.IMPLEMENTATION_ERROR: {
                "stage": "Agent",
                "action": "Fix nodes/edges implementation",
                "restart_required": False,
                "description": (
                    "There's a code bug. Fix the agent implementation, "
                    "then re-run Eval (skip Goal stage)."
                ),
            },
            ErrorCategory.EDGE_CASE: {
                "stage": "Eval",
                "action": "Add new test only",
                "restart_required": False,
                "description": (
                    "This is a new scenario. Add a test for it and continue in the Eval stage."
                ),
            },
            ErrorCategory.TIMEOUT_ERROR: {
                "stage": "Agent",
                "action": "Optimize node performance or increase timeout",
                "restart_required": False,
                "description": (
                    "The agent ran too slowly. Profile slow nodes, add caching, or increase "
                    "the execution_timeout in your entry point spec."
                ),
            },
            ErrorCategory.AUTH_ERROR: {
                "stage": "Config",
                "action": "Run `hive credentials set <KEY>`",
                "restart_required": False,
                "description": (
                    "A credential is missing or expired. Fix credentials first, "
                    "then re-run tests — no code changes needed."
                ),
            },
            ErrorCategory.RATE_LIMIT_ERROR: {
                "stage": "Config",
                "action": "Reduce concurrency or add retry logic",
                "restart_required": False,
                "description": (
                    "Rate limit hit. Run `hive test-run --concurrency 1` to serialize tests, "
                    "or add exponential backoff to the failing node."
                ),
            },
            ErrorCategory.TOOL_ERROR: {
                "stage": "Config",
                "action": "Check tool credentials and external service status",
                "restart_required": False,
                "description": (
                    "An external tool call failed. Verify the tool's API key, network access, "
                    "and whether the external service is operational."
                ),
            },
            ErrorCategory.IMPORT_ERROR: {
                "stage": "Agent",
                "action": "Run `uv add <missing-package>`",
                "restart_required": False,
                "description": (
                    "A Python package is missing from the environment. "
                    "Add it with `uv add <package>` and re-run tests."
                ),
            },
        }
        return guidance.get(
            category,
            {
                "stage": "Unknown",
                "action": "Review manually",
                "restart_required": False,
                "description": "Unable to determine category. Manual review required.",
            },
        )
