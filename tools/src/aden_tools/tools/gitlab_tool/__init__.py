"""
GitLab tool module for Aden MCP Server.

Provides tools for interacting with GitLab:
- List projects
- List and create issues
- Get merge request details
- Trigger CI/CD pipelines

Supports both gitlab.com and self-hosted GitLab instances.

Usage:
    from aden_tools.tools.gitlab_tool import register_tools

    register_tools(mcp, credentials=credentials)
"""

from .gitlab import register_tools

__all__ = ["register_tools"]
