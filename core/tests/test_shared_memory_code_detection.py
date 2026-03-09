"""Tests for SharedMemory code detection — false positives and true positives."""

import pytest

from framework.graph.node import SharedMemory


class TestFalsePositives:
    """Natural language text should NOT be rejected."""

    def test_business_report_with_import(self):
        """A report mentioning 'import' once should not be flagged."""
        mem = SharedMemory()
        report = (
            "Our analysis shows that we should import data from multiple sources. "
            "The market dynamics require a comprehensive approach to gathering "
            "information from various industry sectors. "
        ) * 30  # ~5400 chars, over the 5000 threshold
        mem.write("report", report)  # should not raise

    def test_report_with_class_and_from(self):
        """Words like 'class' and 'from' are normal English."""
        mem = SharedMemory()
        report = (
            "The class of assets defined by their risk profile varies. "
            "Data collected from regional offices shows growth trends. "
        ) * 30
        mem.write("report", report)

    def test_report_with_select_keyword(self):
        """'SELECT' alone in a business context is not SQL."""
        mem = SharedMemory()
        report = (
            "We need to SELECT the best candidates from the applicant pool. "
            "The committee will UPDATE their recommendations next quarter. "
        ) * 25
        # Two weak indicators is still under threshold
        mem.write("report", report)

    def test_short_text_never_rejected(self):
        """Text under 5000 chars is never checked regardless of content."""
        mem = SharedMemory()
        mem.write("short", "import os\nclass Foo:\n    def bar(self):\n        pass")


class TestTruePositives:
    """Actual code should still be caught."""

    def test_python_code_block(self):
        mem = SharedMemory()
        code = '```python\ndef hello():\n    print("world")\n```' + ("x" * 5000)
        with pytest.raises(Exception, match="Rejected suspicious"):
            mem.write("output", code)

    def test_multiple_code_keywords(self):
        """Text with 3+ code indicators should be caught."""
        mem = SharedMemory()
        code = (
            "import os\n"
            "from pathlib import Path\n"
            "class MyClass:\n"
            "    def method(self):\n"
            "        const = 42\n"
        ) * 60  # ~5600 chars, over the 5000 threshold
        with pytest.raises(Exception, match="Rejected suspicious"):
            mem.write("output", code)

    def test_javascript_code(self):
        mem = SharedMemory()
        code = (
            "const express = require('express');\n"
            "function handleRequest(req, res) {\n"
            "  export default class App => {\n"
        ) * 80
        with pytest.raises(Exception, match="Rejected suspicious"):
            mem.write("output", code)

    def test_script_tag_always_caught(self):
        """Strong indicators like <script should always trigger."""
        mem = SharedMemory()
        text = "Some normal text " * 300 + "<script>alert('xss')</script>"
        with pytest.raises(Exception, match="Rejected suspicious"):
            mem.write("output", text)


class TestEdgeCases:
    def test_validate_false_bypasses_check(self):
        """validate=False should always allow writes."""
        mem = SharedMemory()
        code = "```python\nimport os\nclass Foo:\n    def bar(self):\n        pass\n```" * 100
        mem.write("output", code, validate=False)  # should not raise

    def test_non_string_values_skip_check(self):
        mem = SharedMemory()
        mem.write("data", {"import": "from", "class": "def"})  # dict, not str
        mem.write("items", [1, 2, 3] * 2000)  # list, not str
