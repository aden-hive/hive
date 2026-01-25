"""
Structured error classification for the Agent Framework.

This module defines a hierarchy of exception classes to distinguish between
different types of failures (transient vs terminal, rate limits, auth errors, etc.)
allowing for more intelligent retry and recovery strategies.
"""

class AgentError(Exception):
    """Base class for all agent-related errors."""
    pass


class TransientError(AgentError):
    """
    Temporary failure that is likely to succeed if retried.
    
    Examples: Network timeouts, temporary service outages, 5xx responses.
    """
    pass


class RateLimitError(TransientError):
    """
    Rate limit exceeded (HTTP 429).
    
    Attributes:
        retry_after (float): Recommended wait time in seconds before retrying.
    """
    def __init__(self, message: str, retry_after: float = 1.0):
        super().__init__(message)
        self.retry_after = retry_after


class TerminalError(AgentError):
    """
    Permanent failure that will not succeed if retried without changes.
    """
    pass


class AuthenticationError(TerminalError):
    """
    Authentication failed (HTTP 401/403).
    
    This is generally a terminal error unless credentials are rotated.
    """
    pass


class ValidationError(TerminalError):
    """
    Input validation failed (HTTP 400).
    
    The request was invalid and must be modified before retrying.
    """
    pass


class ConfigurationError(TerminalError):
    """
    Invalid configuration preventing execution.
    """
    pass


class ToolExecutionError(AgentError):
    """
    Error during tool execution.
    
    May be transient or terminal depending on the cause.
    """
    def __init__(self, message: str, tool_name: str, retryable: bool = False):
        super().__init__(f"Tool '{tool_name}' failed: {message}")
        self.tool_name = tool_name
        self.retryable = retryable
