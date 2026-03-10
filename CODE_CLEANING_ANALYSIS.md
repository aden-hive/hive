# Code Cleaning Analysis — Hive Framework
**Date:** 2026-03-09
**Scope:** Full codebase audit relative to active entrypoints (`hive open`, `quickstart.sh`)
**Methodology:** Static import tracing, call-site analysis, cross-referencing across all Python modules

---

## Executive Summary

This report identifies code in the Hive framework that is dead, unused, placeholder-only, or structurally isolated from the active execution paths. The active entrypoints are `hive open` (which launches the browser-based server at `core/framework/server/`) and `quickstart.sh`/`quickstart.ps1` (the onboarding wizard). All analysis is verified against actual import graphs — no guesswork.

Findings are grouped into three tiers:

- **Tier 1 — Dead Code:** Not imported or called by anything in the codebase.
- **Tier 2 — Placeholder Stubs:** Registered in the CLI but return `1` with "not yet implemented."
- **Tier 3 — Structural Concerns:** Code that works but represents problematic coupling, migration debt, or deprecated patterns still embedded in active paths.

---

## Tier 1 — Dead Code

### 1.1 `framework/graph/hitl.py` (203 lines)

**Status:** Zero external imports. Completely unused.

**What it is:** A formal data-model module defining a HITL (Human-In-The-Loop) protocol:
```python
class HITLInputType(StrEnum): ...
class HITLQuestion: ...
class HITLRequest: ...
class HITLResponse: ...
class HITLSession: ...
```
**Why it's dead:** The HITL concept is alive in the codebase — agents pause at `pause_nodes` defined in `EdgeSpec`, the `GraphExecutor` checks `node_spec.id in graph.pause_nodes`, and the shell command implements an approval callback (`_hitl_approval`). However, none of this machinery uses the types from `hitl.py`. The actual pause/resume flow uses ad-hoc dicts and the executor's internal state, not these dataclasses.

**Verification:**
```
$ grep -rn "from framework.graph.hitl\|import hitl\|HITLRequest\|HITLQuestion\|HITLSession" core/ --include="*.py"
(no results outside hitl.py itself)
```

**Recommendation:** Delete `core/framework/graph/hitl.py`. The concept it formalized was never adopted by the implementation.

---

### 1.2 `framework/storage/state_writer.py` (179 lines)

**Status:** Zero external imports. Self-described migration artifact.

**What it is:** A "dual-write adapter for migration period" that conditionally writes to both the old `Run`-based storage format and the new `SessionState`-based format via an env var gate:
```python
class StateWriter:
    """
    Writes execution state to both old and new formats during migration.
    During the dual-write phase:
    - New format (state.json) is written when USE_UNIFIED_SESSIONS=true
    - Old format (Run/RunSummary) is always written for backward compatibility
    """
    self.dual_write_enabled = os.getenv("USE_UNIFIED_SESSIONS", "false").lower() == "true"
```

**Why it's dead:** The migration is effectively complete. `AgentRuntime` initializes a `SessionStore` directly (always enabled, no env var check), and `ExecutionStream` now writes to `SessionStore` by default. `StateWriter` is never imported — not by `AgentRuntime`, not by `ExecutionStream`, not by `runner.py`. The class exists in isolation.

**Verification:**
```
$ grep -rn "StateWriter\|state_writer\|USE_UNIFIED_SESSIONS" core/ --include="*.py"
framework/storage/state_writer.py:20:class StateWriter:      # ← definition
framework/storage/state_writer.py:39:    ...USE_UNIFIED_SESSIONS...  # ← internal reference only
```

**Recommendation:** Delete `core/framework/storage/state_writer.py`. The migration is over; the old format path in `ConcurrentStorage` (`save_run`/`load_run`) is the remaining debt, not this class.

---

### 1.3 `framework/server/agent_manager.py` (36 lines)

**Status:** Zero external imports. Explicit backward-compat shim with no callers.

**What it is:** A two-line shim that re-exports `SessionManager` as `AgentManager` and provides a legacy `AgentSlot` dataclass described as "kept for test compatibility only":
```python
"""Backward-compatibility shim.
The primary implementation is now in ``session_manager.py``.
This module re-exports SessionManager as AgentManager and
keeps AgentSlot for test compatibility.
"""
AgentManager = SessionManager
```

**Why it's dead:** No file in the codebase imports from `framework.server.agent_manager`. The tests that supposedly needed `AgentSlot` don't import it either.

