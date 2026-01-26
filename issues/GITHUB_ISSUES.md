# GitHub Issues - Hive/Aden Framework

This document contains proposed GitHub issues for the Hive/Aden AI Agent Framework.
Issues are categorized by type and priority for easy tracking.

---

## 🐛 Bug Fixes

### Issue #1: LLMJudge Has Hardcoded Anthropic Dependency ✅ FIXED

**Status:** Resolved in this PR

**Location:** `core/framework/testing/llm_judge.py`

**Problem:**
The `LLMJudge` class directly instantiates `anthropic.Anthropic()` client, breaking tests when users don't have Anthropic credentials configured.

**Solution Applied:**
Refactored to use `LiteLLMProvider` which supports 100+ providers:
```python
# Before
self.client = anthropic.Anthropic()

# After
self.provider = LiteLLMProvider(model=model)
```

---

### Issue #2: MCP Server Has Direct LLM Dependency ✅ ALREADY FIXED

**Status:** Already resolved in codebase

**Location:** `core/framework/mcp/agent_builder_server.py`

**Problem (Original):**
MCP server tools were documented as having hardcoded LLM dependencies. This was tracked in `issues/remove-llm-dependency-from-mcp-server.md`.

**Verification:**
Code review confirmed that the MCP tools now use pure JSON/Pydantic operations without LLM calls. The tool functions (`create_goal`, `add_node`, `connect_nodes`, etc.) are properly stateless.

---

## 🚀 Feature Implementations

### Issue #3: Add Guardrails Framework ✅ IMPLEMENTED

**Status:** Implemented in this PR

**Location:** `core/framework/runtime/guardrails.py`

**Description:**
The ROADMAP.md mentions "guardrails framework for AI safety" as a Q3 priority, but no implementation existed.

**Implementation:**
Created comprehensive guardrails framework including:
- `Guardrail` base class with pre/post execution hooks
- `BudgetGuardrail` - Token/cost limits
- `RateLimitGuardrail` - Rate limiting with sliding windows
- `ContentFilterGuardrail` - Content safety filters
- `MaxStepsGuardrail` - Execution step limits
- `CustomGuardrail` - User-defined validation functions
- `GuardrailRegistry` - Global guardrail management

**Files Created:**
- `core/framework/runtime/guardrails.py` (~500 lines)
- `core/tests/test_guardrails.py` (comprehensive tests)

---

### Issue #4: Add WebSocket Event Streaming ✅ IMPLEMENTED

**Status:** Implemented in this PR

**Location:** `core/framework/runtime/websocket_server.py`, `core/framework/runtime/event_types.py`

**Description:**
README.md claims "real-time event streaming" but no WebSocket implementation existed. The EventBus was purely in-memory.

**Implementation:**
- WebSocket server that bridges EventBus to external clients
- Strongly-typed event payloads with Pydantic models
- Client filtering by event type, stream ID, execution ID
- Automatic reconnection handling

**Files Created:**
- `core/framework/runtime/websocket_server.py`
- `core/framework/runtime/event_types.py`

---

### Issue #5: Add Audit Trail Tool ✅ IMPLEMENTED

**Status:** Implemented in this PR

**Location:** `tools/src/aden_tools/tools/audit_trail_tool/`

**Description:**
For compliance and debugging, agents need the ability to generate audit trails of their decision-making process.

**Implementation:**
Created MCP tools for audit trail generation:
- `generate_audit_trail` - Comprehensive audit report from run data
- `get_decision_timeline` - Chronological decision list
- `export_audit_report` - Export as JSON/Markdown/CSV
- `list_runs` - Query available runs

**Files Created:**
- `tools/src/aden_tools/tools/audit_trail_tool/__init__.py`
- `tools/src/aden_tools/tools/audit_trail_tool/audit_trail_tool.py`
- `tools/tests/tools/test_audit_trail_tool.py`

---

## 📋 Proposed Issues (Not Yet Implemented)

### Issue #6: Add Metrics Export and Prometheus Integration

**Priority:** Medium  
**Type:** Feature  
**Labels:** `enhancement`, `observability`

**Description:**
The framework tracks metrics internally but has no standard export format. Production deployments need Prometheus/OpenTelemetry integration.

**Proposed Solution:**
1. Add `/metrics` endpoint to WebSocket server (or separate HTTP server)
2. Export standard metrics:
   - `aden_tokens_total{provider, model}` - Counter
   - `aden_cost_usd_total{provider, model}` - Counter  
   - `aden_execution_duration_seconds` - Histogram
   - `aden_decisions_total{outcome}` - Counter
   - `aden_guardrail_violations_total{guardrail}` - Counter

**Files to Create:**
- `core/framework/runtime/metrics_exporter.py`
- `core/tests/test_metrics_exporter.py`

