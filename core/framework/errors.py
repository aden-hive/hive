"""Hive Framework Error Hierarchy.

This module provides a structured exception hierarchy for the Hive agent framework.
All framework-specific exceptions inherit from HiveError to enable:
- Consistent error handling across the framework
- Retry logic based on error types
- Proper error categorization and reporting
- Machine-readable error codes

Error Categories:
- GraphError: Graph structure and validation errors
- ExecutionError: Runtime execution failures
- NodeError: Individual node execution failures
- CredentialError: Authentication and secret management errors
- StorageError: State persistence errors
- ToolError: MCP tool execution failures
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorCategory(StrEnum):
    """High-level error categories for classification and metrics."""

    GRAPH = "graph"
    EXECUTION = "execution"
    NODE = "node"
    CREDENTIAL = "credential"
    STORAGE = "storage"
    TOOL = "tool"
    LLM = "llm"
    VALIDATION = "validation"
    TIMEOUT = "timeout"
    PERMISSION = "permission"


class ErrorSeverity(StrEnum):
    """Error severity levels for prioritization."""

    LOW = "low"  # Recoverable, can continue
    MEDIUM = "medium"  # Degraded operation, may retry
    HIGH = "high"  # Critical failure, needs attention
    CRITICAL = "critical"  # System-wide impact, immediate action


@dataclass
class ErrorContext:
    """Structured context for debugging errors."""

    node_id: str | None = None
    graph_id: str | None = None
    session_id: str | None = None
    tool_name: str | None = None
    attempt: int = 1
    max_attempts: int = 3
    metadata: dict[str, Any] = field(default_factory=dict)


class HiveError(Exception):
    """Base exception for all Hive framework errors.

    Provides:
    - Unique error code for programmatic handling
    - Category for metrics and routing
    - Severity for prioritization
    - Retry hint for recovery logic
    - Structured context for debugging

    Example:
        try:
            result = await node.execute(ctx)
        except HiveError as e:
            if e.retry_allowed:
                await retry_execution(e.context)
            else:
                await escalate_to_human(e)
    """

    error_code: str = "HIVE_ERROR"
    category: ErrorCategory = ErrorCategory.EXECUTION
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    retry_allowed: bool = True

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        category: ErrorCategory | None = None,
        severity: ErrorSeverity | None = None,
        retry_allowed: bool | None = None,
        context: ErrorContext | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = error_code
        if category is not None:
            self.category = category
        if severity is not None:
            self.severity = severity
        if retry_allowed is not None:
            self.retry_allowed = retry_allowed
        self.context = context or ErrorContext()
        self.__cause__ = cause

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary for serialization."""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "retry_allowed": self.retry_allowed,
            "context": {
                "node_id": self.context.node_id,
                "graph_id": self.context.graph_id,
                "session_id": self.context.session_id,
                "tool_name": self.context.tool_name,
                "attempt": self.context.attempt,
                "max_attempts": self.context.max_attempts,
                "metadata": self.context.metadata,
            },
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.error_code}, message={self.message!r})"


# =============================================================================
# Graph Errors
# =============================================================================


class GraphError(HiveError):
    """Base exception for graph-related errors."""

    error_code = "GRAPH_ERROR"
    category = ErrorCategory.GRAPH


class GraphValidationError(GraphError):
    """Raised when graph specification is invalid."""

    error_code = "GRAPH_VALIDATION_ERROR"
    severity = ErrorSeverity.HIGH
    retry_allowed = False


class GraphCycleError(GraphError):
    """Raised when graph contains unexpected cycles."""

    error_code = "GRAPH_CYCLE_ERROR"
    severity = ErrorSeverity.HIGH
    retry_allowed = False


class NodeNotFoundError(GraphError):
    """Raised when referenced node doesn't exist in graph."""

    error_code = "NODE_NOT_FOUND"


class EdgeNotFoundError(GraphError):
    """Raised when referenced edge doesn't exist in graph."""

    error_code = "EDGE_NOT_FOUND"