**Verification:**
```
$ grep -rn "from framework.server.agent_manager\|AgentManager\|AgentSlot" core/ --include="*.py"
framework/server/agent_manager.py:4:...re-exports SessionManager as AgentManager...  # definition only
framework/server/agent_manager.py:36:AgentManager = SessionManager                   # definition only
```

**Recommendation:** Delete `core/framework/server/agent_manager.py`. `SessionManager` is already imported directly everywhere it's needed.

---

### 1.4 `framework/agents/hive_coder/` (directory with only `__pycache__`)

**Status:** Source files deleted. Only stale bytecode (`.pyc`) remains.

**What it is:** A directory at `core/framework/agents/hive_coder/` that once contained an agent. The source Python files (`.py`) no longer exist — only the compiled bytecode artifacts remain:
```
core/framework/agents/hive_coder/
├── __pycache__/
│   ├── agent.cpython-311.pyc
│   ├── agent.cpython-314.pyc
│   ├── config.cpython-311.pyc
│   ├── ticket_receiver.cpython-311.pyc
│   └── ...
├── nodes/__pycache__/
│   ├── __init__.cpython-311.pyc
│   └── ...
└── tests/__pycache__/
```
No `.py` files exist in any of these subdirectories.

**Why it's a problem:** The directory creates a misleading impression that an agent exists here. Python's import resolution can find `__pycache__` entries without source, causing intermittent import surprises. Nothing in the live codebase references this module.

**Verification:**
```
$ find core/framework/agents/hive_coder -name "*.py"
(no results)
$ grep -rn "hive_coder\|HiveCoder" core/ --include="*.py"
(no results)
```

**Recommendation:** Delete the entire `core/framework/agents/hive_coder/` directory tree.

---

### 1.5 `framework/builder/` — `BuilderQuery` class (501 lines)

**Status:** Exported in `framework/__init__.py` but never imported or called by any external code.

**What it is:** An introspection API for querying execution runs, failures, and decision patterns:
```python
class BuilderQuery:
    def get_run_summary(self, run_id: str) -> RunSummary | None: ...
    def list_runs_for_goal(self, goal_id: str) -> list[RunSummary]: ...
    def get_recent_failures(self, limit: int = 10) -> list[RunSummary]: ...
    def analyze_failure(self, run_id: str) -> FailureAnalysis | None: ...
    def get_success_rate(self, goal_id: str) -> float: ...
```

**Why it's dead:** `BuilderQuery` is imported and listed in `__all__` in `framework/__init__.py` as a public API, but no code outside the `builder/` directory ever imports it — not the server, not the CLI, not any agent, not any test.

**Verification:**
```
$ grep -rn "BuilderQuery" core/ --include="*.py" | grep -v "builder/"
framework/__init__.py:25:from framework.builder.query import BuilderQuery  # export only
framework/__init__.py:55:    "BuilderQuery",                                # __all__ only
```

**Recommendation:** Either (a) delete `core/framework/builder/` and remove its export from `framework/__init__.py`, or (b) if it is intended as a future public API, leave it but remove it from `__all__` until it has actual callers.

---

### 1.6 `framework/mcp/__init__.py` (4 lines)

**Status:** Empty module, never imported for substance.

**What it is:**
```python
"""MCP servers for worker-bee."""
# Don't auto-import servers to avoid double-import issues when running with -m
__all__ = []
```

**Why it's a concern:** The `framework/mcp/` directory exists as a Python package but contains only this empty `__init__.py`. The actual MCP client implementation lives in `framework/runner/mcp_client.py`. No code imports `framework.mcp` for functionality — only `framework.runner.mcp_client`, `framework.runner.tool_registry`, and `framework.tools.*` handle MCP.

**Recommendation:** Delete `core/framework/mcp/` entirely, or if a future MCP namespace is intended here, leave a `# TODO` comment.

---

### 1.7 `framework/credentials/vault/` — HashiCorp Vault backend (394 lines)

**Status:** Implemented but never loaded by any active code path.

**What it is:** A `HashiCorpVaultStorage` class that wraps the `hvac` library for enterprise secret management:
```python
class HashiCorpVaultStorage(CredentialStorage):
    """HashiCorp Vault storage adapter.
    Provides integration with HashiCorp Vault for enterprise secret management."""
```

**Why it's dead:** The `credentials/__init__.py` docstring mentions it, but no code in `store.py`, `setup.py`, `runner.py`, or the server routes imports `HashiCorpVaultStorage`. The `CredentialStore` in active use is initialized via `with_encrypted_storage()`, which uses the local file-based backend exclusively.

