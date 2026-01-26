# PR Title: Resilience, Tools & Debugging Improvements (G-Phad Pack)

## Description
This PR implements a comprehensive set of improvements ("G-Phad Pack") focusing on resilience, new capabilities, and developer experience. It addresses critical needs for production-grade agents.

## Key Changes

### 1. Resilience & Safety
- **Node Retries**: Added `max_retries` and `backoff_factor` to `NodeSpec`. Implemented exponential backoff retry logic in `LLMNode` to handle transient failures (e.g., network blips).
- **Global Timeout**: Added `timeout_seconds` to `AgentRunner` and `GraphExecutor`. Implemented strict timeout checks in the execution loop to prevent infinite runs.

### 2. New "Superpower" Tools
- **CSV Tool**: Added `csv_tool` for inspecting headers, counting rows, and sampling data from CSV files.
- **System Tool**: Added `system_tool` for monitoring OS info, resource usage (RAM/Disk), and listing top processes.

### 3. Debugging & "Time Travel"
- **State Persistence**: The executor now saves a full snapshot of the agent's memory to a JSON file (`states/{run_id}_step_{N}.json`) after every successful step. This enables "time travel" debugging and crash recovery.
- **Structured JSON Logging**: Added `--json-logs` flag to the CLI (`run` and `shell` commands). When enabled, logs are output as structured JSON objects, making them easy to parse by observability tools (Datadog, Splunk, etc.).

## Testing
- Verified retry logic by simulating failures.
- Verified timeout by running long loops.
- Verified new tools (CSV and System) via `fastmcp`.
- Verified state files are created in the storage directory.
- Verified JSON logs output correctly with `--json-logs`.
