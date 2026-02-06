"""MCP servers for Hive agent framework."""

# Available servers:
# - agent_builder_server: Tools for building goal-driven agents
# - credential_manager_server: Tools for secure credential management

# Don't auto-import servers to avoid double-import issues when running with -m
__all__ = [
    "agent_builder_server",
    "credential_manager_server",
]