**Verification:**
```
$ grep -rn "from framework.credentials.vault\|HashiCorpVaultStorage" core/ --include="*.py"
credentials/__init__.py:42:    from core.framework.credentials.vault import HashiCorpVaultStorage  # docstring example only
credentials/vault/hashicorp.py:23:class HashiCorpVaultStorage(CredentialStorage):                     # definition only
```

**Recommendation:** If Vault integration is not planned in the near term, delete `core/framework/credentials/vault/`. If it is planned, add an integration test and a `TODO` issue reference.

---

## Tier 2 — Placeholder Stubs (CLI Commands That Don't Work)

The following CLI subcommands are registered in `register_commands()` (`runner/cli.py`), appear in `--help` output, but their implementations return exit code `1` with "not yet implemented" messages. Users invoking these commands get errors.

### 2.1 `hive sessions list` / `hive sessions show` / `hive sessions checkpoints`

```python
def cmd_sessions_list(args: argparse.Namespace) -> int:
    """List agent sessions."""
    print("⚠ Sessions list command not yet implemented")
    print("This will be available once checkpoint infrastructure is complete.")
    return 1

def cmd_sessions_show(args: argparse.Namespace) -> int:
    """Show detailed session information."""
    print("⚠ Session show command not yet implemented")
    print("This will be available once checkpoint infrastructure is complete.")
    return 1

def cmd_sessions_checkpoints(args: argparse.Namespace) -> int:
    """List checkpoints for a session."""
    print("⚠ Session checkpoints command not yet implemented")
    print("This will be available once checkpoint infrastructure is complete.")
    return 1
```

**Why this matters:** The session/checkpoint infrastructure IS complete — `SessionStore`, `CheckpointStore`, and the server's `/api/sessions/*` routes all work. These CLI commands were written as stubs expecting infrastructure that has since been built, but the commands were never wired up to that infrastructure. They are dead stubs that mislead users.

**Recommendation:** Either implement these commands by calling `SessionStore` directly, or remove the subcommand registrations and their functions until implementation is ready.

---

### 2.2 `hive pause` / `hive resume` (CLI)

```python
def cmd_pause(args: argparse.Namespace) -> int:
    """Pause a running session."""
    print("⚠ Pause command not yet implemented")
    print("This will be available once executor pause integration is complete.")
    return 1

def cmd_resume(args: argparse.Namespace) -> int:
    """Resume a session from checkpoint."""
    print("⚠ Resume command not yet implemented")
    print("This will be available once checkpoint resume integration is complete.")
    return 1
```

**Why this matters:** Resume functionality is actually implemented — `cmd_run` supports `--resume-session` and `--checkpoint` flags that call `_load_resume_state()` and restore from checkpoints. The pause mechanism (via `SIGTERM` handling in `AgentRuntime`) also exists. These `hive pause` / `hive resume` stubs duplicate planned functionality that `hive run --resume-session` already provides.

**Recommendation:** Remove the stub registrations and their parser definitions from `runner/cli.py`, or implement them using the existing `_load_resume_state()` infrastructure.

---

## Tier 3 — Structural Concerns

### 3.1 TUI Module Coupled to Active Server (`routes_sessions.py`)

**Context:** CLAUDE.md declares the TUI deprecated: *"TUI is deprecated. The terminal UI (`hive tui`) is no longer maintained. Use the browser-based interface (`hive open`) instead."*

**The concern:** Despite this, the active HTTP server imports directly from the TUI module:
```python
# core/framework/server/routes_sessions.py, line 734
async def handle_discover(request: web.Request) -> web.Response:
    """GET /api/discover — discover agents from filesystem."""
    from framework.tui.screens.agent_picker import discover_agents
    groups = discover_agents()
```

The `discover_agents()` function (from `tui/screens/agent_picker.py`) is a general-purpose filesystem scanner that returns categorized agent entries. It has no terminal UI logic in it — the name and module path are misleading. As a result, the "deprecated" TUI module is a runtime dependency of the active `hive open` server path. Removing the TUI would break the `/api/discover` endpoint that the React frontend uses to list available agents.

**Recommendation:** Extract `discover_agents()` into a location appropriate for its actual role — either `framework/runner/runner.py` or a new `framework/agents/discovery.py`. This decouples the server from the TUI and allows the TUI to be cleanly removed or maintained independently.

---

### 3.2 Legacy `Runtime` Class Still Embedded in Core Execution Path

