"""
Error categorization for test failures.

Categorizes errors to guide iteration strategy:
- LOGIC_ERROR: Goal definition is wrong → update success_criteria/constraints
- IMPLEMENTATION_ERROR: Code bug → fix nodes/edges in Agent stage
- EDGE_CASE: New scenario discovered → add new test only
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
        r"ImportError",
        r"ModuleNotFoundError",
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
        r"timeout",
        r"connection.*timeout",
        r"request.*timeout",
        r"unexpected format",
        r"unexpected response",
        r"rare input",
        r"empty.*result",
        r"null.*value",
        r"empty.*response",
        r"no.*results",
        r"rate.*limit",
        r"quota.*exceeded",
        r"retry.*exhausted",
        r"unicode.*error",
        r"encoding.*error",
        r"special.*character",
    ]

    def __init__(self):
        """Initialize categorizer with compiled patterns."""
        self._logic_patterns = [re.compile(p, re.IGNORECASE) for p in self.LOGIC_ERROR_PATTERNS]
        self._impl_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.IMPLEMENTATION_ERROR_PATTERNS
        ]
        self._edge_patterns = [re.compile(p, re.IGNORECASE) for p in self.EDGE_CASE_PATTERNS]

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

        # Check patterns in priority order
        # Logic errors take precedence (wrong goal definition)
        for pattern in self._logic_patterns:
            if pattern.search(error_text):
                return ErrorCategory.LOGIC_ERROR

        # Then implementation errors (code bugs)
        for pattern in self._impl_patterns:
            if pattern.search(error_text):
                return ErrorCategory.IMPLEMENTATION_ERROR

        # Then edge cases (new scenarios)
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
        }
        return suggestions.get(category, "Review the test and agent implementation.")

    def get_iteration_guidance(self, category: ErrorCategory) -> dict[str, Any]:
        """
        Get detailed iteration guidance based on error category.

        Returns a dict with:
        - stage: Which stage to return to (Goal, Agent, Eval)
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
