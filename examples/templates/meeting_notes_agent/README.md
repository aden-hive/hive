# 🐝 Meeting Notes & Action Item Agent

> **Hive Template** — Copy it, customize the goal/nodes/edges, and run it.

An outcome-driven agent that parses meeting transcripts and extracts structured, actionable notes. Supports **Anthropic Claude** and **Google Gemini** as LLM providers, and delivers results to **Slack** via the Slack MCP tool.

---

## What This Agent Does

Given a raw meeting transcript, the agent:

1. **Validates** the input and normalises the transcript
2. **Extracts** (via LLM) a structured summary including:
   - Executive summary (2–3 sentences)
   - Attendee list
   - Key decisions made
   - Action items with owner, due date, and priority (`high / medium / low`)
   - Blockers flagged during the meeting
   - Follow-up items
3. **Validates** the LLM output against a Pydantic schema
4. **Posts** a rich Slack Block Kit message to a specified channel (optional)
5. **Returns** the fully structured JSON output

---

## Agent Graph

```
validate_input
    │
    ├─ on_success → extract_meeting_data (Claude or Gemini)
    │                   │
    │                   └─ on_success → parse_and_validate_output
    │                                       │
    │                               ┌───────┴───────┐
    │                   slack_channel?              no slack
    │                       │                          │
    │               format_slack_message        compile_final_output
    │                       │                          │
    │               post_to_slack ──────────────────→ ●
    │
    └─ on_failure → handle_error → ●
```

---

## File Structure

```
meeting_notes_agent/
├── __init__.py          # Package exports
├── __main__.py          # CLI entry point
├── agent.json           # GraphSpec (nodes, edges, goal, success criteria)
├── agent.py             # Agent class and graph construction
├── nodes.py             # Node function implementations + Pydantic schemas + NodeSpec definitions
├── config.py            # Model config + dual LLM registry
├── mcp_servers.json     # MCP server configuration
├── tools/
│   ├── __init__.py
│   └── slack_tool.py    # Slack MCP tool (post_message, list_channels)
├── tests/
│   ├── __init__.py
│   └── test_meeting_notes_agent.py   # Full test suite
└── README.md            # This file
```

### Architecture Overview

The agent follows a clean separation of concerns:

- **nodes.py** - Contains all node function implementations, Pydantic schemas (ActionItem, MeetingNotesOutput), and NodeSpec definitions. This is where the business logic lives.

- **agent.py** - Orchestrates the graph construction. Imports node functions and NodeSpecs from nodes.py, defines the Goal, edges, and the MeetingNotesAgent class that manages execution.

- **config.py** - Centralized configuration for LLM providers (Anthropic Claude, Google Gemini), model settings, and agent metadata.

- **agent.json** - Declarative graph specification in JSON format. Defines nodes, edges, goal, success criteria, and constraints in a format that can be read by external tools.

- **__init__.py** - Package entry point that exports all public APIs from nodes.py and agent.py.

- **__main__.py** - CLI entry point for running the agent via `python -m meeting_notes_agent`.

---

## Prerequisites

- Python 3.11+
- Hive installed (`./quickstart.sh` from repo root)
- At least one LLM API key:
  - `ANTHROPIC_API_KEY` — for Claude (default)
  - `GEMINI_API_KEY` — for Google Gemini
- `SLACK_BOT_TOKEN` — for Slack delivery (optional)

---

## Setup

### 1. Install Hive

```bash
git clone https://github.com/adenhq/hive.git
cd hive
./quickstart.sh
```

### 2. Copy Template

```bash
cp -r examples/templates/meeting_notes_agent exports/meeting_notes_agent
```

### 3. Configure Credentials

Create a `.env` file in the agent directory:

```bash
cp .env.example .env
```

Then edit `.env` and add your API keys:

```bash
ANTHROPIC_API_KEY="sk-ant-..."
GEMINI_API_KEY="AIzaSy..."          # optional
SLACK_BOT_TOKEN="xoxb-..."          # optional
```

### 4. Validate the Agent

```bash
PYTHONPATH=exports uv run python -m meeting_notes_agent validate
```

---

## Running the Agent

### Basic run (no Slack)

```bash
hive run exports/meeting_notes_agent --input '{
  "transcript": "Meeting: Q1 Planning\nSarah: We need to launch by March 31st.\nMarcus: I will have the API done by Friday.\nTom: Approved."
}'
```

### With Slack delivery

```bash
hive run exports/meeting_notes_agent --input '{
  "transcript": "...",
  "meeting_name": "Q1 Planning",
  "meeting_date": "2026-02-20",
  "slack_channel": "#team-standup"
}'
```

### Using Google Gemini instead of Claude

```bash
hive run exports/meeting_notes_agent --input '{
  "transcript": "...",
  "llm_provider": "gemini"
}'
```

### Interactive TUI