**Context:** `framework/runtime/core.py` contains the original `Runtime` class, which writes decisions and run metadata to the old `FileStorage`-based format (`save_run`, `load_run`, `summaries/`). A newer `AgentRuntime` + `SessionStore` + `ExecutionStream` architecture has replaced this for the server-based flow.

**The concern:** Despite the newer architecture, the old `Runtime` is still instantiated and called in the primary execution path:
```python
# framework/graph/executor.py — called for every agent execution
_run_id = self.runtime.start_run(goal_id, ...)  # line 692
self.runtime.end_run(success=True, ...)          # lines 1089, 1163, 1515, 1632
```

This means every agent execution writes to two places: the new `SessionStore` (via `ExecutionStream`) and the old file format (via `Runtime.start_run`/`end_run`). The `BuilderQuery` class was designed to read from this old format, but since `BuilderQuery` has no callers (Tier 1, item 1.5), the old format data is written but never read by anything other than tests.

**Affected files:**
- `framework/runtime/core.py` — the `Runtime` class itself
- `framework/graph/executor.py` — calls `runtime.start_run`/`end_run`
- `framework/storage/backend.py` — `FileStorage.save_run`/`load_run`
- `framework/storage/concurrent.py` — `ConcurrentStorage.save_run`/`load_run`
- `framework/schemas/run.py` — `Run`, `RunSummary` schemas
- `framework/__init__.py` — exports `Run`, `RunSummary` (public API)

**Recommendation:** Before removing, confirm whether `Run`/`RunSummary`/`Runtime` are part of the external public API (i.e., exported agents import from `framework`). If not, create a migration plan to remove the dual-write path. The `BuilderQuery` removal (Tier 1, item 1.5) should happen first.

---

### 3.3 `hive dispatch` Command and `AgentOrchestrator` — Orphaned CLI Orchestration

**Context:** `hive dispatch` uses `AgentOrchestrator` (`framework/runner/orchestrator.py`) to route requests across multiple agents using an LLM router. This is a CLI-only multi-agent orchestration pattern that predates the server's Queen-based orchestration.

**The concern:** The server's primary multi-agent flow goes through `queen_orchestrator.py` → `SessionManager` → Queen agent. The `AgentOrchestrator` class provides different behavior (capability-based routing, capability negotiation via `CapabilityResponse`, message relay protocol in `runner/protocol.py`). The two patterns are architecturally distinct and neither references the other.

`AgentOrchestrator` is also used in `hive shell --multi` (line 1674 in `cli.py`). This is functional but represents an older orchestration pattern now superseded by the server's approach.

**Files involved:**
- `framework/runner/orchestrator.py` — `AgentOrchestrator` class
- `framework/runner/protocol.py` — `AgentMessage`, `CapabilityLevel`, `CapabilityResponse`, `MessageType`, `OrchestratorResult`
- `framework/runner/cli.py` — `cmd_dispatch`, `hive shell --multi`

**Recommendation:** Clarify whether `hive dispatch` / `AgentOrchestrator` is intended to remain as a CLI alternative to the server's Queen orchestration, or if it should be removed in favor of directing users to `hive open`. If the latter, remove `cmd_dispatch`, `AgentOrchestrator`, and `runner/protocol.py`.

---

### 3.4 Codex Subscription Code Path — Active but Narrowly Used

**Context:** The quickstart wizard offers "OpenAI Codex Subscription" as option 3 of 4 LLM providers. When selected, it invokes `core/codex_oauth.py` for OAuth, sets `use_codex_subscription: true` in the agent config, and routes through `get_codex_token()` / `get_codex_account_id()` in `runner.py`.

**The concern:** This is a functional code path (not dead), but it is:
1. Tightly coupled to specific OpenAI Codex OAuth endpoints and client IDs that are hardcoded in `codex_oauth.py`
2. Uses the Codex-specific `gpt-5.3-codex` model name hardcoded in `quickstart.sh`
3. No exported agents in `exports/` use `use_codex_subscription`, suggesting this is mostly a setup-time concern

This is not dead code — it is a supported configuration path — but it represents a narrow, externally-coupled feature that may require maintenance if OpenAI changes their OAuth endpoints.

**Files involved:**
- `core/codex_oauth.py` (standalone script)
- `core/framework/runner/runner.py` — `get_codex_token()`, `_is_codex_token_expired()`, `_refresh_codex_token()`, `get_codex_account_id()`
- `core/framework/config.py` — `use_codex_subscription` branch in `get_api_key()`, `get_api_base()`, `get_extra_headers()`

