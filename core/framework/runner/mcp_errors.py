"""Structured error codes and exceptions for MCP server operations."""

from enum import Enum


class MCPErrorCode(Enum):
    """Standardized error codes for MCP operations."""

    MCP_INSTALL_FAILED = "MCP_INSTALL_FAILED"
    MCP_AUTH_MISSING = "MCP_AUTH_MISSING"
    MCP_CONNECT_TIMEOUT = "MCP_CONNECT_TIMEOUT"
    MCP_TOOL_NOT_FOUND = "MCP_TOOL_NOT_FOUND"
    MCP_PROTOCOL_MISMATCH = "MCP_PROTOCOL_MISMATCH"
    MCP_VERSION_CONFLICT = "MCP_VERSION_CONFLICT"
    MCP_HEALTH_FAILED = "MCP_HEALTH_FAILED"


class MCPError(ValueError):
    """Base exception for all structured MCP errors."""

    def __init__(self, code: MCPErrorCode, what: str, why: str, fix: str):
        self.code = code
        self.what = what
        self.why = why
        self.fix = fix
        self.message = (
            f"[{self.code.value}]\nWhat failed: {self.what}\nWhy: {self.why}\nFix: {self.fix}"
        )
        super().__init__(self.message)


class MCPToolNotFoundError(MCPError):
    def __init__(self, server: str, tool_name: str):
        super().__init__(
            code=MCPErrorCode.MCP_TOOL_NOT_FOUND,
            what=f"Tool '{tool_name}' not found on server '{server}'",
            why=f"The server '{server}' does not expose a tool named '{tool_name}'.",
            fix=f"Run 'hive mcp inspect {server}' to view available tools.",
        )


class MCPConnectTimeoutError(MCPError):
    def __init__(self, server: str, transport: str, timeout_sec: int):
        super().__init__(
            code=MCPErrorCode.MCP_CONNECT_TIMEOUT,
            what=f"Connection timed out while starting server '{server}'",
            why=f"The {transport} transport did not respond within {timeout_sec} seconds.",
            fix=f"Check if the server is running. Run 'hive mcp doctor {server}' for diagnostics.",
        )


class MCPAuthError(MCPError):
    def __init__(self, server: str, env_var: str):
        super().__init__(
            code=MCPErrorCode.MCP_AUTH_MISSING,
            what=f"Authentication failed for server '{server}'",
            why=f"The required environment variable '{env_var}' is missing or empty.",
            fix=f"Run: hive mcp config {server} --set {env_var}=<your-token>",
        )


class MCPInstallError(MCPError):
    def __init__(self, server: str, why: str, fix: str):
        super().__init__(
            code=MCPErrorCode.MCP_INSTALL_FAILED,
            what=f"Could not install MCP server '{server}'",
            why=why,
            fix=fix,
        )


class MCPProtocolMismatchError(MCPError):
    def __init__(self, server: str, detail: str):
        super().__init__(
            code=MCPErrorCode.MCP_PROTOCOL_MISMATCH,
            what=f"Protocol mismatch with server '{server}'",
            why=detail,
            fix=f"Check the MCP SDK version required by '{server}' matches your installation.",
        )


class MCPVersionConflictError(MCPError):
    def __init__(self, server: str, detail: str):
        super().__init__(
            code=MCPErrorCode.MCP_VERSION_CONFLICT,
            what=f"Version conflict with server '{server}'",
            why=detail,
            fix="Update or pin the MCP server package to a compatible version.",
        )


class MCPHealthCheckError(MCPError):
    def __init__(self, server: str, detail: str):
        super().__init__(
            code=MCPErrorCode.MCP_HEALTH_FAILED,
            what=f"Health check failed for server '{server}'",
            why=detail,
            fix=f"Run 'hive mcp doctor {server}' to diagnose the issue.",
        )
