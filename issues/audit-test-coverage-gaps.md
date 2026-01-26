# Issue: Testing Coverage Gaps in MCP Servers

## Summary

While the core framework logic (graph execution, runtime) appears to have unit tests, the MCP server implementations (`agent_builder_server.py` and `tools/src/mcp_server.py`) have disproportionately low test coverage relative to their complexity and criticality.

## Affected Code

-   **Codebase**: `core/framework/mcp/agent_builder_server.py` (~3000 LOC)
-   **Tests**: `core/tests/test_builder.py` (~300 LOC) and `core/tests/test_mcp_server.py` (~60 LOC)

## Problem

1.  **Critical Logic Untested**: The `agent_builder_server` handles complex state management (sessions, graph validation, file operations) that is not fully covered by existing tests.
2.  **Regression Risk**: Modifications to the builder server (e.g., refactoring input validation) carry high risk of breaking functionality since integration tests are missing.
3.  **Manual Verification**: Relies on manual testing or "Gold Master" testing which is slow and error-prone.

## Root Cause

Focus appears to have been on testing the underlying graph/node logic (`framework.graph`) rather than the MCP API layer that exposes it.

## Proposed Solution

1.  **Add Integration Tests**: Create a test suite that spins up the `FastMCP` server instances and makes calls to them, verifying responses.
2.  **Test Scenarios**:
    -   Create/Load/Delete Session lifecycles.
    -   Invalid input handling (to verify expected error responses).
    -   Graph validation logic (testing edge cases for disconnected graphs, cycles).
3.  **Mocking**: Use `unittest.mock` to mock filesystem operations (`_save_session`) to test server logic without creating disk artifacts.

## Impact

-   **Stability**: Bugs in the "Agent Builder" tools will directly frustrate users trying to create agents, which is the entry point to the system.
-   **Velocity**: Fear of unrelated breaks slows down development on the server components.
