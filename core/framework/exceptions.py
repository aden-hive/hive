"""
Hive Framework Exceptions.

A hierarchical exception system for structured error handling across:
- LLM operations (provider errors, rate limits, API failures)
- Runner operations (agent loading, tool execution, validation)
- Orchestrator operations (routing, message relay, capability checks)
- Graph execution (node failures, edge conditions, execution limits)

All exceptions include:
- Descriptive messages with context
- Optional original exception chaining
- Structured error codes for programmatic handling
"""

from __future__ import annotations

from typing import Any


class HiveError(Exception):
    """
    Base exception for all Hive framework errors.

    Attributes:
        message: Human-readable error description
        error_code: Machine-readable error code for categorization
        context: Additional context dict for debugging
        original_error: The underlying exception if this wraps another error
    """

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        context: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ):
        self.message = message
        self.error_code = error_code or "HIVE_ERROR"
        self.context = context or {}
        self.original_error = original_error

        # Build full message with context
        full_message = message
        if context:
            context_str = ", ".join(f"{k}={v}" for k, v in context.items())
            full_message = f"{message} [{context_str}]"

        super().__init__(full_message)

        # Chain the original exception if provided
        if original_error:
            self.__cause__ = original_error


# === LLM Exceptions ===


class LLMError(HiveError):
    """Base exception for LLM provider operations."""

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {})
        if provider:
            context["provider"] = provider
        if model:
            context["model"] = model
        super().__init__(message, context=context, **kwargs)


class LLMProviderNotAvailableError(LLMError):
    """Raised when an LLM provider cannot be initialized (missing API key, import failure)."""

    def __init__(self, provider: str, reason: str, **kwargs: Any):
        super().__init__(
            f"LLM provider '{provider}' is not available: {reason}",
            error_code="LLM_PROVIDER_NOT_AVAILABLE",
            provider=provider,
            **kwargs,
        )


