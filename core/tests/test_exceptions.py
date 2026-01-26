"""Tests for the Hive exception hierarchy.

Run with:
    cd core
    pytest tests/test_exceptions.py -v
"""

import pytest

from framework.exceptions import (
    HiveError,
    LLMError,
    LLMProviderNotAvailableError,
    LLMAPIError,
    LLMResponseParseError,
    RunnerError,
    AgentLoadError,
    AgentValidationError,
    ToolExecutionError,
    MCPServerError,
    OrchestratorError,
    RoutingError,
    AgentNotFoundError,
    CapabilityCheckError,
    GraphExecutionError,
    NodeExecutionError,
    MaxIterationsExceededError,
    InvalidGraphError,
    ConfigurationError,
    MissingCredentialError,
)


class TestHiveErrorBase:
    """Test base HiveError functionality."""

    def test_basic_message(self):
        """Test basic error with just a message."""
        error = HiveError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.message == "Something went wrong"
        assert error.error_code == "HIVE_ERROR"

    def test_with_error_code(self):
        """Test error with custom error code."""
        error = HiveError("Failed", error_code="CUSTOM_CODE")
        assert error.error_code == "CUSTOM_CODE"

    def test_with_context(self):
        """Test error with context dict."""
        error = HiveError("Failed", context={"key": "value", "count": 42})
        assert "key=value" in str(error)
        assert "count=42" in str(error)
        assert error.context == {"key": "value", "count": 42}

    def test_with_original_error(self):
        """Test exception chaining."""
        original = ValueError("original problem")
        error = HiveError("Wrapped error", original_error=original)
        assert error.original_error is original
        assert error.__cause__ is original

    def test_inheritance(self):
        """Test that HiveError inherits from Exception."""
        error = HiveError("test")
        assert isinstance(error, Exception)


class TestLLMExceptions:
    """Test LLM-related exceptions."""

    def test_llm_error_with_provider_and_model(self):
        """Test LLMError with provider and model context."""
        error = LLMError("API failed", provider="anthropic", model="claude-3")
        assert error.context["provider"] == "anthropic"
        assert error.context["model"] == "claude-3"
        assert "API failed" in str(error)

    def test_llm_provider_not_available(self):
        """Test LLMProviderNotAvailableError."""
        error = LLMProviderNotAvailableError("anthropic", "missing API key")
        assert "anthropic" in str(error)
        assert "missing API key" in str(error)
        assert error.error_code == "LLM_PROVIDER_NOT_AVAILABLE"
        assert error.context["provider"] == "anthropic"

    def test_llm_api_error_with_status(self):
        """Test LLMAPIError with status code."""
        error = LLMAPIError("Rate limit exceeded", status_code=429)
        assert error.context["status_code"] == 429
        assert error.error_code == "LLM_API_ERROR"

    def test_llm_response_parse_error(self):
        """Test LLMResponseParseError with truncated response preview."""
        long_response = "this is not json" * 50
        error = LLMResponseParseError(
            "Invalid JSON",
            response_content=long_response,
        )
        # Should truncate long responses
        assert len(error.context["response_preview"]) <= 200
        assert error.error_code == "LLM_RESPONSE_PARSE_ERROR"


class TestRunnerExceptions:
    """Test runner-related exceptions."""

    def test_runner_error_with_agent_name(self):
        """Test RunnerError with agent name context."""
        error = RunnerError("Runner failed", agent_name="my-agent")
        assert error.context["agent"] == "my-agent"

    def test_agent_load_error(self):
        """Test AgentLoadError."""
        error = AgentLoadError("/path/to/agent", "file not found")
        assert "/path/to/agent" in str(error)
        assert "file not found" in str(error)
        assert error.error_code == "AGENT_LOAD_ERROR"

    def test_agent_validation_error(self):
        """Test AgentValidationError with errors and missing tools."""
        error = AgentValidationError(
            "Validation failed",
            errors=["No entry node", "Cycle detected"],
            missing_tools=["send_email", "read_file"],
        )
        assert error.context["errors"] == ["No entry node", "Cycle detected"]
        assert error.context["missing_tools"] == ["send_email", "read_file"]
        assert error.error_code == "AGENT_VALIDATION_ERROR"

    def test_tool_execution_error(self):
        """Test ToolExecutionError."""
        error = ToolExecutionError(
            "send_email",
            "SMTP connection failed",
            tool_input={"to": "test@example.com"},
        )
        assert "send_email" in str(error)
        assert error.context["tool"] == "send_email"
        assert error.context["input"] == {"to": "test@example.com"}
        assert error.error_code == "TOOL_EXECUTION_ERROR"

    def test_mcp_server_error(self):
        """Test MCPServerError."""
        error = MCPServerError("tools-server", "Connection refused")
        assert "tools-server" in str(error)
        assert error.context["server"] == "tools-server"
        assert error.error_code == "MCP_SERVER_ERROR"


class TestOrchestratorExceptions:
    """Test orchestrator-related exceptions."""

    def test_orchestrator_error_inheritance(self):
        """Test OrchestratorError inherits from HiveError."""
        error = OrchestratorError("Orchestrator failed")
        assert isinstance(error, HiveError)

    def test_routing_error(self):
        """Test RoutingError with available agents."""
        error = RoutingError(
            "No capable agents",
            available_agents=["agent_a", "agent_b"],
        )
        assert error.context["available_agents"] == ["agent_a", "agent_b"]
        assert error.error_code == "ROUTING_ERROR"

    def test_agent_not_found(self):
        """Test AgentNotFoundError."""
        error = AgentNotFoundError("missing_agent")
        assert "missing_agent" in str(error)
        assert error.error_code == "AGENT_NOT_FOUND"
        assert error.context["agent"] == "missing_agent"

    def test_capability_check_error(self):
        """Test CapabilityCheckError."""
        error = CapabilityCheckError("agent_x", "LLM timeout")
        assert "agent_x" in str(error)
        assert "LLM timeout" in str(error)
        assert error.error_code == "CAPABILITY_CHECK_ERROR"


