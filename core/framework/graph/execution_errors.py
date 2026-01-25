"""
Shared error handling model for graph execution.

This module defines a consistent error handling contract across all executors.
All executors follow this model to ensure predictable failure semantics.

Error Categories:
- RETRIABLE: Transient errors that may succeed on retry (timeouts, rate limits)
- FATAL: Permanent errors that cannot succeed on retry (invalid config, missing tools)
- DEPENDENCY: Error caused by upstream failure (missing input data)
- VALIDATION: Data validation failed (invalid output schema)
- USER: Error caused by user action (rejected approval, modified step)
- RESOURCE: System resource error (memory, disk, sandbox)
- UNKNOWN: Error cause unclear, treat as fatal to avoid silent failures
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import traceback


class ErrorCode(str, Enum):
    """Error codes for execution failures."""
    # Retriable errors
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    
    # Validation errors
    INPUT_VALIDATION_ERROR = "INPUT_VALIDATION_ERROR"
    OUTPUT_VALIDATION_ERROR = "OUTPUT_VALIDATION_ERROR"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    
    # Configuration errors
    MISSING_TOOL = "MISSING_TOOL"
    MISSING_DEPENDENCY = "MISSING_DEPENDENCY"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_NODE_TYPE = "INVALID_NODE_TYPE"
    
    # Execution errors
    EXECUTION_FAILED = "EXECUTION_FAILED"
    NODE_NOT_FOUND = "NODE_NOT_FOUND"
    EDGE_NOT_FOUND = "EDGE_NOT_FOUND"
    MEMORY_ERROR = "MEMORY_ERROR"
    
    # Code execution errors
    SYNTAX_ERROR = "SYNTAX_ERROR"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    SECURITY_ERROR = "SECURITY_ERROR"
    
    # User/Approval errors
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    APPROVAL_ABORTED = "APPROVAL_ABORTED"
    APPROVAL_TIMEOUT = "APPROVAL_TIMEOUT"
    
    # Resource errors
    SANDBOX_ERROR = "SANDBOX_ERROR"
    OUT_OF_MEMORY = "OUT_OF_MEMORY"
    DISK_FULL = "DISK_FULL"
    
    # Unknown/Unclassified
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class ErrorCategory(str, Enum):
    """Error category for determining handling strategy."""
    RETRIABLE = "retriable"       # May succeed on retry
    FATAL = "fatal"               # Won't succeed on retry
    DEPENDENCY = "dependency"     # Blocked by upstream failure
    VALIDATION = "validation"     # Data validation failed
    USER = "user"                 # User action (rejection, etc.)
    RESOURCE = "resource"         # System resource exhausted
    UNKNOWN = "unknown"           # Cannot determine, treat as fatal


@dataclass
class ExecutionError(Exception):
    """
    Base error class for all execution failures.
    
    Provides consistent error reporting across all executors.
    """
    code: ErrorCode
    message: str
    category: ErrorCategory = ErrorCategory.UNKNOWN
    context: dict[str, Any] = field(default_factory=dict)
    original_error: Optional[Exception] = None
    retriable: bool = False
    stacktrace: Optional[str] = None
    
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        context: Optional[dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
        retriable: bool = False,
    ):
        """
        Initialize ExecutionError.
        
        Args:
            code: Error code for categorization
            message: Human-readable error message
            category: Error category for handling strategy
            context: Additional context (node_id, step_id, etc.)
            original_error: The underlying exception that caused this
            retriable: Whether this error might succeed on retry
        """
        self.code = code
        self.message = message
        self.category = category
        self.context = context or {}
        self.original_error = original_error
        self.retriable = retriable
        
        # Capture stack trace if original error exists
        if original_error:
            self.stacktrace = traceback.format_exc()
        
        super().__init__(self.message)
    
    def __str__(self) -> str:
        """Return formatted error message."""
        context_str = ""
        if self.context:
            context_items = ", ".join(f"{k}={v}" for k, v in self.context.items())
            context_str = f" [{context_items}]"
        
        return f"{self.code.value}: {self.message}{context_str}"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "code": self.code.value,
            "message": self.message,
            "category": self.category.value,
            "retriable": self.retriable,
            "context": self.context,
            "original_error": str(self.original_error) if self.original_error else None,
            "stacktrace": self.stacktrace,
        }


class RetriableExecutionError(ExecutionError):
    """Error that might succeed on retry."""
    
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        context: Optional[dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            code=code,
            message=message,
            category=ErrorCategory.RETRIABLE,
            context=context,
            original_error=original_error,
            retriable=True,
        )


class FatalExecutionError(ExecutionError):
    """Error that won't succeed on retry."""
    
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        context: Optional[dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            code=code,
            message=message,
            category=ErrorCategory.FATAL,
            context=context,
            original_error=original_error,
            retriable=False,
        )


