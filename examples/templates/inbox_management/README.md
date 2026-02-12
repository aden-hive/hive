# Inbox Management

**Version**: 1.0.0
**Type**: Multi-node agent
**Created**: 2026-02-11

## Overview

Automatically triage unread Gmail emails using user-defined free-text rules. Fetch unread emails (configurable batch size, default 100), classify each by urgency and type, then take appropriate actions — trash spam, archive low-priority messages, mark important emails, and categorize the rest as Action Needed, FYI, or Waiting On.

## Architecture

### Execution Flow

```
intake → fetch-emails → classify-and-act → report
```

### Nodes (4 total)

1. **intake** (event_loop)
   - Receive and validate input parameters: triage rules and max_emails. Present the interpreted rules back to the user for confirmation before proceeding.
   - Reads: `rules, max_emails`
   - Writes: `triage_rules, max_emails`
   - Client-facing: Yes (blocks for user input)
2. **fetch-emails** (event_loop)
   - Fetch unread emails from Gmail up to the configured batch limit. Only retrieves emails with the UNREAD label.
   - Reads: `triage_rules, max_emails`
   - Writes: `emails`
   - Tools: `gmail_list_messages, gmail_get_message`
3. **classify-and-act** (event_loop)
   - Classify each email against the user's triage rules, then execute the appropriate Gmail actions (trash, archive, mark important, add labels).
   - Reads: `triage_rules, emails`
   - Writes: `actions_taken`
   - Tools: `gmail_trash_message, gmail_modify_message, gmail_batch_modify_messages`
4. **report** (event_loop)
   - Generate a summary report of all triage actions taken, organized by category.
   - Reads: `actions_taken`
   - Writes: `summary_report`

### Edges (3 total)

- `intake` → `fetch-emails` (condition: on_success, priority=1)
- `fetch-emails` → `classify-and-act` (condition: on_success, priority=1)
- `classify-and-act` → `report` (condition: on_success, priority=1)


## Goal Criteria

### Success Criteria

**Each unread email is classified according to the user's free-text rules with appropriate urgency category (action needed, FYI, waiting on) and type (spam, newsletter, important, etc.)** (weight 0.3)
- Metric: classification_match_rate
- Target: >=90%
**Trash, archive, mark-important, and label actions are applied correctly to the right emails based on classification** (weight 0.25)
- Metric: action_correctness
- Target: >=95%
**Only unread emails are fetched and processed; read emails are never modified** (weight 0.2)
- Metric: read_email_modifications
- Target: 0
**Produces a summary report showing what was done: how many trashed, archived, marked important, and categorized, with email subjects listed per category** (weight 0.15)
- Metric: report_completeness
- Target: 100%
**All fetched emails up to the configured max are classified and acted upon; none are silently skipped** (weight 0.1)
- Metric: emails_processed_ratio
- Target: 100%

### Constraints

**Must never modify, trash, or relabel emails that are already read** (hard)
- Category: safety
**Must not process more emails than the configured max_emails parameter** (hard)
- Category: operational
**Archiving removes from inbox but preserves the email; only explicit trash rules move emails to trash** (hard)
- Category: safety

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