class TestGraphExceptions:
    """Test graph execution exceptions."""

    def test_graph_execution_error_with_ids(self):
        """Test GraphExecutionError with node and graph IDs."""
        error = GraphExecutionError(
            "Execution failed",
            node_id="node_123",
            graph_id="graph_456",
        )
        assert error.context["node_id"] == "node_123"
        assert error.context["graph_id"] == "graph_456"

    def test_node_execution_error(self):
        """Test NodeExecutionError."""
        error = NodeExecutionError(
            node_id="node_123",
            node_name="ProcessData",
            reason="timeout after 30s",
        )
        assert "ProcessData" in str(error)
        assert "node_123" in str(error)
        assert error.context["node_id"] == "node_123"
        assert error.error_code == "NODE_EXECUTION_ERROR"

    def test_max_iterations_exceeded(self):
        """Test MaxIterationsExceededError."""
        error = MaxIterationsExceededError(100)
        assert "100" in str(error)
        assert error.context["max_iterations"] == 100
        assert error.error_code == "MAX_ITERATIONS_EXCEEDED"

    def test_invalid_graph_error(self):
        """Test InvalidGraphError."""
        error = InvalidGraphError(["No entry node", "Cycle detected"])
        assert "No entry node" in str(error)
        assert "Cycle detected" in str(error)
        assert error.context["errors"] == ["No entry node", "Cycle detected"]
        assert error.error_code == "INVALID_GRAPH"


class TestConfigurationExceptions:
    """Test configuration-related exceptions."""

    def test_configuration_error(self):
        """Test ConfigurationError."""
        error = ConfigurationError("Invalid config", config_key="api_url")
        assert error.context["config_key"] == "api_url"
        assert error.error_code == "CONFIGURATION_ERROR"

    def test_missing_credential_error(self):
        """Test MissingCredentialError."""
        error = MissingCredentialError("anthropic", "ANTHROPIC_API_KEY")
        assert "anthropic" in str(error)
        assert "ANTHROPIC_API_KEY" in str(error)
        assert error.error_code == "MISSING_CREDENTIAL"
        assert error.context["config_key"] == "ANTHROPIC_API_KEY"


class TestExceptionChaining:
    """Test exception chaining behavior."""

    def test_preserves_traceback(self):
        """Test that exception chaining preserves traceback."""
        try:
            try:
                raise ValueError("original")
            except ValueError as e:
                raise LLMAPIError("wrapped", original_error=e) from e
        except LLMAPIError as e:
            assert e.__cause__ is not None
            assert isinstance(e.__cause__, ValueError)

    def test_chained_exception_is_accessible(self):
        """Test that original error is accessible via attribute."""
        original = KeyError("missing_key")
        error = HiveError("Wrapped", original_error=original)
        assert error.original_error is original


class TestExceptionHierarchy:
    """Test the exception class hierarchy."""

    def test_llm_errors_inherit_from_hive_error(self):
        """Test that all LLM exceptions inherit from HiveError."""
        assert issubclass(LLMError, HiveError)
        assert issubclass(LLMProviderNotAvailableError, LLMError)
        assert issubclass(LLMAPIError, LLMError)
        assert issubclass(LLMResponseParseError, LLMError)

    def test_runner_errors_inherit_from_hive_error(self):
        """Test that all runner exceptions inherit from HiveError."""
        assert issubclass(RunnerError, HiveError)
        assert issubclass(AgentLoadError, RunnerError)
        assert issubclass(AgentValidationError, RunnerError)
        assert issubclass(ToolExecutionError, RunnerError)
        assert issubclass(MCPServerError, RunnerError)

    def test_orchestrator_errors_inherit_from_hive_error(self):
        """Test that all orchestrator exceptions inherit from HiveError."""
        assert issubclass(OrchestratorError, HiveError)
        assert issubclass(RoutingError, OrchestratorError)
        assert issubclass(AgentNotFoundError, OrchestratorError)
        assert issubclass(CapabilityCheckError, OrchestratorError)

    def test_graph_errors_inherit_from_hive_error(self):
        """Test that all graph exceptions inherit from HiveError."""
        assert issubclass(GraphExecutionError, HiveError)
        assert issubclass(NodeExecutionError, GraphExecutionError)
        assert issubclass(MaxIterationsExceededError, GraphExecutionError)
        assert issubclass(InvalidGraphError, GraphExecutionError)

    def test_config_errors_inherit_from_hive_error(self):
        """Test that all config exceptions inherit from HiveError."""
        assert issubclass(ConfigurationError, HiveError)
        assert issubclass(MissingCredentialError, ConfigurationError)

    def test_all_exceptions_can_be_caught_as_exception(self):
        """Test that all custom exceptions can be caught as base Exception."""
        exceptions = [
            HiveError("test"),
            LLMError("test"),
            LLMProviderNotAvailableError("provider", "reason"),
            RunnerError("test"),
            OrchestratorError("test"),
            GraphExecutionError("test"),
            ConfigurationError("test"),
        ]

        for exc in exceptions:
            try:
                raise exc
            except Exception as e:
                assert e is exc
