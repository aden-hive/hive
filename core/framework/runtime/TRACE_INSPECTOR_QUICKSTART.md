# Trace Inspector - Quick Start Guide

## Where to Run

Run these commands from your **project root** (`/Users/sudip/hive`):

```bash
cd /Users/sudip/hive
```

## Step-by-Step Usage

### 1. Run an Agent (to generate traces)

```bash
python3 -m framework run ./exports/test_agent --input '{"query": "hello world"}' --mock
```

This will:
- Execute the agent
- Automatically create a trace
- Save it to `~/.hive/storage/test_agent/traces/{execution_id}.json`

### 2. List Available Traces

```bash
python3 -m framework trace-inspect --list --agent-path ./exports/test_agent
```

**Output:**
```
Available traces in /Users/sudip/.hive/storage/test_agent/traces:

  ✓ exec_main_fb04a5c8
     Status: completed
     Started: 2026-01-26 19:01:25
     Duration: 0.0s
     Decisions: 1
```

### 3. Inspect a Specific Trace

Use the `execution_id` from step 2:

```bash
python3 -m framework trace-inspect exec_main_fb04a5c8 --agent-path ./exports/test_agent
```

**Output:**
```
============================================================
Execution Trace Analysis
============================================================

Execution ID: exec_main_fb04a5c8
Status: completed
Duration: 1ms

Summary:
  ✓ Execution completed | Duration: 1ms | Decisions: 1 | LLM calls: 0 | Tool calls: 0 | Success rate: 100.0%

Decisions:
  Total: 1
  Successful: 1
  Failed: 0
  Success Rate: 100.0%

Performance:
  Total Duration: 1ms
  Avg Decision Latency: 0ms
  Max Decision Latency: 0ms
  Nodes Executed: 0
```

### 4. View Timeline

```bash
python3 -m framework trace-inspect exec_main_fb04a5c8 --agent-path ./exports/test_agent --timeline
```

**Output:**
```
Event Timeline:
  [2026-01-26T19:01:25.128613] decision: Decision: Execute function echo_function
  [2026-01-26T19:01:25.128619] outcome: Outcome: ✓ 
```

## Example with Real Agent

If you have a more complex agent with LLM calls and tool usage:

```bash
# 1. Run agent
python3 -m framework run ./exports/my_agent --input '{"query": "search for python tutorials"}'

# 2. List traces
python3 -m framework trace-inspect --list --agent-path ./exports/my_agent

# 3. Inspect trace (example output)
python3 -m framework trace-inspect exec_abc123 --agent-path ./exports/my_agent
```

**Example Output (for complex agent):**
```
============================================================
Execution Trace Analysis
============================================================

Execution ID: exec_abc123
Status: completed
Duration: 5234ms

Summary:
  ✓ Execution completed | Duration: 5234ms | Decisions: 5 | LLM calls: 3 | Tool calls: 2 | Cost: $0.0234 | Success rate: 80.0%

Decisions:
  Total: 5
  Successful: 4
  Failed: 1
  Success Rate: 80.0%

Failed Decisions:
  - [node_3] Search for user data
    Error: API timeout

Performance:
  Total Duration: 5234ms
  Avg Decision Latency: 1046ms
  Max Decision Latency: 2500ms
  Nodes Executed: 5
  Insights:
    - 1 decisions took >5s

Cost:
  Total: $0.0234
  Per Decision: $0.004680
  Per Token: $0.000023
  Total Tokens: 1,020

Problems Detected:
  ⚠️ [warning] Execution took 5234ms
  🔴 [error] 1 decisions failed

Recommendations:
  • Consider improving decision logic - success rate is low
  • High decision latency - consider caching or optimization
```

## Trace Storage Locations

Traces are automatically saved to:

- **Default**: `~/.hive/storage/{agent_name}/traces/{execution_id}.json`
- **Example**: `/Users/sudip/.hive/storage/test_agent/traces/exec_main_fb04a5c8.json`

The CLI automatically checks these locations when you use `--agent-path`.

## All Available Options

```bash
# List traces
python3 -m framework trace-inspect --list --agent-path ./exports/my_agent

# Inspect trace
python3 -m framework trace-inspect <execution_id> --agent-path ./exports/my_agent

# With timeline
python3 -m framework trace-inspect <execution_id> --agent-path ./exports/my_agent --timeline

# Export analysis to JSON
python3 -m framework trace-inspect <execution_id> --agent-path ./exports/my_agent --export analysis.json

# Output as JSON
python3 -m framework trace-inspect <execution_id> --agent-path ./exports/my_agent --json

# From trace file (if exported)
python3 -m framework trace-inspect <execution_id> --trace-file trace.json
```

## Troubleshooting

**No traces found?**
- Make sure you've run the agent at least once
- Check that trace collection is enabled (it's automatic)
- Verify storage path: `~/.hive/storage/{agent_name}/traces/`

**Can't find execution_id?**
- Use `--list` to see all available traces
- Execution IDs are shown in the list output

**Agent path not found?**
- Use absolute path: `--agent-path /full/path/to/exports/my_agent`
- Or relative from project root: `--agent-path ./exports/my_agent`
