"""Tests for JSON/YAML Tool."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aden_tools.tools.json_yaml_tool.json_yaml_tool import register_tools


class TestValidateJson:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        register_tools(self.mcp)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    def test_validate_json_valid(self):
        result = self._fn("validate_json")(content='{"name": "test", "value": 123}')
        assert result["valid"] is True
        assert result["data"] == {"name": "test", "value": 123}

    def test_validate_json_invalid_syntax(self):
        result = self._fn("validate_json")(content='{"name": invalid}')
        assert result["valid"] is False
        assert "JSON parsing error" in result["error"]

    def test_validate_json_empty_string(self):
        result = self._fn("validate_json")(content="")
        assert result["valid"] is False
        assert "JSON parsing error" in result["error"]

    def test_validate_json_array(self):
        result = self._fn("validate_json")(content="[1, 2, 3]")
        assert result["valid"] is True
        assert result["data"] == [1, 2, 3]

    def test_validate_json_with_schema_valid(self):
        result = self._fn("validate_json")(
            content='{"name": "agent", "version": 1}',
            schema={"type": "object", "required": ["name"]},
        )
        assert result["valid"] is True
        assert result["data"]["name"] == "agent"

    def test_validate_json_with_schema_missing_required(self):
        result = self._fn("validate_json")(
            content='{"version": 1}',
            schema={"type": "object", "required": ["name"]},
        )
        assert result["valid"] is False
        assert "Schema validation error" in result["error"]

    def test_validate_json_with_schema_wrong_type(self):
        result = self._fn("validate_json")(
            content='{"name": "agent", "count": "not_a_number"}',
            schema={"type": "object", "properties": {"count": {"type": "number"}}},
        )
        assert result["valid"] is False
        assert "Schema validation error" in result["error"]

    def test_validate_json_with_invalid_schema(self):
        result = self._fn("validate_json")(
            content='{"name": "agent"}',
            schema={"type": "invalid_type"},
        )
        assert result["valid"] is False
        assert "Invalid schema" in result["error"]

    def test_validate_json_exceeds_size_limit(self):
        large_content = "x" * (11 * 1024 * 1024)
        result = self._fn("validate_json")(content=large_content)
        assert result["valid"] is False
        assert "exceeds maximum size" in result["error"]


class TestValidateYaml:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        register_tools(self.mcp)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    def test_validate_yaml_valid(self):
        result = self._fn("validate_yaml")(content="name: test\nvalue: 123")
        assert result["valid"] is True
        assert result["data"] == {"name": "test", "value": 123}

    def test_validate_yaml_invalid_syntax(self):
        result = self._fn("validate_yaml")(content="name: test\n  bad_indent: value")
        assert result["valid"] is False
        assert "YAML parsing error" in result["error"]

    def test_validate_yaml_empty_string(self):
        result = self._fn("validate_yaml")(content="")
        assert result["valid"] is True
        assert result["data"] is None

    def test_validate_yaml_list(self):
        result = self._fn("validate_yaml")(content="- item1\n- item2\n- item3")
        assert result["valid"] is True
        assert result["data"] == ["item1", "item2", "item3"]

    def test_validate_yaml_nested(self):
        result = self._fn("validate_yaml")(
            content="parent:\n  child: value\n  nested:\n    deep: true"
        )
        assert result["valid"] is True
        assert result["data"]["parent"]["nested"]["deep"] is True

    def test_validate_yaml_exceeds_size_limit(self):
        large_content = "x" * (11 * 1024 * 1024)
        result = self._fn("validate_yaml")(content=large_content)
        assert result["valid"] is False
        assert "exceeds maximum size" in result["error"]


class TestJsonToYaml:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        register_tools(self.mcp)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    def test_json_to_yaml_simple(self):
        result = self._fn("json_to_yaml")(content='{"key": "value"}')
        assert result["success"] is True
        assert result["yaml"] == "key: value"

    def test_json_to_yaml_nested(self):
        result = self._fn("json_to_yaml")(content='{"parent": {"child": "value"}}')
        assert result["success"] is True
        assert "parent:" in result["yaml"]
        assert "child: value" in result["yaml"]

    def test_json_to_yaml_array(self):
        result = self._fn("json_to_yaml")(content="[1, 2, 3]")
        assert result["success"] is True
        assert "- 1" in result["yaml"]
        assert "- 2" in result["yaml"]
        assert "- 3" in result["yaml"]

    def test_json_to_yaml_custom_indent(self):
        result = self._fn("json_to_yaml")(content='{"parent": {"child": "value"}}', indent=4)
        assert result["success"] is True
        assert "    child: value" in result["yaml"]

    def test_json_to_yaml_invalid_json(self):
        result = self._fn("json_to_yaml")(content="{invalid json}")
        assert result["success"] is False
        assert "JSON parsing error" in result["error"]

    def test_json_to_yaml_unicode(self):
        result = self._fn("json_to_yaml")(content='{"greeting": "hello world"}')
        assert result["success"] is True
        assert "greeting: hello world" in result["yaml"]

    def test_json_to_yaml_exceeds_size_limit(self):
        large_content = "x" * (11 * 1024 * 1024)
        result = self._fn("json_to_yaml")(content=large_content)
        assert result["success"] is False
        assert "exceeds maximum size" in result["error"]


class TestYamlToJson:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        register_tools(self.mcp)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    def test_yaml_to_json_simple(self):
        result = self._fn("yaml_to_json")(content="key: value")
        assert result["success"] is True
        assert result["json"] == '{"key": "value"}'

    def test_yaml_to_json_nested(self):
        result = self._fn("yaml_to_json")(content="parent:\n  child: value")
        assert result["success"] is True
        assert '"parent"' in result["json"]
        assert '"child": "value"' in result["json"]

    def test_yaml_to_json_array(self):
        result = self._fn("yaml_to_json")(content="- item1\n- item2")
        assert result["success"] is True
        assert result["json"] == '["item1", "item2"]'

    def test_yaml_to_json_custom_indent(self):
        result = self._fn("yaml_to_json")(content="key: value", indent=4)
        assert result["success"] is True
        assert "    " in result["json"]

    def test_yaml_to_json_compact(self):
        result = self._fn("yaml_to_json")(content="key: value", indent=None)
        assert result["success"] is True
        assert result["json"] == '{"key": "value"}'

    def test_yaml_to_json_invalid_yaml(self):
        result = self._fn("yaml_to_json")(content="key: value\n  bad: indent")
        assert result["success"] is False
        assert "YAML parsing error" in result["error"]

    def test_yaml_to_json_numbers(self):
        result = self._fn("yaml_to_json")(content="integer: 42\nfloat: 3.14")
        assert result["success"] is True
        assert '"integer": 42' in result["json"]
        assert '"float": 3.14' in result["json"]

    def test_yaml_to_json_exceeds_size_limit(self):
        large_content = "x" * (11 * 1024 * 1024)
        result = self._fn("yaml_to_json")(content=large_content)
        assert result["success"] is False
        assert "exceeds maximum size" in result["error"]


class TestToolRegistration:
    def test_register_tools_registers_all_tools(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        assert mcp.tool.call_count == 4
