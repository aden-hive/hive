# Inbox Management

**Version**: 1.0.0
**Type**: Multi-node agent
**Created**: 2026-02-11

## Overview

Automatically manage Gmail inbox emails using user-defined free-text rules. Fetch emails from the inbox (configurable batch size, default 100, supports pagination for any count), then take appropriate actions — trash junk, mark spam, mark important, mark as unread/read, archive, star, and categorize for reporting.

## Architecture

### Execution Flow

```
intake → fetch-emails → classify-and-act → report
```

### Nodes (4 total)

1. **intake** (event_loop)
   - Receive and validate input parameters: rules and max_emails. Present the interpreted rules back to the user for confirmation.
   - Reads: `rules, max_emails`
   - Writes: `rules, max_emails`
   - Client-facing: Yes (blocks for user input)
2. **fetch-emails** (event_loop)
   - Fetch emails from the Gmail inbox up to the configured batch limit. Processes in small batches across multiple iterations.
   - Reads: `rules, max_emails`
   - Writes: `emails`
   - Tools: `gmail_list_messages, gmail_get_message`
3. **classify-and-act** (event_loop)
   - Execute the user's rules on each email using the appropriate Gmail actions (trash, spam, mark important, mark unread/read, archive, star).
   - Reads: `rules, emails`
   - Writes: `actions_taken`
   - Tools: `gmail_trash_message, gmail_modify_message, gmail_batch_modify_messages`
4. **report** (event_loop)
   - Generate a summary report of all actions taken, organized by action type.
   - Reads: `actions_taken`
   - Writes: `summary_report`

### Edges (3 total)

- `intake` → `fetch-emails` (condition: on_success, priority=1)
- `fetch-emails` → `classify-and-act` (condition: on_success, priority=1)
- `classify-and-act` → `report` (condition: on_success, priority=1)


## Goal Criteria

### Success Criteria

**Each email is acted upon according to the user's free-text rules** (weight 0.3)
- Metric: classification_match_rate
- Target: >=90%
**Trash, spam, mark-important, mark-unread, mark-read, archive, star actions are applied correctly using only valid Gmail system labels** (weight 0.25)
- Metric: action_correctness
- Target: >=95%
**Only inbox emails are fetched and processed (label:INBOX scope)** (weight 0.2)
- Metric: inbox_scope_accuracy
- Target: 100%
**Produces a summary report showing what was done, with email subjects listed per action** (weight 0.15)
- Metric: report_completeness
- Target: 100%
**All fetched emails up to the configured max are processed; none are silently skipped** (weight 0.1)
- Metric: emails_processed_ratio
- Target: 100%

### Constraints

**Must only fetch and process emails from the inbox (label:INBOX)** (hard)
- Category: safety
**Must not process more emails than the configured max_emails parameter** (hard)
- Category: operational
**Marking as spam moves to spam folder but preserves the email; only explicit trash rules permanently delete emails** (hard)
- Category: safety
**Must only use valid Gmail system labels; custom labels like 'FYI' or 'Action Needed' must NOT be applied via Gmail API** (hard)
- Category: operational

## Required Tools

- `gmail_batch_modify_messages`
- `gmail_get_message`
- `gmail_list_messages`
- `gmail_modify_message`
- `gmail_trash_message`

## MCP Tool Sources

### hive-tools (stdio)
Hive tools MCP server

**Configuration:**
- Command: `uv`
- Args: `['run', 'python', 'mcp_server.py', '--stdio']`
- Working Directory: `tools`

Tools from these MCP servers are automatically loaded when the agent runs.

## Usage

### Basic Usage

```python
from framework.runner import AgentRunner

# Load the agent
runner = AgentRunner.load("examples/templates/inbox_management")

# Run with input
result = await runner.run({"input_key": "value"})

# Access results
print(result.output)
print(result.status)
```

### Input Schema

The agent's entry node `intake` requires:
- `rules` (required)
- `max_emails` (required)


### Output Schema

Terminal nodes: `report`

## Version History

- **1.0.0** (2026-02-11): Initial release
  - 4 nodes, 3 edges
  - Goal: Inbox Management