# =============================================================================
# Execution Errors
# =============================================================================


class ExecutionError(HiveError):
    """Base exception for execution-related errors."""

    error_code = "EXECUTION_ERROR"
    category = ErrorCategory.EXECUTION


class MaxStepsExceededError(ExecutionError):
    """Raised when graph exceeds maximum allowed steps."""

    error_code = "MAX_STEPS_EXCEEDED"
    severity = ErrorSeverity.MEDIUM


class MaxRetriesExceededError(ExecutionError):
    """Raised when node exceeds maximum retry attempts."""

    error_code = "MAX_RETRIES_EXCEEDED"
    severity = ErrorSeverity.MEDIUM
    retry_allowed = False


class ParallelExecutionError(ExecutionError):
    """Raised when parallel branch execution fails."""

    error_code = "PARALLEL_EXECUTION_ERROR"


class TimeoutError(ExecutionError):
    """Raised when execution exceeds time limit."""

    error_code = "EXECUTION_TIMEOUT"
    category = ErrorCategory.TIMEOUT


# =============================================================================
# Node Errors
# =============================================================================


class NodeError(HiveError):
    """Base exception for node-related errors."""

    error_code = "NODE_ERROR"
    category = ErrorCategory.NODE


class NodeInputError(NodeError):
    """Raised when node receives invalid input."""

    error_code = "NODE_INPUT_ERROR"
    severity = ErrorSeverity.MEDIUM


class NodeOutputError(NodeError):
    """Raised when node produces invalid output."""

    error_code = "NODE_OUTPUT_ERROR"
    severity = ErrorSeverity.MEDIUM


class MemoryWriteError(NodeError):
    """Raised when an invalid value is written to memory."""

    error_code = "MEMORY_WRITE_ERROR"
    severity = ErrorSeverity.MEDIUM


class MemoryReadError(NodeError):
    """Raised when memory read fails."""

    error_code = "MEMORY_READ_ERROR"


class MemoryPermissionError(NodeError):
    """Raised when node lacks permission to access memory key."""

    error_code = "MEMORY_PERMISSION_ERROR"
    category = ErrorCategory.PERMISSION
    retry_allowed = False


# =============================================================================
# LLM Errors
# =============================================================================


class LLMError(HiveError):
    """Base exception for LLM-related errors."""

    error_code = "LLM_ERROR"
    category = ErrorCategory.LLM


class LLMRateLimitError(LLMError):
    """Raised when LLM rate limit is exceeded."""

    error_code = "LLM_RATE_LIMIT"
    severity = ErrorSeverity.LOW


class LLMTimeoutError(LLMError):
    """Raised when LLM call times out."""

    error_code = "LLM_TIMEOUT"
    category = ErrorCategory.TIMEOUT


class LLMContextLengthError(LLMError):
    """Raised when input exceeds LLM context length."""

    error_code = "LLM_CONTEXT_LENGTH"
    severity = ErrorSeverity.MEDIUM


class LLMOutputParsingError(LLMError):
    """Raised when LLM output cannot be parsed."""

    error_code = "LLM_OUTPUT_PARSING"


# =============================================================================
# Tool Errors
# =============================================================================


class ToolError(HiveError):
    """Base exception for tool-related errors."""

    error_code = "TOOL_ERROR"
    category = ErrorCategory.TOOL


class ToolNotFoundError(ToolError):
    """Raised when referenced tool doesn't exist."""

    error_code = "TOOL_NOT_FOUND"
    retry_allowed = False


class ToolExecutionError(ToolError):
    """Raised when tool execution fails."""

    error_code = "TOOL_EXECUTION_ERROR"


class ToolTimeoutError(ToolError):
    """Raised when tool execution times out."""

    error_code = "TOOL_TIMEOUT"
    category = ErrorCategory.TIMEOUT


class ToolPermissionError(ToolError):
    """Raised when tool lacks required permissions."""

    error_code = "TOOL_PERMISSION_ERROR"
    category = ErrorCategory.PERMISSION
    retry_allowed = False


