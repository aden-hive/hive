# Runtime Logs Tool

The Runtime Logs tool provides read-only access to the comprehensive three-level logging system used by Aden Hive agents. It allows developers to monitor execution health, identify failing nodes, and inspect raw tool/LLM interactions.

## Logging Levels

1.  **Level 1 (Summary)**: Provides a high-level overview of a graph run, including overall status (success, failure, degraded), start time, and whether it requires attention.
2.  **Level 2 (Details)**: Provides per-node results, including exit status, success/failure flags, and specific attention markers for a given run.
3.  **Level 3 (Raw/Steps)**: Provides the full execution trace, including tool inputs/outputs, LLM prompts/completions, and token usage for every step of every node.

## Tools

### `query_runtime_logs`
Returns a list of recent graph run summaries.
- **agent_work_dir**: Path to the agent's working directory.
- **status**: Optional filter (e.g., "needs_attention", "success", "failure").
- **limit**: Maximum number of runs to return (default: 20).

### `query_runtime_log_details`
Returns detailed completion information for each node in a specific run.
- **agent_work_dir**: Path to the agent's working directory.
- **run_id**: The unique ID of the run to inspect.
- **needs_attention_only**: Filter to show only nodes flagged with issues.
- **node_id**: Filter to show details for a specific node.

### `query_runtime_log_raw`
Returns the raw step-by-step logs for a specific run, including tool calls and LLM responses.
- **agent_work_dir**: Path to the agent's working directory.
- **run_id**: The unique ID of the run to inspect.
- **step_index**: Filter for a specific execution step.
- **node_id**: Filter for a specific node's steps.

## Storage Compatibility

This tool automatically detects and scans both the modern session-based storage (`sessions/{session_id}/logs/`) and the deprecated legacy format (`runtime_logs/runs/{run_id}/`), ensuring full visibility across different framework versions.
