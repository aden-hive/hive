"""
Tests for ToolRegistry type inference in register_function().

Tests enhanced type inference for function parameters including:
- Union types (int | None, Union[int, float])
- Optional[T]
- Generic types (list[T], dict[str, V])
- Pydantic BaseModel parameters
- Required vs optional parameter detection
"""

from typing import Optional, Union

from framework.runner.tool_registry import ToolRegistry


class TestToolRegistryTypeInference:
    """Tests for type inference in register_function()."""

    def test_list_str_type(self):
        """Should infer list[str] as array with string items."""
        registry = ToolRegistry()

        def test_func(items: list[str]) -> dict:
            return {"count": len(items)}

        registry.register_function(test_func)
        tool = registry.get_tools()["test_func"]

        assert tool.parameters["properties"]["items"]["type"] == "array"
        assert tool.parameters["properties"]["items"]["items"]["type"] == "string"
        assert "items" in tool.parameters["required"]

    def test_dict_str_int_type(self):
        """Should infer dict[str, int] as object with integer additionalProperties."""
        registry = ToolRegistry()

        def test_func(scores: dict[str, int]) -> dict:
            return {"total": sum(scores.values())}

        registry.register_function(test_func)
        tool = registry.get_tools()["test_func"]

        assert tool.parameters["properties"]["scores"]["type"] == "object"
        assert (
            tool.parameters["properties"]["scores"]["additionalProperties"]["type"]
            == "integer"
        )
        assert "scores" in tool.parameters["required"]

    def test_optional_str_type(self):
        """Should infer Optional[str] as string and mark as optional."""
        registry = ToolRegistry()

        def test_func(name: Optional[str]) -> dict:
            return {"greeting": f"Hello, {name or 'Guest'}"}

        registry.register_function(test_func)
        tool = registry.get_tools()["test_func"]

        assert tool.parameters["properties"]["name"]["type"] == "string"
        assert "name" not in tool.parameters["required"]

    def test_union_with_none_type(self):
        """Should infer int | None as integer and mark as optional."""
        registry = ToolRegistry()

        def test_func(count: int | None) -> dict:
            return {"value": count or 0}

        registry.register_function(test_func)
        tool = registry.get_tools()["test_func"]

        assert tool.parameters["properties"]["count"]["type"] == "integer"
        assert "count" not in tool.parameters["required"]

    def test_union_types(self):
        """Should infer Union[int, float] as first type (int -> integer)."""
        registry = ToolRegistry()

        def test_func(value: Union[int, float]) -> dict:
            return {"result": value}

        registry.register_function(test_func)
        tool = registry.get_tools()["test_func"]

        # Should use first type in union
        assert tool.parameters["properties"]["value"]["type"] == "integer"
        assert "value" in tool.parameters["required"]

    def test_pydantic_basemodel_parameter(self):
        """Should infer Pydantic BaseModel parameter using model_json_schema()."""
        try:
            from pydantic import BaseModel

            registry = ToolRegistry()

            class UserInput(BaseModel):
                """User input model."""

                name: str
                age: int

            def test_func(user: UserInput) -> dict:
                return {"greeting": f"Hello, {user.name}"}

            registry.register_function(test_func)
            tool = registry.get_tools()["test_func"]

            # Should use Pydantic's JSON schema
            user_schema = tool.parameters["properties"]["user"]
            assert "properties" in user_schema or "type" in user_schema
            assert "user" in tool.parameters["required"]
        except ImportError:
            # Skip if Pydantic not available
            pass

    def test_backward_compatibility_simple_int(self):
        """Should maintain backward compatibility for simple int parameter."""
        registry = ToolRegistry()

        def test_func(count: int) -> dict:
            return {"result": count}

        registry.register_function(test_func)
        tool = registry.get_tools()["test_func"]

        assert tool.parameters["properties"]["count"]["type"] == "integer"
        assert "count" in tool.parameters["required"]

    def test_backward_compatibility_simple_str(self):
        """Should maintain backward compatibility for simple str parameter."""
        registry = ToolRegistry()

        def test_func(name: str) -> dict:
            return {"greeting": f"Hello, {name}"}

        registry.register_function(test_func)
        tool = registry.get_tools()["test_func"]

        assert tool.parameters["properties"]["name"]["type"] == "string"
        assert "name" in tool.parameters["required"]

    def test_optional_with_default(self):
        """Should mark parameter as optional when default value is provided."""
        registry = ToolRegistry()

        def test_func(name: str = "Guest") -> dict:
            return {"greeting": f"Hello, {name}"}

        registry.register_function(test_func)
        tool = registry.get_tools()["test_func"]

        assert tool.parameters["properties"]["name"]["type"] == "string"
        assert "name" not in tool.parameters["required"]

    def test_optional_union_with_default(self):
        """Should handle Optional[T] with default value."""
        registry = ToolRegistry()

        def test_func(count: Optional[int] = None) -> dict:
            return {"value": count or 0}

        registry.register_function(test_func)
        tool = registry.get_tools()["test_func"]

        assert tool.parameters["properties"]["count"]["type"] == "integer"
        assert "count" not in tool.parameters["required"]

    def test_list_with_optional_items(self):
        """Should handle list[Optional[str]]."""
        registry = ToolRegistry()

        def test_func(items: list[Optional[str]]) -> dict:
            return {"count": len([i for i in items if i])}

        registry.register_function(test_func)
        tool = registry.get_tools()["test_func"]

        assert tool.parameters["properties"]["items"]["type"] == "array"
        # Items schema should be inferred (may be string or have optional handling)
        assert "items" in tool.parameters["properties"]["items"]
        assert "items" in tool.parameters["required"]

    def test_nested_generics(self):
        """Should handle nested generic types like list[dict[str, int]]."""
        registry = ToolRegistry()

        def test_func(data: list[dict[str, int]]) -> dict:
            return {"total": sum(sum(d.values()) for d in data)}

        registry.register_function(test_func)
        tool = registry.get_tools()["test_func"]

        assert tool.parameters["properties"]["data"]["type"] == "array"
        items_schema = tool.parameters["properties"]["data"]["items"]
        assert items_schema["type"] == "object"
        assert "data" in tool.parameters["required"]

    def test_unannotated_parameter(self):
        """Should default unannotated parameters to string and mark as required."""
        registry = ToolRegistry()

        def test_func(value) -> dict:  # noqa: ANN001
            return {"result": str(value)}

        registry.register_function(test_func)
        tool = registry.get_tools()["test_func"]

        assert tool.parameters["properties"]["value"]["type"] == "string"
        assert "value" in tool.parameters["required"]