# =============================================================================
# Credential Errors
# =============================================================================


class CredentialError(HiveError):
    """Base exception for credential-related errors."""

    error_code = "CREDENTIAL_ERROR"
    category = ErrorCategory.CREDENTIAL
    severity = ErrorSeverity.HIGH


class CredentialNotFoundError(CredentialError):
    """Raised when credential doesn't exist."""

    error_code = "CREDENTIAL_NOT_FOUND"
    retry_allowed = False


class CredentialKeyNotFoundError(CredentialError):
    """Raised when credential key doesn't exist within credential."""

    error_code = "CREDENTIAL_KEY_NOT_FOUND"
    retry_allowed = False


class CredentialRefreshError(CredentialError):
    """Raised when credential refresh fails."""

    error_code = "CREDENTIAL_REFRESH_ERROR"


class CredentialValidationError(CredentialError):
    """Raised when credential validation fails."""

    error_code = "CREDENTIAL_VALIDATION_ERROR"
    retry_allowed = False


class CredentialDecryptionError(CredentialError):
    """Raised when credential decryption fails."""

    error_code = "CREDENTIAL_DECRYPTION_ERROR"
    severity = ErrorSeverity.CRITICAL
    retry_allowed = False


# =============================================================================
# Storage Errors
# =============================================================================


class StorageError(HiveError):
    """Base exception for storage-related errors."""

    error_code = "STORAGE_ERROR"
    category = ErrorCategory.STORAGE


class StorageReadError(StorageError):
    """Raised when storage read fails."""

    error_code = "STORAGE_READ_ERROR"


class StorageWriteError(StorageError):
    """Raised when storage write fails."""

    error_code = "STORAGE_WRITE_ERROR"


class StorageConnectionError(StorageError):
    """Raised when storage connection fails."""

    error_code = "STORAGE_CONNECTION_ERROR"
    severity = ErrorSeverity.HIGH


# =============================================================================
# Validation Errors
# =============================================================================


class ValidationError(HiveError):
    """Base exception for validation errors."""

    error_code = "VALIDATION_ERROR"
    category = ErrorCategory.VALIDATION


class SchemaValidationError(ValidationError):
    """Raised when data doesn't match expected schema."""

    error_code = "SCHEMA_VALIDATION_ERROR"


class PydanticValidationError(ValidationError):
    """Raised when Pydantic model validation fails."""

    error_code = "PYDANTIC_VALIDATION_ERROR"

    def __init__(
        self,
        message: str,
        *,
        validation_errors: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.validation_errors = validation_errors or []


__all__ = [
    # Base classes
    "HiveError",
    "ErrorCategory",
    "ErrorSeverity",
    "ErrorContext",
    # Graph errors
    "GraphError",
    "GraphValidationError",
    "GraphCycleError",
    "NodeNotFoundError",
    "EdgeNotFoundError",
    # Execution errors
    "ExecutionError",
    "MaxStepsExceededError",
    "MaxRetriesExceededError",
    "ParallelExecutionError",
    "TimeoutError",
    # Node errors
    "NodeError",
    "NodeInputError",
    "NodeOutputError",
    "MemoryWriteError",
    "MemoryReadError",
    "MemoryPermissionError",
    # LLM errors
    "LLMError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "LLMContextLengthError",
    "LLMOutputParsingError",
    # Tool errors
    "ToolError",
    "ToolNotFoundError",
    "ToolExecutionError",
    "ToolTimeoutError",
    "ToolPermissionError",
    # Credential errors
    "CredentialError",
    "CredentialNotFoundError",
    "CredentialKeyNotFoundError",
    "CredentialRefreshError",
    "CredentialValidationError",
    "CredentialDecryptionError",
    # Storage errors
    "StorageError",
    "StorageReadError",
    "StorageWriteError",
    "StorageConnectionError",
    # Validation errors
    "ValidationError",
    "SchemaValidationError",
    "PydanticValidationError",
]
