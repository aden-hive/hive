"""Tests for json_read tool (FastMCP)."""

from pathlib import Path

import pytest
from fastmcp import FastMCP

from aden_tools.tools.json_read_tool import register_tools


@pytest.fixture
def json_read_fn(mcp: FastMCP):
    """Register and return the json_read tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["json_read"].fn


class TestJsonReadTool:
    """Tests for json_read tool."""

    def test_read_json_file_not_found(self, json_read_fn, tmp_path: Path):
        """Reading non-existent JSON returns error."""
        result = json_read_fn(file_path=str(tmp_path / "missing.json"))

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_read_json_invalid_extension(self, json_read_fn, tmp_path: Path):
        """Reading non-JSON file returns error."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text('{"a": 1}')

        result = json_read_fn(file_path=str(txt_file))

        assert "error" in result
        assert "not a json" in result["error"].lower()

    def test_read_json_directory(self, json_read_fn, tmp_path: Path):
        """Reading a directory returns error."""
        result = json_read_fn(file_path=str(tmp_path))

        assert "error" in result
        assert "not a file" in result["error"].lower()

    def test_read_valid_json(self, json_read_fn, sample_json: Path):
        """Read and parse valid JSON file."""
        result = json_read_fn(file_path=str(sample_json))

        assert "error" not in result
        assert result["content"]["users"][0]["name"] == "Alice"
        assert result["content"]["users"][1]["age"] == 25
        assert "path" in result
        assert "name" in result

    def test_read_json_with_jsonpath(self, json_read_fn, sample_json: Path):
        """Extract data using JSONPath expression."""
        result = json_read_fn(
            file_path=str(sample_json),
            jsonpath="$.users[*].name",
        )

        assert "error" not in result
        assert result["content"] == ["Alice", "Bob"]
        assert result["jsonpath"] == "$.users[*].name"
        assert result["match_count"] == 2

    def test_read_json_jsonpath_single_match(self, json_read_fn, tmp_path: Path):
        """JSONPath with single match returns value directly."""
        json_file = tmp_path / "test.json"
        json_file.write_text('{"version": "1.0.0", "name": "my-app"}')

        result = json_read_fn(
            file_path=str(json_file),
            jsonpath="$.version",
        )

        assert "error" not in result
        assert result["content"] == "1.0.0"

    def test_read_json_invalid_jsonpath(self, json_read_fn, sample_json: Path):
        """Invalid JSONPath returns error."""
        result = json_read_fn(
            file_path=str(sample_json),
            jsonpath="invalid[path",
        )

        assert "error" in result
        assert "jsonpath" in result["error"].lower()

    def test_read_json_invalid_syntax(self, json_read_fn, tmp_path: Path):
        """Invalid JSON syntax returns error."""
        json_file = tmp_path / "bad.json"
        json_file.write_text("{ invalid json }")

        result = json_read_fn(file_path=str(json_file))

        assert "error" in result
        assert "invalid json" in result["error"].lower()

    def test_max_content_length_respected(self, json_read_fn, tmp_path: Path):
        """File exceeding max_content_length returns error."""
        json_file = tmp_path / "large.json"
        json_file.write_text('{"data": "' + "x" * 2000 + '"}')

        result = json_read_fn(
            file_path=str(json_file),
            max_content_length=1000,
        )

        assert "error" in result
        assert "too large" in result["error"].lower()

    def test_max_content_length_clamped(self, json_read_fn, sample_json: Path):
        """max_content_length outside range is clamped."""
        result = json_read_fn(
            file_path=str(sample_json),
            max_content_length=500,
        )

        assert "error" not in result
        assert "content" in result
