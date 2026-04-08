"""Tests for ErrorCategorizer.categorize_text (added for issue #3900).

The original ``categorize`` API takes a TestResult, but the FailureReport
flow needs to classify a raw summary string. ``categorize_text`` exposes
the same patterns without requiring a TestResult.
"""

from __future__ import annotations

from framework.testing.categorizer import ErrorCategorizer
from framework.testing.test_result import ErrorCategory


def test_categorize_text_logic_error() -> None:
    cat = ErrorCategorizer()
    assert cat.categorize_text("criteria not met for goal") == ErrorCategory.LOGIC_ERROR


def test_categorize_text_implementation_error() -> None:
    cat = ErrorCategorizer()
    assert (
        cat.categorize_text("AssertionError: expected 1 but got 2")
        == ErrorCategory.IMPLEMENTATION_ERROR
    )


def test_categorize_text_edge_case() -> None:
    cat = ErrorCategorizer()
    assert cat.categorize_text("connection timeout after 30s") == ErrorCategory.EDGE_CASE


def test_categorize_text_empty_defaults_to_implementation() -> None:
    cat = ErrorCategorizer()
    assert cat.categorize_text("") == ErrorCategory.IMPLEMENTATION_ERROR
