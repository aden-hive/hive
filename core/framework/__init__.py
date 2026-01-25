"""
Aden Hive Framework: A high-performance goal-driven agent runtime.

Version 0.2.0 - Performance optimized with async execution.

The runtime is designed around DECISIONS, not just actions. Every significant
choice the agent makes is captured with:
- What it was trying to do (intent)
- What options it considered
- What it chose and why
- What happened as a result
- Whether that was good or bad (evaluated post-hoc)

This gives the Builder LLM the information it needs to improve agent behavior.

## Key Performance Features (v0.2.0)

- **Async Storage**: AsyncFileStorage, RedisStorage, PostgresStorage
- **Caching**: Multi-level L1 (memory) + L2 (Redis) caching
- **Resilience**: Rate limiting, circuit breakers, retry logic
- **Parallel Execution**: ParallelGraphExecutor for independent nodes
- **Fast JSON**: 30x faster JSON extraction with orjson

## Testing Framework

The framework includes a Goal-Based Testing system (Goal → Agent → Eval):
- Generate tests from Goal success_criteria and constraints
- Mandatory user approval before tests are stored
- Parallel test execution with error categorization
- Debug tools with fix suggestions

See `framework.testing` for details.
"""

from framework.schemas.decision import Decision, Option, Outcome, DecisionEvaluation
from framework.schemas.run import Run, RunSummary, Problem
from framework.runtime.core import Runtime
from framework.builder.query import BuilderQuery
from framework.llm import LLMProvider, AnthropicProvider, AsyncLiteLLMProvider
from framework.runner import AgentRunner, AgentOrchestrator
from framework.graph import ParallelGraphExecutor, ParallelExecutionResult

# Performance modules
from framework.cache import AgentCache, CachedLLMProvider, get_cache
from framework.resilience import RateLimiter, CircuitBreaker, CircuitOpenError, retry_async
from framework.logging_config import (
    configure_logging,
    get_logger,
    LogContext,
    AgentExecutionLogger,
    init_logging,
)
from framework.storage import (
    AsyncFileStorage,
    RedisStorage,
    PostgresStorage,
    StorageFactory,
)

# Testing framework
from framework.testing import (
    Test,
    TestResult,
    TestSuiteResult,
    TestStorage,
    ApprovalStatus,
    ErrorCategory,
    DebugTool,
)

__version__ = "0.2.0"

__all__ = [
    # Version
    "__version__",
    # Schemas
    "Decision",
    "Option",
    "Outcome",
    "DecisionEvaluation",
    "Run",
    "RunSummary",
    "Problem",
    # Runtime
    "Runtime",
    # Builder
    "BuilderQuery",
    # LLM
    "LLMProvider",
    "AnthropicProvider",
    "AsyncLiteLLMProvider",
    # Runner
    "AgentRunner",
    "AgentOrchestrator",
    # Parallel Execution
    "ParallelGraphExecutor",
    "ParallelExecutionResult",
    # Caching
    "AgentCache",
    "CachedLLMProvider",
    "get_cache",
    # Resilience
    "RateLimiter",
    "CircuitBreaker",
    "CircuitOpenError",
    "retry_async",
    # Logging
    "configure_logging",
    "get_logger",
    "LogContext",
    "AgentExecutionLogger",
    "init_logging",
    # Storage
    "AsyncFileStorage",
    "RedisStorage",
    "PostgresStorage",
    "StorageFactory",
    # Testing
    "Test",
    "TestResult",
    "TestSuiteResult",
    "TestStorage",
    "ApprovalStatus",
    "ErrorCategory",
    "DebugTool",
]

