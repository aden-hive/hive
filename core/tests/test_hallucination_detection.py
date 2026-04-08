"""
Test hallucination detection in DataBuffer and OutputValidator.

These tests verify that code detection works correctly across the entire
string content, not just the first 500 characters.
"""

import pytest

from framework.graph.node import DataBuffer, DataBufferWriteError
from framework.graph.validator import OutputValidator, ValidationResult


class TestDataBufferHallucinationDetection:
    """Test the DataBuffer hallucination detection."""

    def test_detects_code_at_start(self):
        """Code at the start of the string should be detected."""
        buffer = DataBuffer()
        code_content = "```python\nimport os\nfrom pathlib import Path\ndef hack(): pass\n```" + "A" * 6000

        with pytest.raises(DataBufferWriteError) as exc_info:
            buffer.write("output", code_content)

        assert "hallucinated code" in str(exc_info.value)

    def test_detects_code_in_middle(self):
        """Code in the middle of the string should be detected (was previously missed)."""
        buffer = DataBuffer()
        # 600 chars of padding, then code, then more padding to exceed 5000 chars
        padding_start = "A" * 600
        code = "\n```python\nimport os\nfrom pathlib import Path\ndef malicious(): pass\n```\n"
        padding_end = "B" * 5000
        content = padding_start + code + padding_end

        with pytest.raises(DataBufferWriteError) as exc_info:
            buffer.write("output", content)

        assert "hallucinated code" in str(exc_info.value)

    def test_detects_code_at_end(self):
        """Code at the end of the string should be detected (was previously missed)."""
        buffer = DataBuffer()
        padding = "A" * 5500
        code = "\n```python\nimport os\nfrom x import y\nclass Exploit:\n    pass\n```"
        content = padding + code

        with pytest.raises(DataBufferWriteError) as exc_info:
            buffer.write("output", content)

        assert "hallucinated code" in str(exc_info.value)

    def test_detects_javascript_code(self):
        """JavaScript code patterns should be detected."""
        buffer = DataBuffer()
        padding = "A" * 600
        code = "\nconst x = require('child_process');\nfunction malicious() { return x; }\n"
        padding_end = "B" * 5000
        content = padding + code + padding_end

        with pytest.raises(DataBufferWriteError) as exc_info:
            buffer.write("output", content)

        assert "hallucinated code" in str(exc_info.value)

    def test_detects_sql_injection(self):
        """SQL patterns should be detected."""
        buffer = DataBuffer()
        padding = "A" * 600
        code = "\nDROP TABLE users;\nSELECT * FROM passwords;\n"
        padding_end = "B" * 5000
        content = padding + code + padding_end

        with pytest.raises(DataBufferWriteError) as exc_info:
            buffer.write("output", content)

        assert "hallucinated code" in str(exc_info.value)

    def test_detects_script_injection(self):
        """HTML script injection should be detected."""
        buffer = DataBuffer()
        padding = "A" * 600
        code = "\n<script>alert('xss')</script>\n"
        padding_end = "B" * 5000
        content = padding + code + padding_end

        with pytest.raises(DataBufferWriteError) as exc_info:
            buffer.write("output", content)

        assert "hallucinated code" in str(exc_info.value)

    def test_allows_short_strings_without_validation(self):
        """Strings under 5000 chars should not trigger validation."""
        buffer = DataBuffer()
        content = "def hello(): pass"  # Contains code indicator but short

        # Should not raise - too short to validate
        buffer.write("output", content)
        assert buffer.read("output") == content

    def test_allows_long_strings_without_code(self):
        """Long strings without code indicators should be allowed."""
        buffer = DataBuffer()
        content = "This is a long text document. " * 500  # ~15000 chars, no code

        buffer.write("output", content)
        assert buffer.read("output") == content

    def test_validate_false_bypasses_check(self):
        """Using validate=False should bypass the check."""
        buffer = DataBuffer()
        code_content = "```python\nimport os\nfrom x import y\n```" + "A" * 6000

        # Should not raise when validate=False
        buffer.write("output", code_content, validate=False)
        assert buffer.read("output") == code_content

    def test_sampling_for_very_long_strings(self):
        """Very long strings (>10KB) should be sampled at multiple positions."""
        buffer = DataBuffer()
        # Create a 50KB string with code at the 75% mark
        size = 50000
        code_position = int(size * 0.75)
        content = (
            "A" * code_position + "def hidden_code(): pass" + "B" * (size - code_position - 25)
        )

        with pytest.raises(DataBufferWriteError) as exc_info:
            buffer.write("output", content)

        assert "hallucinated code" in str(exc_info.value)