---

### Issue #7: Improve Error Messages for Graph Validation

**Priority:** Medium  
**Type:** Enhancement  
**Labels:** `dx`, `error-handling`

**Description:**
When graph validation fails (missing connections, cycles, invalid node types), error messages don't provide actionable guidance.

**Current Behavior:**
```
ValidationError: Graph validation failed
```

**Desired Behavior:**
```
GraphValidationError: Graph has disconnected nodes
  - Node 'process_data' has no incoming edges
  - Suggestion: Connect 'start_node' → 'process_data' or remove the orphan node
  
  Visual graph:
  [start_node] → [analyze] → [end]
                            
  [process_data] (DISCONNECTED)
```

**Files to Modify:**
- `core/framework/graph/executor.py` - Add detailed error context
- `core/framework/schemas/graph.py` - Add validation helpers

---

### Issue #8: Add Structured Logging with Context Propagation

**Priority:** Medium  
**Type:** Enhancement  
**Labels:** `observability`, `logging`

**Description:**
Current logging uses basic Python logging without structured output or trace context propagation.

**Proposed Solution:**
1. Add structlog or similar for JSON logging
2. Propagate execution context (run_id, node_id, decision_id) automatically
3. Support log levels per-component via configuration

**Example Output:**
```json
{
  "timestamp": "2024-01-15T10:00:00Z",
  "level": "info",
  "message": "Node execution started",
  "context": {
    "run_id": "run-123",
    "node_id": "analyze_input",
    "execution_id": "exec-456"
  }
}
```

---

### Issue #9: Add CLI for Agent Development

**Priority:** Low  
**Type:** Feature  
**Labels:** `enhancement`, `dx`

**Description:**
The framework has `cli.py` but it's minimal. A rich CLI would improve developer experience.

**Proposed Commands:**
```bash
# Create new agent from template
aden new my-agent --template=simple

# Validate agent graph
aden validate agent.json

# Run agent locally with hot-reload
aden dev agent.json --port=8080

# Generate audit report
aden audit run-123 --format=markdown

# Export agent graph as Mermaid diagram
aden visualize agent.json --output=graph.md
```

**Files to Modify:**
- `core/framework/cli.py` - Expand CLI functionality
- Add templates in `core/framework/templates/`

---

### Issue #10: Add Database Storage Backend

**Priority:** Low  
**Type:** Feature  
**Labels:** `enhancement`, `storage`

**Description:**
`FileStorage` is the only implemented backend. Production deployments need database options.

**Proposed Solution:**
Add alternative storage backends:
1. `SQLiteStorage` - Local database, good for development
2. `PostgresStorage` - Production-ready relational storage
3. `RedisStorage` - For high-throughput temporary storage

**Interface:**
```python
class StorageBackend(Protocol):
    async def save_run(self, run: RunLog) -> None: ...
    async def load_run(self, run_id: str) -> RunLog: ...
    async def query_runs(self, filters: RunFilters) -> list[RunLog]: ...
```

---

## 📊 Summary

| Issue | Type | Priority | Status |
|-------|------|----------|--------|
| #1 LLMJudge Anthropic Dependency | Bug | Critical | ✅ Fixed |
| #2 MCP Server LLM Dependency | Bug | High | ✅ Already Fixed |
| #3 Guardrails Framework | Feature | High | ✅ Implemented |
| #4 WebSocket Event Streaming | Feature | High | ✅ Implemented |
| #5 Audit Trail Tool | Feature | Medium | ✅ Implemented |
| #6 Prometheus Metrics | Feature | Medium | 📋 Proposed |
| #7 Better Error Messages | Enhancement | Medium | 📋 Proposed |
| #8 Structured Logging | Enhancement | Medium | 📋 Proposed |
| #9 Rich CLI | Feature | Low | 📋 Proposed |
| #10 Database Backends | Feature | Low | 📋 Proposed |

---

## 🔗 Related Documentation

- [ROADMAP.md](../ROADMAP.md) - Framework roadmap and priorities
- [DEVELOPER.md](../DEVELOPER.md) - Developer setup guide
- [MCP_INTEGRATION_GUIDE.md](../core/MCP_INTEGRATION_GUIDE.md) - MCP server usage
- [Architecture Overview](../docs/architecture/README.md) - System architecture

---

## 📝 Notes for Contributors

1. **Before implementing**: Check if an issue is already being worked on
2. **Testing**: All new code must have corresponding tests
3. **Documentation**: Update relevant docs when adding features
4. **Core Logic**: Avoid changing existing core behavior without discussion
5. **Provider Agnostic**: Always use `LiteLLMProvider` for LLM calls

---

*Last updated: Generated during codebase analysis session*
