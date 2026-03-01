"""JSON/YAML Tool - Validate and convert JSON and YAML data."""

from __future__ import annotations

import json

import yaml
from fastmcp import FastMCP

MAX_CONTENT_SIZE = 10 * 1024 * 1024


def register_tools(mcp: FastMCP) -> None:
    """Register JSON/YAML tools with the MCP server."""

    @mcp.tool()
    def validate_json(content: str, schema: dict | None = None) -> dict:
        """
        Validate JSON content and optionally validate against a JSON Schema.

        Args:
            content: JSON string to validate
            schema: Optional JSON Schema dictionary to validate against

        Returns:
            dict with validation result:
            - valid: bool indicating if JSON is valid
            - data: parsed JSON data (if valid)
            - error: error message (if invalid)
        """
        if len(content) > MAX_CONTENT_SIZE:
            return {
                "valid": False,
                "error": f"Content exceeds maximum size of {MAX_CONTENT_SIZE} bytes",
            }

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            return {"valid": False, "error": f"JSON parsing error: {str(e)}"}

        if schema is not None:
            try:
                import jsonschema
            except ImportError:
                return {
                    "valid": False,
                    "error": "jsonschema not installed. Install with: pip install jsonschema",
                }

            try:
                jsonschema.validate(instance=data, schema=schema)
            except jsonschema.ValidationError as e:
                return {
                    "valid": False,
                    "error": f"Schema validation error: {e.message}",
                    "path": list(e.absolute_path),
                }
            except jsonschema.SchemaError as e:
                return {"valid": False, "error": f"Invalid schema: {e.message}"}

        return {"valid": True, "data": data}

    @mcp.tool()
    def validate_yaml(content: str) -> dict:
        """
        Validate YAML content and parse it.

        Args:
            content: YAML string to validate

        Returns:
            dict with validation result:
            - valid: bool indicating if YAML is valid
            - data: parsed YAML data (if valid)
            - error: error message (if invalid)
        """
        if len(content) > MAX_CONTENT_SIZE:
            return {
                "valid": False,
                "error": f"Content exceeds maximum size of {MAX_CONTENT_SIZE} bytes",
            }

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            return {"valid": False, "error": f"YAML parsing error: {str(e)}"}

        return {"valid": True, "data": data}

    @mcp.tool()
    def json_to_yaml(content: str, indent: int = 2, default_flow_style: bool = False) -> dict:
        """
        Convert JSON content to YAML format.

        Args:
            content: JSON string to convert
            indent: Number of spaces for YAML indentation (default: 2)
            default_flow_style: Use flow style for nested structures (default: False)

        Returns:
            dict with conversion result:
            - success: bool indicating if conversion was successful
            - yaml: YAML string (if successful)
            - error: error message (if failed)
        """
        if len(content) > MAX_CONTENT_SIZE:
            return {
                "success": False,
                "error": f"Content exceeds maximum size of {MAX_CONTENT_SIZE} bytes",
            }

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"JSON parsing error: {str(e)}"}

        try:
            yaml_output = yaml.dump(
                data,
                indent=indent,
                default_flow_style=default_flow_style,
                allow_unicode=True,
                sort_keys=False,
            )
        except yaml.YAMLError as e:
            return {"success": False, "error": f"YAML serialization error: {str(e)}"}

        return {"success": True, "yaml": yaml_output.rstrip("\n")}

    @mcp.tool()
    def yaml_to_json(content: str, indent: int = 2) -> dict:
        """
        Convert YAML content to JSON format.

        Args:
            content: YAML string to convert
            indent: Number of spaces for JSON indentation (default: 2)

        Returns:
            dict with conversion result:
            - success: bool indicating if conversion was successful
            - json: JSON string (if successful)
            - error: error message (if failed)
        """
        if len(content) > MAX_CONTENT_SIZE:
            return {
                "success": False,
                "error": f"Content exceeds maximum size of {MAX_CONTENT_SIZE} bytes",
            }

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            return {"success": False, "error": f"YAML parsing error: {str(e)}"}

        try:
            json_output = json.dumps(data, indent=indent, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            return {"success": False, "error": f"JSON serialization error: {str(e)}"}

        return {"success": True, "json": json_output}
