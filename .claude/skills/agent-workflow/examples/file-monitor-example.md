# Example: File Monitor Agent

This example shows the complete agent-workflow in action for building a file monitoring agent.

## Initial Request

```
User: "Build an agent that monitors ~/Downloads and copies new files to ~/Documents"
```

## Phase 1: Building (20 minutes)

### Step 1: Create Structure

Agent invokes `/building-agents` skill and:

1. Creates `exports/file_monitor_agent/` package
2. Writes skeleton files (__init__.py, __main__.py, agent.py, etc.)

**Output**: Package structure visible immediately

### Step 2: Define Goal

```python
goal = Goal(
    id="file-monitor-copy",
    name="Automated File Monitor & Copy",
    success_criteria=[
        # 100% detection rate
        # 100% copy success
        # 100% conflict resolution
        # >99% uptime
    ],
    constraints=[
        # Preserve originals
        # Handle errors gracefully
        # Track state
        # Respect permissions
    ]
)
```

**Output**: Goal written to agent.py

### Step 3: Design Nodes

7 nodes approved and written incrementally:

1. `initialize-state` - Set up tracking
2. `list-downloads` - Scan directory
3. `identify-new-files` - Find new files
4. `check-for-new-files` - Router
5. `copy-files` - Copy with conflict resolution
6. `update-state` - Mark as processed
7. `wait-interval` - Sleep between cycles

**Output**: All nodes in nodes/__init__.py

### Step 4: Connect Edges

8 edges connecting the workflow loop:

```
initialize → list → identify → check
                                ↓  ↓
                              copy  wait
                                ↓    ↑
                              update ↓
                                ↓    ↓
                              wait → list (loop)
```

**Output**: Edges written to agent.py

### Step 5: Finalize

```bash
$ PYTHONPATH=core:exports python -m file_monitor_agent validate
✓ Agent is valid

$ PYTHONPATH=core:exports python -m file_monitor_agent info
Agent: File Monitor & Copy Agent
Nodes: 7
Edges: 8
```

**Phase 1 Complete**: Structure validated ✅

### Status After Phase 1

```
exports/file_monitor_agent/
├── __init__.py          ✅ (package exports)
├── __main__.py          ✅ (CLI: run, info, validate, shell)
├── agent.py             ✅ (goal, graph, AgentRuntime class)
├── nodes/__init__.py    ✅ (7 nodes)
├── config.py            ✅ (RuntimeConfig, AgentMetadata)
├── mcp_servers.json     ✅ (MCP server configuration)
└── README.md            ✅ (documentation)
```

**Note**: Agent uses `AgentRuntime` for multi-entrypoint support with pause/resume capabilities. MCP servers are configured via `mcp_servers.json`.

## Phase 2: Testing (25 minutes)

### Step 1: Analyze Agent

Agent invokes `/testing-agent` skill and:

1. Reads goal from `exports/file_monitor_agent/agent.py`
2. Identifies 4 success criteria to test
3. Identifies 4 constraints to verify
4. Plans test coverage

### Step 2: Generate Tests

Creates test files:

```
exports/file_monitor_agent/tests/
├── conftest.py              (fixtures)
├── test_constraints.py      (4 constraint tests)
├── test_success_criteria.py (4 success tests)
└── test_edge_cases.py       (error handling)
```

Tests approved incrementally by user.

### Step 3: Run Tests

```bash
$ PYTHONPATH=core:exports pytest exports/file_monitor_agent/tests/

test_constraints.py::test_preserves_originals     PASSED
test_constraints.py::test_handles_errors          PASSED
test_constraints.py::test_tracks_state            PASSED
test_constraints.py::test_respects_permissions    PASSED

test_success_criteria.py::test_detects_all_files  PASSED
test_success_criteria.py::test_copies_all_files   PASSED
test_success_criteria.py::test_resolves_conflicts PASSED
test_success_criteria.py::test_continuous_run     PASSED

test_edge_cases.py::test_empty_directory          PASSED
test_edge_cases.py::test_permission_denied        PASSED
test_edge_cases.py::test_disk_full                PASSED
test_edge_cases.py::test_large_files              PASSED

========================== 12 passed in 3.42s ==========================
```

**Phase 2 Complete**: All tests pass ✅

## Final Output

**Production-Ready Agent:**

```bash
# Show agent info
PYTHONPATH=core:exports python -m file_monitor_agent info

# Validate structure
PYTHONPATH=core:exports python -m file_monitor_agent validate

# Run the agent
PYTHONPATH=core:exports python -m file_monitor_agent run --input '{"source_dir": "~/Downloads", "dest_dir": "~/Documents"}'

# Interactive shell
PYTHONPATH=core:exports python -m file_monitor_agent shell
```

**Python API:**

```python
from exports.file_monitor_agent import default_agent

# Simple usage
result = await default_agent.run({
    "source_dir": "~/Downloads",
    "dest_dir": "~/Documents"
})

# Check output
if result.success:
    print(f"Files processed: {result.output['files_copied']}")
```

**Capabilities:**
- Monitors ~/Downloads continuously
- Copies new files to ~/Documents
- Resolves conflicts with timestamps
- Handles errors gracefully
- Tracks processed files
- Runs as background service

**Total Time**: ~45 minutes from concept to production

## Key Learnings

1. **Incremental building** - Files written immediately, visible throughout
2. **Validation early** - Structure validated before moving to implementation
3. **Test-driven** - Tests reveal real behavior
4. **Modern runtime** - Uses `AgentRuntime` with multi-entrypoint support
5. **MCP integration** - Tools configured via `mcp_servers.json`
6. **Repeatable process** - Same workflow for any agent type

## Variations

**For simpler agents:**
- Fewer nodes (3-5 instead of 7)
- Simpler workflow (linear instead of looping)
- Faster build time (10-15 minutes)

**For complex agents:**
- More nodes (10-15+)
- Multiple entry points via `entry_points` dict
- Pause/resume nodes for human-in-the-loop
- MCP server integration for external tools
- Longer build time (45-60 minutes)

The workflow scales to your needs!
