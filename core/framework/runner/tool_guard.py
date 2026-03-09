from dataclasses import dataclass, field
import logging
from typing import Any

logger = logging.getLogger(__name__)

@dataclass
class SecurityPolicy:
    """Configuration for tool execution security."""
    allowed_tools: list[str] | None = None
    blocked_keywords: list[str] = field(default_factory=list)
    allow_destructive_tools: bool = False
    
    @classmethod
    def default(cls) -> "SecurityPolicy":
        """Returns a default restrictive policy."""
        return cls(
            allowed_tools=None,
            blocked_keywords=["rm -rf", "sudo", "password", "format c:", "mkfs"],
            allow_destructive_tools=False
        )

class ToolSecurityError(Exception):
    """Exception raised when a tool call violates security policy."""
    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason

class ToolGuard:
    """
    Middleware layer that validates agent tool calls before execution.

    Purpose:
    - Mitigates prompt injection attacks by checking tool arguments for blocked keywords.
    - Prevents unsafe or destructive actions (e.g., repository deletion) unless explicitly allowed.
    - Enforces an optional tool allowlist to limit the agent's capabilities.

    Integration:
    - Integrated into `ToolRegistry.get_executor()`, acting as a central choke point for all tool calls.
    - Captures `ToolSecurityError` and returns structured `ToolResult` errors to the agent.
    - Configured via `AgentRunner` using a `SecurityPolicy` object.
    """
    
    DESTRUCTIVE_KEYWORDS = ["delete", "remove", "drop", "shutdown", "terminate"]

    def __init__(self, policy: SecurityPolicy | None = None):
        self.policy = policy or SecurityPolicy.default()

    def validate(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        """
        Validates a tool call against the security policy.
        
        Args:
            tool_name: The name of the tool being called.
            tool_input: The arguments passed to the tool.
            
        Returns:
            True if the call is valid.
            
        Raises:
            ToolSecurityError: If the call violates the policy.
        """
        # 1. Allowlist Check
        if self.policy.allowed_tools is not None:
            if tool_name not in self.policy.allowed_tools:
                reason = f"Tool '{tool_name}' is not in the allowlist."
                logger.warning(f"Security Block: {reason}")
                raise ToolSecurityError(f"Tool execution blocked: {reason}", "not_allowed")

        # 2. Destructive Tool Check
        # Splits the tool name (e.g., "github_delete_repo" -> ["github", "delete", "repo"])
        # to ensure keywords match specific parts and avoid false positives.
        if not self.policy.allow_destructive_tools:
            parts = tool_name.lower().replace(".", "_").split("_")
            if any(word in parts for word in self.DESTRUCTIVE_KEYWORDS):
                reason = f"Tool '{tool_name}' is classified as destructive."
                logger.warning(f"Security Block: {reason}")
                raise ToolSecurityError(f"Tool execution blocked: {reason}", "destructive_tool")

        # 3. Blocked Keywords Check (in arguments)
        # Uses str() instead of json.dumps() to handle non-serializable objects safely.
        input_str = str(tool_input).lower()
        for keyword in self.policy.blocked_keywords:
            if keyword.lower() in input_str:
                reason = f"Blocked keyword '{keyword}' detected in tool arguments."
                logger.warning(f"Security Block: {reason}")
                raise ToolSecurityError(f"Tool execution blocked: {reason}", "blocked_keyword")

        return True
