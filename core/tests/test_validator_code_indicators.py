"""
Tests for OutputValidator._contains_code_indicators false-positive reduction.

Verifies that the two-tier indicator system:
- Still detects actual code blocks (strong and weak indicators)
- Does NOT false-positive on natural language text
- Handles large strings via sampling
"""

from __future__ import annotations

import pytest

from framework.graph.validator import OutputValidator


@pytest.fixture
def validator():
    return OutputValidator()


# ---------------------------------------------------------------------------
# Strong indicators — single match should trigger
# ---------------------------------------------------------------------------


class TestStrongIndicators:
    """Strong indicators should trigger on a single occurrence."""

    @pytest.mark.parametrize(
        "code_snippet",
        [
            "if __name__ == '__main__':",
            "async def main():",
            "const handler = () => { return true; }",
            "const x = require('fs')",
            "<script>alert('xss')</script>",
            "<?php echo 'hello'; ?>",
            "<% Response.Write('hello') %>",
            "try:\n    pass",
            "except:\n    pass",
        ],
    )
    def test_detects_strong_indicators(self, validator, code_snippet):
        """Each strong indicator alone should be detected."""
        assert validator._contains_code_indicators(code_snippet) is True


# ---------------------------------------------------------------------------
# Weak indicators — need ≥2 co-occurring, line-anchored
# ---------------------------------------------------------------------------


class TestWeakIndicators:
    """Weak indicators should only trigger when line-anchored and co-occurring."""

    def test_single_weak_indicator_not_flagged(self, validator):
        """A single weak indicator should NOT trigger a false positive."""
        text = "Here is a summary.\nimport os\nThis is natural language."
        assert validator._contains_code_indicators(text) is False

    def test_two_weak_indicators_flagged(self, validator):
        """Two co-occurring weak indicators should trigger."""
        text = "Here is some code:\nimport os\nfrom pathlib import Path\n"
        assert validator._contains_code_indicators(text) is True

    def test_multiple_python_indicators(self, validator):
        """Multiple Python code lines should be detected."""
        code = "\nimport os\nfrom pathlib import Path\ndef main():\n    pass\n"
        assert validator._contains_code_indicators(code) is True

    def test_multiple_js_indicators(self, validator):
        """Multiple JavaScript code lines should be detected."""
        code = "\nconst x = 1;\nlet y = 2;\nexport default x;\n"
        assert validator._contains_code_indicators(code) is True

    def test_multiple_sql_indicators(self, validator):
        """Multiple SQL statements should be detected."""
        code = "\nSELECT * FROM users\nDELETE FROM sessions\n"
        assert validator._contains_code_indicators(code) is True


# ---------------------------------------------------------------------------
# Natural language — should NOT trigger
# ---------------------------------------------------------------------------


class TestNaturalLanguageFalsePositives:
    """Common English text should not be flagged as code."""

    @pytest.mark.parametrize(
        "text",
        [
            "We need to import all data from the database",
            "Let me update the class schedule for next week",
            "Please select the best option and delete the rest",
            "The function of this tool is to export reports",
            "From the analysis, we can see that const effort is needed",
            "I await your response regarding the update plan",
            "Let the team know about the new class of issues",
            "We need to import goods from overseas and export them locally",
            "The drop in revenue requires us to update our strategy",
        ],
    )
    def test_natural_language_not_flagged(self, validator, text):
        """Everyday English sentences should not be flagged as code."""
        assert validator._contains_code_indicators(text) is False

    def test_business_report_not_flagged(self, validator):
        """A multi-line business report should not be flagged."""
        report = (
            "Q1 Financial Report\n\n"
            "We need to import the latest figures from accounting.\n"
            "Let the board know about the updated projections.\n"
            "The class of investments we selected performed well.\n"
            "From Q4, our revenue grew by 15%.\n"
        )
        assert validator._contains_code_indicators(report) is False


# ---------------------------------------------------------------------------
# Actual code blocks — should still be detected
# ---------------------------------------------------------------------------


class TestActualCodeDetection:
    """Real code blocks should still be detected."""

    def test_python_script(self, validator):
        code = """
import os
from pathlib import Path

def process_files():
    for f in Path('.').iterdir():
        print(f)
"""
        assert validator._contains_code_indicators(code) is True

    def test_javascript_module(self, validator):
        code = """
const express = require('express');
const app = express();

function handleRequest(req, res) {
    res.send('Hello');
}
"""
        assert validator._contains_code_indicators(code) is True

    def test_html_with_script(self, validator):
        code = "<html><body><script>alert('test')</script></body></html>"
        assert validator._contains_code_indicators(code) is True

    def test_sql_injection_attempt(self, validator):
        code = "'; DROP TABLE users; --"
        # Single SQL keyword without line-anchor should not trigger
        # unless it's a strong indicator. DROP alone is weak.
        assert validator._contains_code_indicators(code) is False


# ---------------------------------------------------------------------------
# Large string sampling
# ---------------------------------------------------------------------------


class TestLargeStringSampling:
    """Verify sampling logic for strings > 10KB."""

    def test_large_clean_string(self, validator):
        """Large non-code string should not be flagged."""
        text = "This is a normal paragraph. " * 1000  # ~28KB
        assert validator._contains_code_indicators(text) is False

    def test_large_string_with_code_at_start(self, validator):
        """Code at the start of a large string should be detected."""
        code_block = "\nimport os\nfrom pathlib import Path\ndef main():\n    pass\n"
        padding = "Normal text. " * 1000
        text = code_block + padding
        assert validator._contains_code_indicators(text) is True

    def test_large_string_with_code_at_end(self, validator):
        """Code at the end of a large string should be detected."""
        padding = "Normal text. " * 1000
        code_block = "\nimport os\nfrom pathlib import Path\ndef main():\n    pass\n"
        text = padding + code_block
        assert validator._contains_code_indicators(text) is True