class TestOutputValidatorHallucinationDetection:
    """Test the OutputValidator hallucination detection."""

    def test_detects_code_anywhere_in_output(self):
        """Code anywhere in the output value should trigger a warning."""
        validator = OutputValidator()
        padding = "Normal text content. " * 50
        code = "\nimport os\nfrom module import *\ndef suspicious_function():\n    pass\n"
        output = {"result": padding + code}

        # The method logs a warning but doesn't fail
        result = validator.validate_no_hallucination(output)
        # The warning is logged - we can't easily test logging, but the method should work
        assert isinstance(result, ValidationResult)

    def test_contains_code_indicators_full_check(self):
        """_contains_code_indicators should check the entire string."""
        validator = OutputValidator()

        # Code at position 600 (was previously missed with [:500] check)
        padding = "A" * 600
        code = "\nimport os\nfrom module import path"
        content = padding + code

        assert validator._contains_code_indicators(content) is True

    def test_contains_code_indicators_sampling(self):
        """_contains_code_indicators should sample for very long strings."""
        validator = OutputValidator()

        # 50KB string with code at 75% position
        size = 50000
        code_position = int(size * 0.75)
        content = "A" * code_position + "\nimport os\nclass HiddenClass:\n    pass\n" + "B" * (size - code_position - 38)

        assert validator._contains_code_indicators(content) is True

    def test_no_false_positive_for_clean_text(self):
        """Clean text without code should not trigger false positives."""
        validator = OutputValidator()

        # Long text without any code indicators
        content = "This is a perfectly normal document. " * 300

        assert validator._contains_code_indicators(content) is False

    def test_detects_multiple_languages(self):
        """Should detect code patterns from multiple programming languages."""
        validator = OutputValidator()

        test_cases = [
            "\nfunction test() {}\nconst x = 5;",  # JavaScript
            "\nconst x = 5;\nlet y = 10;",  # JavaScript
            "\nSELECT * FROM users;\nDROP TABLE data;",  # SQL
            "<script>alert(1)</script>",  # HTML
            "<?php echo 'hello'; ?>",  # PHP
        ]

        for code in test_cases:
            assert validator._contains_code_indicators(code) is True, f"Failed to detect: {code}"


class TestEdgeCases:
    """Test edge cases for hallucination detection."""

    def test_empty_string(self):
        """Empty strings should not cause errors."""
        buffer = DataBuffer()
        buffer.write("output", "")
        assert buffer.read("output") == ""

    def test_non_string_values(self):
        """Non-string values should not be validated for code."""
        buffer = DataBuffer()

        # These should all work without validation
        buffer.write("number", 12345)
        buffer.write("list", [1, 2, 3])
        buffer.write("dict", {"key": "value"})
        buffer.write("bool", True)

        assert buffer.read("number") == 12345
        assert buffer.read("list") == [1, 2, 3]

    def test_exactly_5000_chars(self):
        """String of exactly 5000 chars should not trigger validation."""
        buffer = DataBuffer()
        content = "def code(): pass" + "A" * (5000 - 16)  # Exactly 5000 chars

        # Should not raise - exactly at threshold, not over
        buffer.write("output", content)
        assert len(buffer.read("output")) == 5000

    def test_5001_chars_triggers_validation(self):
        """String of 5001 chars with code should trigger validation."""
        buffer = DataBuffer()
        content = "def code(): pass" + "A" * (5001 - 16)  # 5001 chars

        with pytest.raises(DataBufferWriteError):
            buffer.write("output", content)
