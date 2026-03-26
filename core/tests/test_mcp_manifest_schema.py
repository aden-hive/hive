"""Tests for MCP manifest schema validation."""

from framework.runner.mcp_manifest_schema import validate_manifest

# Based on the Jira example from PRD section 7.1
VALID_MANIFEST = {
    "name": "jira",
    "display_name": "Jira MCP Server",
    "version": "1.2.0",
    "description": "Interact with Jira issues, boards, and sprints",
    "author": {
        "name": "Jane Contributor",
        "github": "janedev",
        "url": "https://github.com/janedev",
    },
    "maintainer": {"github": "janedev", "email": "jane@example.com"},
    "repository": "https://github.com/janedev/jira-mcp-server",
    "license": "MIT",
    "status": "community",
    "transport": {"supported": ["stdio", "http"], "default": "stdio"},
    "install": {"pip": "jira-mcp-server", "docker": None, "npm": None},
    "stdio": {"command": "uvx", "args": ["jira-mcp-server", "--stdio"]},
    "http": {
        "default_port": 4010,
        "health_path": "/health",
        "command": "uvx",
        "args": ["jira-mcp-server", "--http", "--port", "{port}"],
    },
    "tools": [
        {"name": "jira_create_issue", "description": "Create a new Jira issue"},
        {"name": "jira_search", "description": "Search Jira issues with JQL"},
    ],
    "credentials": [
        {
            "id": "jira_api_token",
            "env_var": "JIRA_API_TOKEN",
            "description": "Jira API token",
            "help_url": "https://id.atlassian.com/manage-profile/security/api-tokens",
            "required": True,
        },
    ],
    "tags": ["project-management", "atlassian"],
    "categories": ["productivity"],
    "mcp_protocol_version": "2024-11-05",
}


def test_valid_manifest_passes():
    errors = validate_manifest(VALID_MANIFEST)
    assert errors == []


def test_missing_name():
    manifest = {**VALID_MANIFEST}
    del manifest["name"]
    errors = validate_manifest(manifest)
    assert any("name" in e for e in errors)


def test_bad_name_format():
    manifest = {**VALID_MANIFEST, "name": "My Server"}
    errors = validate_manifest(manifest)
    assert any("name" in e and "match" in e for e in errors)


def test_bad_tool_name_format():
    manifest = {**VALID_MANIFEST, "tools": [{"name": "createIssue", "description": "..."}]}
    errors = validate_manifest(manifest)
    assert any("name" in e for e in errors)


def test_bad_credential_env_var():
    manifest = {
        **VALID_MANIFEST,
        "credentials": [{"id": "x", "env_var": "bad_var", "description": "...", "required": True}],
    }
    errors = validate_manifest(manifest)
    assert any("env_var" in e for e in errors)


def test_invalid_status():
    manifest = {**VALID_MANIFEST, "status": "unknown"}
    errors = validate_manifest(manifest)
    assert any("status" in e for e in errors)


def test_missing_transport_config():
    manifest = {**VALID_MANIFEST}
    manifest["transport"] = {"supported": ["stdio", "http"], "default": "stdio"}
    manifest.pop("http", None)
    errors = validate_manifest(manifest)
    assert any("http" in e for e in errors)


def test_minimal_valid_manifest():
    manifest = {
        "name": "minimal",
        "display_name": "Minimal Server",
        "version": "0.1.0",
        "description": "A minimal MCP server",
        "author": {"name": "Test", "github": "testuser"},
        "maintainer": {"github": "testuser"},
        "repository": "https://github.com/testuser/minimal",
        "license": "MIT",
        "status": "community",
        "transport": {"supported": ["stdio"], "default": "stdio"},
        "install": {"pip": "minimal-server"},
        "stdio": {"command": "uvx", "args": ["minimal-server"]},
        "tools": [{"name": "do_thing", "description": "Does a thing"}],
    }
    errors = validate_manifest(manifest)
    assert errors == []


def test_valid_manifest_with_hive_block():
    manifest = {**VALID_MANIFEST, "hive": {"min_version": "0.5.0", "profiles": ["core"]}}
    errors = validate_manifest(manifest)
    assert errors == []


def test_fix_suggestion_for_bad_name():
    manifest = {**VALID_MANIFEST, "name": "My Server"}
    errors = validate_manifest(manifest)
    assert any("Fix:" in e for e in errors)


def test_fix_suggestion_for_missing_transport_config():
    manifest = {**VALID_MANIFEST}
    manifest["transport"] = {"supported": ["stdio", "http"], "default": "stdio"}
    manifest.pop("http", None)
    errors = validate_manifest(manifest)
    assert any("Fix:" in e for e in errors)


def test_example_agent_url_field_accepted():
    manifest = {**VALID_MANIFEST, "example_agent_url": "https://example.com/agent"}
    errors = validate_manifest(manifest)
    assert errors == []