class ValidationExecutionError(ExecutionError):
    """Data validation failed."""
    
    def __init__(
        self,
        message: str,
        context: Optional[dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            code=ErrorCode.SCHEMA_MISMATCH,
            message=message,
            category=ErrorCategory.VALIDATION,
            context=context,
            original_error=original_error,
            retriable=False,
        )


class DependencyExecutionError(ExecutionError):
    """Blocked by upstream failure."""
    
    def __init__(
        self,
        message: str,
        context: Optional[dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            code=ErrorCode.MISSING_DEPENDENCY,
            message=message,
            category=ErrorCategory.DEPENDENCY,
            context=context,
            original_error=original_error,
            retriable=False,
        )


class UserExecutionError(ExecutionError):
    """Error caused by user action (e.g., rejected approval)."""
    
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        context: Optional[dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            code=code,
            message=message,
            category=ErrorCategory.USER,
            context=context,
            original_error=original_error,
            retriable=False,
        )


# Error code mappings for classification
CODE_TO_RETRIABLE: dict[ErrorCode, bool] = {
    # Retriable
    ErrorCode.TIMEOUT: True,
    ErrorCode.RATE_LIMIT: True,
    ErrorCode.TRANSIENT_FAILURE: True,
    
    # Non-retriable
    ErrorCode.INPUT_VALIDATION_ERROR: False,
    ErrorCode.OUTPUT_VALIDATION_ERROR: False,
    ErrorCode.SCHEMA_MISMATCH: False,
    ErrorCode.MISSING_TOOL: False,
    ErrorCode.MISSING_DEPENDENCY: False,
    ErrorCode.INVALID_CONFIGURATION: False,
    ErrorCode.INVALID_NODE_TYPE: False,
    ErrorCode.EXECUTION_FAILED: False,
    ErrorCode.NODE_NOT_FOUND: False,
    ErrorCode.EDGE_NOT_FOUND: False,
    ErrorCode.MEMORY_ERROR: False,
    ErrorCode.SYNTAX_ERROR: False,
    ErrorCode.RUNTIME_ERROR: False,
    ErrorCode.SECURITY_ERROR: False,
    ErrorCode.APPROVAL_REJECTED: False,
    ErrorCode.APPROVAL_ABORTED: False,
    ErrorCode.APPROVAL_TIMEOUT: False,
    ErrorCode.SANDBOX_ERROR: False,
    ErrorCode.OUT_OF_MEMORY: False,
    ErrorCode.DISK_FULL: False,
    ErrorCode.UNKNOWN_ERROR: False,
}


def classify_error(
    error: Exception,
    default_code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
) -> ExecutionError:
    """
    Convert any exception into a classified ExecutionError.
    
    Args:
        error: The exception to classify
        default_code: Code to use if classification fails
    
    Returns:
        ExecutionError with appropriate classification
    """
    # If already an ExecutionError, return as-is
    if isinstance(error, ExecutionError):
        return error
    
    # Classify based on exception type
    error_type = type(error).__name__
    message = str(error)
    
    if isinstance(error, TimeoutError):
        code = ErrorCode.TIMEOUT
        category = ErrorCategory.RETRIABLE
        retriable = True
    elif isinstance(error, ValueError):
        code = ErrorCode.INPUT_VALIDATION_ERROR
        category = ErrorCategory.VALIDATION
        retriable = False
    elif isinstance(error, KeyError):
        code = ErrorCode.MISSING_DEPENDENCY
        category = ErrorCategory.DEPENDENCY
        retriable = False
    elif isinstance(error, RuntimeError):
        code = ErrorCode.RUNTIME_ERROR
        category = ErrorCategory.FATAL
        retriable = False
    elif isinstance(error, MemoryError):
        code = ErrorCode.OUT_OF_MEMORY
        category = ErrorCategory.RESOURCE
        retriable = False
    elif isinstance(error, PermissionError):
        code = ErrorCode.SECURITY_ERROR
        category = ErrorCategory.FATAL
        retriable = False
    else:
        code = default_code
        category = ErrorCategory.UNKNOWN
        retriable = CODE_TO_RETRIABLE.get(default_code, False)
    
    return ExecutionError(
        code=code,
        message=f"{error_type}: {message}",
        category=category,
        original_error=error,
        retriable=retriable,
    )