```bash
hive run exports/meeting_notes_agent --tui
```

### Python directly

```bash
PYTHONPATH=exports uv run python -m meeting_notes_agent run --input '{
  "transcript": "Meeting: Sprint Retro\nAlex: We need to fix the login bug by Monday — it is blocking QA.\nMia: I will do it. Also, should we move to biweekly sprints?\nAlex: Yes, agreed. Starting next sprint."
}'
```

---

## Input Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `transcript` | string | ✅ | Raw meeting transcript text (min 50 chars) |
| `meeting_name` | string | — | Meeting title (default: "Untitled Meeting") |
| `meeting_date` | string | — | ISO date string `YYYY-MM-DD` |
| `slack_channel` | string | — | Slack channel ID (`C012AB3CD`) or name (`#general`) |
| `llm_provider` | string | — | `anthropic` (default) or `gemini` |

---

## Output Schema

```json
{
  "summary": "2-3 sentence executive summary.",
  "attendees": ["Sarah Chen (PM)", "Marcus Rodriguez (Lead)"],
  "decisions": [
    "Mobile app launch target is March 31st",
    "Analytics dashboard ships Q2"
  ],
  "action_items": [
    {
      "task": "Fix login bug",
      "owner": "Alex",
      "due": "by Monday",
      "priority": "high"
    }
  ],
  "blockers": ["Login bug is blocking QA testing"],
  "follow_ups": ["Discuss sprint cadence change at next retro"],
  "slack_message_sent": true
}
```

---

## Slack Setup

### Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From Scratch**
2. Under **OAuth & Permissions**, add these Bot Token Scopes:
   - `chat:write`
   - `chat:write.public`
3. **Install to workspace** and copy the **Bot User OAuth Token** (`xoxb-...`)
4. Set `SLACK_BOT_TOKEN=xoxb-...` in your environment

### Invite the Bot to a Channel

```
/invite @YourBotName
```

The bot must be a member of private channels. For public channels, `chat:write.public` handles it automatically.

---

## Running Tests

```bash
# Run all tests
PYTHONPATH=examples/templates uv run pytest examples/templates/meeting_notes_agent/tests/ -v

# Run only constraint tests
PYTHONPATH=examples/templates uv run pytest examples/templates/meeting_notes_agent/tests/ -v -k "Constraint"

# Run only success scenario tests
PYTHONPATH=examples/templates uv run pytest examples/templates/meeting_notes_agent/tests/ -v -k "Success"
```

---

## Customising This Agent

### Change the LLM model

Edit `config.py`:
```python
CONFIG = {
    "model": "anthropic/claude-opus-4-5-20250929",   # Use Opus for higher quality
    "gemini_model": "gemini/gemini-1.5-flash-latest", # Use Flash for lower cost
}
```

### Add a new output field

1. Add the field to `MeetingNotesOutput` in `agent.py`
2. Update the extraction prompt in `agent.json` (the `prompt` field of `extract_meeting_data` node)
3. Add the field to `output_schema` in `agent.json`
4. Add a test in `tests/test_meeting_notes_agent.py`

### Add a second Slack channel

Fork the `post_to_slack` node in `agent.json` with a different `channel` input key, or modify `post_to_slack()` in `agent.py` to accept a list of channels.

### Connect to Linear or Jira instead of Slack

Replace the `post_to_slack` node with a `post_to_linear` or `post_to_jira` function node, and add the corresponding tool to `tools/`. Follow the same pattern as `slack_tool.py`.

---

## Self-Healing Notes

Hive's adaptive loop activates when this agent fails. Common failure modes and what happens:

| Failure | How the loop handles it |
|---|---|
| LLM returns invalid JSON | `parse_and_validate_output` raises → `handle_error` captures it. Hive logs the failure context for graph evolution. |
| Slack API rate limit | `post_to_slack` catches the exception, logs it as non-fatal, and still returns final output. |
| Transcript too short | `validate_input` raises → `handle_error` returns a clean error response. |
| LLM hallucination (e.g. fabricated owner name) | Hard constraint `c_no_hallucination` is logged; Hive's `BuilderQuery` can refine the prompt on next evolution cycle. |

---

## Contributing

1. Fork the repo and create a branch: `git checkout -b feat/meeting-notes-agent`
2. Make your changes and run the test suite
3. Open an issue with the `agent-idea` label **before** submitting a PR (per [CONTRIBUTING.md](../../CONTRIBUTING.md))
4. Submit your PR and move the agent from `exports/` to `examples/templates/`

---

## Related Hive Examples

- [`tech_news_reporter`](../tech_news_reporter/) — Web search + LLM summarisation
- [`email_inbox_management`](../email_inbox_management/) — Gmail integration
- [`job_hunter`](../job_hunter/) — Multi-source job search agent

---

*Made with 🔥 for the Aden Hive community · [adenhq.com](https://adenhq.com)*
