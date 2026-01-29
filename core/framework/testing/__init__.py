"""
Goal-Based Testing Framework

A framework where tests are written based on success_criteria and constraints,
then run with pytest and debugged with LLM assistance.

## Core Flow

1. **Goal Stage**: Define success_criteria and constraints
2. **Agent Stage**: Build nodes + edges, write tests
3. **Eval Stage**: Run tests, debug failures

## Key Components

- **Schemas**: Test, TestResult, TestSuiteResult, ApprovalStatus, ErrorCategory
- **Storage**: TestStorage for persisting tests and results
- **Runner**: Test execution via pytest subprocess with pytest-xdist parallelization
- **Debug**: Error categorization and fix suggestions

## MCP Tools

Testing tools are integrated into the main agent_builder_server.py:
- generate_constraint_tests, generate_success_tests (return guidelines)
- run_tests, debug_test, list_tests

## CLI Commands

```bash
python -m framework test-run <agent_path> --goal <goal_id>
python -m framework test-debug <goal_id> <test_id>
python -m framework test-list <agent_path> --goal <goal_id>
```
"""

# Schemas
from framework.testing.approval_cli import batch_approval, interactive_approval

# Approval
from framework.testing.approval_types import (
    ApprovalAction,
    ApprovalRequest,
    ApprovalResult,
    BatchApprovalRequest,
    BatchApprovalResult,
)

# Error categorization
from framework.testing.categorizer import ErrorCategorizer

# CLI
from framework.testing.cli import register_testing_commands

# Debug
from framework.testing.debug_tool import DebugInfo, DebugTool

# LLM Judge for semantic evaluation
from framework.testing.llm_judge import LLMJudge
from framework.testing.test_case import (
    ApprovalStatus,
    Test,
    TestType,
)
from framework.testing.test_result import (
    ErrorCategory,
    TestResult,
    TestSuiteResult,
)

# Storage
from framework.testing.test_storage import TestStorage

__all__ = [
    # Schemas
    "ApprovalStatus",
    "TestType",
    "Test",
    "ErrorCategory",
    "TestResult",
    "TestSuiteResult",
    # Storage
    "TestStorage",
    # Approval types (pure types, no LLM)
    "ApprovalAction",
    "ApprovalRequest",
    "ApprovalResult",
    "BatchApprovalRequest",
    "BatchApprovalResult",
    "interactive_approval",
    "batch_approval",
    # Error categorization
    "ErrorCategorizer",
    # LLM Judge
    "LLMJudge",
    # Debug
    "DebugTool",
    "DebugInfo",
    # CLI
    "register_testing_commands",
]