class LLMAPIError(LLMError):
    """Raised when an LLM API call fails."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {})
        if status_code:
            context["status_code"] = status_code
        super().__init__(
            message,
            error_code="LLM_API_ERROR",
            context=context,
            **kwargs,
        )


class LLMResponseParseError(LLMError):
    """Raised when LLM response cannot be parsed (e.g., invalid JSON)."""

    def __init__(self, message: str, response_content: str | None = None, **kwargs: Any):
        context = kwargs.pop("context", {})
        if response_content:
            # Truncate for logging safety
            context["response_preview"] = response_content[:200]
        super().__init__(
            message,
            error_code="LLM_RESPONSE_PARSE_ERROR",
            context=context,
            **kwargs,
        )


# === Runner Exceptions ===


class RunnerError(HiveError):
    """Base exception for agent runner operations."""

    def __init__(self, message: str, agent_name: str | None = None, **kwargs: Any):
        context = kwargs.pop("context", {})
        if agent_name:
            context["agent"] = agent_name
        super().__init__(message, context=context, **kwargs)


class AgentLoadError(RunnerError):
    """Raised when an agent cannot be loaded from disk."""

    def __init__(self, agent_path: str, reason: str, **kwargs: Any):
        super().__init__(
            f"Failed to load agent from '{agent_path}': {reason}",
            error_code="AGENT_LOAD_ERROR",
            **kwargs,
        )


class AgentValidationError(RunnerError):
    """Raised when agent validation fails."""

    def __init__(
        self,
        message: str,
        errors: list[str] | None = None,
        missing_tools: list[str] | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {})
        if errors:
            context["errors"] = errors
        if missing_tools:
            context["missing_tools"] = missing_tools
        super().__init__(
            message,
            error_code="AGENT_VALIDATION_ERROR",
            context=context,
            **kwargs,
        )


class ToolExecutionError(RunnerError):
    """Raised when a tool execution fails."""

    def __init__(
        self,
        tool_name: str,
        message: str,
        tool_input: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {})
        context["tool"] = tool_name
        if tool_input:
            context["input"] = tool_input
        super().__init__(
            f"Tool '{tool_name}' failed: {message}",
            error_code="TOOL_EXECUTION_ERROR",
            context=context,
            **kwargs,
        )


class MCPServerError(RunnerError):
    """Raised when MCP server registration or communication fails."""

    def __init__(self, server_name: str, message: str, **kwargs: Any):
        context = kwargs.pop("context", {})
        context["server"] = server_name
        super().__init__(
            f"MCP server '{server_name}' error: {message}",
            error_code="MCP_SERVER_ERROR",
            context=context,
            **kwargs,
        )


# === Orchestrator Exceptions ===


class OrchestratorError(HiveError):
    """Base exception for orchestrator operations."""

    pass


class RoutingError(OrchestratorError):
    """Raised when request routing fails."""

    def __init__(
        self,
        message: str,
        available_agents: list[str] | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {})
        if available_agents:
            context["available_agents"] = available_agents
        super().__init__(
            message,
            error_code="ROUTING_ERROR",
            context=context,
            **kwargs,
        )


class AgentNotFoundError(OrchestratorError):
    """Raised when a requested agent is not registered."""

    def __init__(self, agent_name: str, **kwargs: Any):
        super().__init__(
            f"Agent '{agent_name}' is not registered with the orchestrator",
            error_code="AGENT_NOT_FOUND",
            context={"agent": agent_name},
            **kwargs,
        )


class CapabilityCheckError(OrchestratorError):
    """Raised when capability checking fails."""

    def __init__(self, agent_name: str, reason: str, **kwargs: Any):
        super().__init__(
            f"Capability check failed for '{agent_name}': {reason}",
            error_code="CAPABILITY_CHECK_ERROR",
            context={"agent": agent_name},
            **kwargs,
        )


# === Graph Execution Exceptions ===


class GraphExecutionError(HiveError):
    """Base exception for graph execution errors."""

    def __init__(
        self,
        message: str,
        node_id: str | None = None,
        graph_id: str | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {})
        if node_id:
            context["node_id"] = node_id
        if graph_id:
            context["graph_id"] = graph_id
        super().__init__(message, context=context, **kwargs)


class NodeExecutionError(GraphExecutionError):
    """Raised when a node fails to execute."""

    def __init__(
        self,
        node_id: str,
        node_name: str,
        reason: str,
        **kwargs: Any,
    ):
        super().__init__(
            f"Node '{node_name}' (id={node_id}) failed: {reason}",
            error_code="NODE_EXECUTION_ERROR",
            node_id=node_id,
            **kwargs,
        )


class MaxIterationsExceededError(GraphExecutionError):
    """Raised when execution exceeds maximum allowed iterations."""

    def __init__(self, max_iterations: int, **kwargs: Any):
        super().__init__(
            f"Execution exceeded maximum iterations ({max_iterations})",
            error_code="MAX_ITERATIONS_EXCEEDED",
            context={"max_iterations": max_iterations},
            **kwargs,
        )


class InvalidGraphError(GraphExecutionError):
    """Raised when a graph spec is invalid."""

    def __init__(self, errors: list[str], **kwargs: Any):
        super().__init__(
            f"Invalid graph: {'; '.join(errors)}",
            error_code="INVALID_GRAPH",
            context={"errors": errors},
            **kwargs,
        )


# === Configuration Exceptions ===


class ConfigurationError(HiveError):
    """Raised for configuration-related errors."""

    def __init__(self, message: str, config_key: str | None = None, **kwargs: Any):
        context = kwargs.pop("context", {})
        if config_key:
            context["config_key"] = config_key
        super().__init__(
            message,
            error_code="CONFIGURATION_ERROR",
            context=context,
            **kwargs,
        )


class MissingCredentialError(ConfigurationError):
    """Raised when a required credential is missing."""

    def __init__(self, credential_name: str, env_var: str, **kwargs: Any):
        # Remove error_code from kwargs if present to avoid conflict
        kwargs.pop("error_code", None)
        super().__init__(
            f"Missing credential '{credential_name}'. Set environment variable: {env_var}",
            config_key=env_var,
            **kwargs,
        )
        # Override the error code after initialization
        self.error_code = "MISSING_CREDENTIAL"