**Recommendation:** No immediate action, but document that this path requires maintenance if Codex OAuth endpoints change. Consider adding an integration test.

---

### 3.5 `framework/__init__.py` Public API Surface — Exports That Have No External Consumers

The framework's top-level `__init__.py` exports several items that are either dead (no external callers) or internal implementation details:

| Export | External Callers | Recommendation |
|--------|-----------------|----------------|
| `BuilderQuery` | None | Remove (see Tier 1, §1.5) |
| `Run`, `RunSummary` | `runtime/core.py` (internal) | Keep — part of legacy format transition |
| `Problem` | Tests only | Keep — schema type |
| `AgentOrchestrator` | CLI only | Reassess (see §3.3) |
| `ApprovalStatus`, `ErrorCategory`, `DebugTool`, `TestSuiteResult` | Tests only | Keep — testing framework |
| `Runtime` | executor, server (internal) | Keep — in active use |

**Recommendation:** Remove `BuilderQuery` from `__all__`. Review whether `AgentOrchestrator` should remain in the public API given its CLI-only usage.

---

## Summary Table

| Item | Location | Type | Lines | Action |
|------|----------|------|-------|--------|
| `hitl.py` | `framework/graph/hitl.py` | Dead code | 203 | Delete |
| `state_writer.py` | `framework/storage/state_writer.py` | Migration artifact | 179 | Delete |
| `agent_manager.py` | `framework/server/agent_manager.py` | Dead shim | 36 | Delete |
| `hive_coder/` directory | `framework/agents/hive_coder/` | Stale bytecode | — | Delete directory |
| `BuilderQuery` | `framework/builder/query.py` | Unused export | 501 | Delete or de-export |
| `framework/mcp/__init__.py` | `framework/mcp/` | Empty package | 4 | Delete directory |
| `credentials/vault/` | `framework/credentials/vault/` | Unwired feature | 394 | Delete or add tests |
| `cmd_sessions_*` stubs | `runner/cli.py` lines 1773–1799 | Placeholder | ~30 | Implement or remove |
| `cmd_pause` / `cmd_resume` stubs | `runner/cli.py` lines 1801–1821 | Placeholder | ~20 | Implement or remove |
| `discover_agents` coupling | `server/routes_sessions.py` line 734 | Bad dependency | — | Extract to neutral module |
| Legacy `Runtime` dual-write | `graph/executor.py`, `runtime/core.py` | Migration debt | — | Plan removal after BuilderQuery gone |
| `AgentOrchestrator` / `hive dispatch` | `runner/orchestrator.py`, `cli.py` | Architectural concern | — | Clarify intent |

---

## What Is Confirmed Active (Not Flagged)

For completeness, the following are verified active and should not be touched:

- **`hive open` / `hive serve`** — primary entrypoints, fully functional
- **`hive run`** — headless agent execution (without `--tui`)
- **`hive shell`** — interactive REPL (without `--multi`)
- **`hive info` / `hive validate` / `hive list`** — agent inspection
- **`hive setup-credentials`** — credential wizard
- **`hive tui`** and **`hive run --tui`** — functional despite deprecation label; contains the `discover_agents` function needed by server
- **`framework/graph/`** — all files except `hitl.py` are in active use
- **`framework/runtime/`** — all files except `state_writer.py` are in active use
- **`framework/server/`** — all files except `agent_manager.py` are in active use
- **`framework/credentials/`** — all subdirectories except `vault/` are in active use
- **`framework/agents/queen/`** — primary orchestrator, fully active
- **`framework/agents/credential_tester/`** — active (used by TUI account selection)
- **`framework/monitoring/`** — active (used by `session_manager.py` for judge evaluation)
- **`framework/testing/`** — active CLI testing framework
- **`framework/tools/`** — all four modules active (Queen lifecycle, memory, graph, worker monitoring)
- **`framework/storage/`** — all files except `state_writer.py` active
- **`framework/observability/`** — active logging infrastructure
- **`framework/utils/`** — `atomic_write` used by storage layer
- **`quickstart.sh` / `quickstart.ps1`** — active onboarding flow
- **`core/codex_oauth.py`** — active (used by quickstart option 3)

---

*Analysis performed by tracing import graphs from `hive open` → `cmd_serve()` → `create_app()` → six route modules → `SessionManager`/`QueenOrchestrator`, and from `quickstart.sh` → `hive run`/`hive shell`/`hive open`. All findings verified with `grep` — no guesses.*
