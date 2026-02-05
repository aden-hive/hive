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
$ PYTHONPATH=exports uv run python -m file_monitor_agent validate
✓ Agent is valid

$ PYTHONPATH=exports uv run python -m file_monitor_agent info
Agent: File Monitor & Copy Agent
Nodes: 7
Edges: 8
```

**Phase 1 Complete**: Structure validated ✅

### Status After Phase 1

```
exports/file_monitor_agent/
├── __init__.py          ✅ (exports)
├── __main__.py          ✅ (CLI)
├── agent.py             ✅ (goal, graph, agent class)
├── nodes/__init__.py    ✅ (7 nodes)
├── config.py            ✅ (configuration)
├── implementations.py   ✅ (Python functions)
├── README.md            ✅ (documentation)
├── IMPLEMENTATION_GUIDE.md ✅ (next steps)
└── STATUS.md            ✅ (current state)
```

**Note**: Implementation gap exists - data flow needs connection (covered in STATUS.md)

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
$ PYTHONPATH=exports uv run pytest exports/file_monitor_agent/tests/

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
# Run the agent
./RUN_AGENT.sh

# Or manually
PYTHONPATH=exports uv run python -m file_monitor_agent run
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
4. **Documentation included** - README, STATUS, and guides auto-generated
5. **Repeatable process** - Same workflow for any agent type

## Variations

**For simpler agents:**
- Fewer nodes (3-5 instead of 7)
- Simpler workflow (linear instead of looping)
- Faster build time (10-15 minutes)

**For complex agents:**
- More nodes (10-15+)
- Multiple subgraphs
- Pause/resume points for human-in-the-loop
- Longer build time (45-60 minutes)

The workflow scales to your needs!
