"""
Goal-Based Testing Framework

A three-stage framework (Goal → Agent → Eval) where tests are LLM-generated
from success_criteria and constraints, with mandatory user approval.

## Core Flow

1. **Goal Stage**: Define success_criteria and constraints, generate constraint tests
2. **Agent Stage**: Build nodes + edges, run constraint tests during development
3. **Eval Stage**: Generate success_criteria tests, run all tests, debug failures

## Key Components

- **Schemas**: Test, TestResult, TestSuiteResult, ApprovalStatus, ErrorCategory
- **Storage**: TestStorage for persisting tests and results
- **Generation**: LLM-based test generation from Goal criteria
- **Approval**: Mandatory user approval workflow (CLI and programmatic)
- **Runner**: Parallel test execution with pytest-xdist inspired design
- **Debug**: Error categorization and fix suggestions

## MCP Tools

Testing tools are integrated into the main agent_builder_server.py (not a separate server).
This ensures the building_agent skill has access to all testing functionality:
- generate_constraint_tests, generate_success_tests
- approve_tests, run_tests, debug_test
- list_tests, get_pending_tests

## Usage

```python
from framework.testing import (
    Test, TestResult, TestStorage,
    ConstraintTestGenerator, SuccessCriteriaTestGenerator,
    ParallelTestRunner, DebugTool,
)

# Generate tests
generator = ConstraintTestGenerator(llm)
tests = generator.generate(goal)

# Approve tests (required)
for test in tests:
    test.approve("user")
    storage.save_test(test)

# Run tests
runner = ParallelTestRunner()
result = runner.run_all(goal_id, agent_factory, tests)

# Debug failures
debug = DebugTool(storage)
info = debug.analyze(goal_id, test_id)
```

## CLI Commands

```bash
python -m framework test-generate goal.json
python -m framework test-approve <goal_id>
python -m framework test-run <agent_path> --goal <goal_id>
python -m framework test-debug <goal_id> <test_id>
```
"""

# Schemas
from framework.testing.test_case import (
    ApprovalStatus,
    TestType,
    Test,
)
from framework.testing.test_result import (
    ErrorCategory,
    TestResult,
    TestSuiteResult,
)

# Storage
from framework.testing.test_storage import TestStorage

# Generation
from framework.testing.constraint_gen import ConstraintTestGenerator
from framework.testing.success_gen import SuccessCriteriaTestGenerator
from framework.testing.prompts import (
    CONSTRAINT_TEST_PROMPT,
    SUCCESS_CRITERIA_TEST_PROMPT,
)

# Approval
from framework.testing.approval_types import (
    ApprovalAction,
    ApprovalRequest,
    ApprovalResult,
    BatchApprovalRequest,
    BatchApprovalResult,
)
from framework.testing.approval_cli import interactive_approval, batch_approval

# Runner
from framework.testing.executor import TestExecutor
from framework.testing.parallel import ParallelTestRunner, ParallelConfig
from framework.testing.categorizer import ErrorCategorizer

# Debug
from framework.testing.debug_tool import DebugTool, DebugInfo

# CLI
from framework.testing.cli import register_testing_commands

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
    # Generation
    "ConstraintTestGenerator",
    "SuccessCriteriaTestGenerator",
    "CONSTRAINT_TEST_PROMPT",
    "SUCCESS_CRITERIA_TEST_PROMPT",
    # Approval
    "ApprovalAction",
    "ApprovalRequest",
    "ApprovalResult",
    "BatchApprovalRequest",
    "BatchApprovalResult",
    "interactive_approval",
    "batch_approval",
    # Runner
    "TestExecutor",
    "ParallelTestRunner",
    "ParallelConfig",
    "ErrorCategorizer",
    # Debug
    "DebugTool",
    "DebugInfo",
    # CLI
    "register_testing_commands",
]
