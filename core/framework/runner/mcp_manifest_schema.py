"""JSON Schema and validation helpers for MCP server manifests."""

from __future__ import annotations

import jsonschema

MANIFEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "name",
        "display_name",
        "version",
        "description",
        "author",
        "maintainer",
        "repository",
        "license",
        "status",
        "transport",
        "install",
        "tools",
    ],
    "properties": {
        "name": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
        "display_name": {"type": "string"},
        "version": {"type": "string"},
        "description": {"type": "string"},
        "author": {
            "type": "object",
            "required": ["name", "github"],
            "properties": {
                "name": {"type": "string"},
                "github": {"type": "string"},
                "url": {"type": "string"},
            },
        },
        "maintainer": {
            "type": "object",
            "required": ["github"],
            "properties": {
                "github": {"type": "string"},
                "email": {"type": "string", "format": "email"},
            },
        },
        "repository": {"type": "string"},
        "license": {"type": "string"},
        "status": {"type": "string", "enum": ["official", "verified", "community"]},
        "transport": {
            "type": "object",
            "required": ["supported", "default"],
            "properties": {
                "supported": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["stdio", "http", "unix", "sse"]},
                },
                "default": {"type": "string", "enum": ["stdio", "http", "unix", "sse"]},
            },
        },
        "install": {
            "type": "object",
            "properties": {
                "pip": {"type": ["string", "null"]},
                "docker": {"type": ["string", "null"]},
                "npm": {"type": ["string", "null"]},
            },
        },
        "tools": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "description"],
                "properties": {
                    "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                    "description": {"type": "string"},
                },
            },
        },
        "credentials": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "env_var", "description", "required"],
                "properties": {
                    "id": {"type": "string"},
                    "env_var": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]*$"},
                    "description": {"type": "string"},
                    "help_url": {"type": "string"},
                    "required": {"type": "boolean"},
                },
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "categories": {"type": "array", "items": {"type": "string"}},
        "mcp_protocol_version": {"type": "string"},
        "docs_url": {"type": "string"},
        "supported_os": {
            "type": "array",
            "items": {"type": "string", "enum": ["linux", "macos", "windows"]},
        },
        "example_agent_url": {"type": "string"},
        "deprecated": {"type": "boolean"},
        "deprecated_by": {"type": "string"},
        # Transport config blocks
        "stdio": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}},
            },
        },
        "http": {
            "type": "object",
            "properties": {
                "default_port": {"type": "integer"},
                "health_path": {"type": "string"},
                "command": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}},
            },
        },
        "unix": {
            "type": "object",
            "properties": {
                "socket_template": {"type": "string"},
                "command": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}},
            },
        },
        # Hive extension block
        "hive": {
            "type": "object",
            "properties": {
                "min_version": {"type": ["string", "null"]},
                "max_version": {"type": ["string", "null"]},
                "profiles": {"type": "array", "items": {"type": "string"}},
                "tool_namespace": {"type": "string"},
                "example_agent": {"type": "string"},
            },
        },
    },
}


def _format_path(path: list) -> str:
    """Convert a jsonschema error path to a human-readable string like 'tools[0].name'."""
    parts: list[str] = []
    for segment in path:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        elif parts:
            parts.append(f".{segment}")
        else:
            parts.append(segment)
    return "".join(parts)


_FIX_SUGGESTIONS: dict[str, str] = {
    "name": "Use lowercase letters and hyphens only (e.g., 'my-server')",
    "tools.name": "Use snake_case (e.g., 'create_issue')",
    "credentials.env_var": "Use UPPER_SNAKE_CASE (e.g., 'MY_API_KEY')",
    "status": "Must be one of: official, verified, community",
    "transport.supported": "Supported transports: stdio, http, unix, sse",
    "transport.default": "Must be one of: stdio, http, unix, sse",
}


def _suggest_fix(error: jsonschema.ValidationError) -> str | None:
    """Return a human-readable fix suggestion for a schema validation error, or None."""
    path_parts = list(error.absolute_path)
    # Match leaf field name (e.g., "name" inside tools[0])
    if path_parts:
        leaf = str(path_parts[-1])
        # Check compound key first (e.g., "tools.name" for path [tools, 0, name])
        if len(path_parts) >= 2:
            if not isinstance(path_parts[-2], int):
                parent = str(path_parts[-2])
            elif len(path_parts) >= 3:
                parent = str(path_parts[-3])
            else:
                parent = ""
            compound = f"{parent}.{leaf}"
            if compound in _FIX_SUGGESTIONS:
                return _FIX_SUGGESTIONS[compound]
        if leaf in _FIX_SUGGESTIONS:
            return _FIX_SUGGESTIONS[leaf]
    return None


def validate_manifest(data: dict) -> list[str]:
    """Validate a manifest dict against the schema. Returns a list of error strings.

    Each error string includes context and, where possible, a suggested fix.
    """
    validator = jsonschema.Draft202012Validator(MANIFEST_SCHEMA)
    errors: list[str] = []

    for error in validator.iter_errors(data):
        path = _format_path(list(error.absolute_path))
        msg = f"{path}: {error.message}" if path else error.message
        fix = _suggest_fix(error)
        if fix:
            msg += f"\n       Fix: {fix}"
        errors.append(msg)

    # Cross-validation: each declared transport must have a matching config block
    transport = data.get("transport", {})
    supported = transport.get("supported", [])
    for t in supported:
        if t not in data:
            errors.append(
                f"transport: Config block '{t}' is missing but '{t}' is listed in"
                f" transport.supported\n"
                f"       Fix: Add a '{t}' section with the server command and args"
            )

    return errors
