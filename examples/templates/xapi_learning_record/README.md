# xAPI Learning Record Agent

A deterministic Hive agent template that captures learning events, builds valid
[xAPI 1.0.3](https://github.com/adlnet/xAPI-Spec/blob/master/xAPI-About.md)
statements, validates structure, dispatches to a Learning Record Store (LRS),
and returns a confirmation with `statement_id` and timestamp.

**No LLM required** for the core pipeline. Statement building, validation, and
LRS dispatch are handled by pure Python functions in `tools.py`.

---

## Pipeline

```text
event-capture → statement-builder → validator → lrs-dispatch → confirmation
     ↑                                                               |
     └───────────────────── (loop) ─────────────────────────────────┘
```

| Node | Role | LLM? | Tools |
|---|---|---|---|
| `event-capture` | Collect actor/verb/object/result from user, normalize | Yes (intake only) | — |
| `statement-builder` | Build xAPI 1.0.3 statement dict | No | `build_xapi_statement` |
| `validator` | Check required fields, IRI format, mbox, score range | No | `validate_statement` |
| `lrs-dispatch` | POST to LRS via HTTP Basic auth, retry once on 5xx | No | `post_to_lrs` |
| `confirmation` | Report statement_id, timestamp, success/error to user | Yes (format only) | — |

---

## Setup

**1. Set your LRS credentials as environment variables:**

```bash
export LRS_ENDPOINT="https://cloud.scorm.com/lrs/YOUR_LRS_KEY/statements"
export LRS_USERNAME="your_username"
export LRS_PASSWORD="your_password"
```

**2. Run the agent:**

```bash
# Single event via CLI flags
python -m xapi_learning_record run \
  --actor-name "Alice Chen" \
  --actor-mbox alice@example.com \
  --verb-id http://adlnet.gov/expapi/verbs/completed \
  --verb-display completed \
  --object-id https://example.com/activities/intro-python \
  --object-name "Introduction to Python" \
  --score-raw 85 --score-min 0 --score-max 100 --score-scaled 0.85 \
  --completion --success

# Interactive shell
python -m xapi_learning_record shell

# TUI dashboard
python -m xapi_learning_record tui

# Validate graph structure
python -m xapi_learning_record validate
```

**3. Override LRS credentials at runtime (optional):**

```bash
python -m xapi_learning_record run \
  --actor-name "Bob Li" \
  --actor-mbox bob@example.com \
  --verb-id http://adlnet.gov/expapi/verbs/attempted \
  --verb-display attempted \
  --object-id https://example.com/activities/quiz-1 \
  --object-name "Quiz 1" \
  --lrs-endpoint https://my-lrs.example.com/statements \
  --lrs-username myuser \
  --lrs-password mypass
```

---

## Example xAPI Statement (output of `build_xapi_statement`)

```json
{
  "id": "a3b4c5d6-e7f8-9012-abcd-ef1234567890",
  "actor": {
    "objectType": "Agent",
    "name": "Alice Chen",
    "mbox": "mailto:alice@example.com"
  },
  "verb": {
    "id": "http://adlnet.gov/expapi/verbs/completed",
    "display": {"en-US": "completed"}
  },
  "object": {
    "objectType": "Activity",
    "id": "https://example.com/activities/intro-python",
    "definition": {
      "name": {"en-US": "Introduction to Python"}
    }
  },
  "result": {
    "score": {"raw": 85, "min": 0, "max": 100, "scaled": 0.85},
    "completion": true,
    "success": true
  },
  "timestamp": "2026-03-18T14:30:00.000Z",
  "version": "1.0.3",
  "context": {"platform": "Hive"}
}
```

---

## Validation Rules (`validate_statement`)

| Check | Rule |
|---|---|
| Required fields | `id`, `actor`, `verb`, `object`, `timestamp`, `version` |
| `statement.id` | Valid UUID string |
| `actor.mbox` | `mailto:user@domain.tld` format |
| `actor` IFI | At least one of: `mbox`, `mbox_sha1sum`, `openid`, `account` |
| `verb.id` | Valid IRI (`scheme://...`) |
| `object.id` | Valid IRI (`scheme://...`) |
| `result.score.scaled` | Float in range `[0.0, 1.0]` |
| `timestamp` | Valid ISO 8601 datetime |
| `version` | Must be `"1.0.3"` |

---

## LRS Dispatch Behavior (`post_to_lrs`)

- Uses `urllib` (stdlib only — no additional dependencies)
- Sets `X-Experience-API-Version: 1.0.3` header
- HTTP 200 or 204 → success
- HTTP 5xx → retry once after 1 second
- HTTP 4xx → report error immediately, no retry
- Returns `{"statement_id": str, "success": bool, "error": str | None}`

---

## Sidecar Integration

This agent is designed to work alongside other Hive templates as a learning
analytics sidecar — recording interactions as xAPI statements without blocking
the primary agent flow.

### With Curriculum Research Agent (#5301)

The Curriculum Research Agent generates learning objectives and research
summaries. Each research session can be recorded as an xAPI statement:

```python
# After curriculum research completes, record the learning event
event = {
    "actor": {"name": learner_name, "mbox": f"mailto:{learner_email}"},
    "verb": {
        "id": "http://adlnet.gov/expapi/verbs/experienced",
        "display": "experienced",
    },
    "object": {
        "id": f"https://hive.example.com/activities/curriculum-research/{topic_slug}",
        "name": f"Curriculum Research: {topic}",
        "type": "http://adlnet.gov/expapi/activities/module",
    },
    "result": {"completion": True},
}
result = await xapi_agent.run({"learning_event": json.dumps(event)})
```

### With Document Intelligence A2A (#5523)

The Document Intelligence Agent Team analyzes documents through a Queen Bee +
Worker Bee A2A pattern. xAPI statements can record each document analysis
session as a `http://adlnet.gov/expapi/verbs/analyzed` interaction:

```python
event = {
    "actor": {"name": analyst_name, "mbox": f"mailto:{analyst_email}"},
    "verb": {
        "id": "https://hive.example.com/verbs/analyzed",
        "display": "analyzed",
    },
    "object": {
        "id": f"https://hive.example.com/activities/document/{doc_id}",
        "name": document_title,
        "type": "http://adlnet.gov/expapi/activities/assessment",
    },
}
result = await xapi_agent.run({"learning_event": json.dumps(event)})
```

The xAPI agent runs independently — it does not share state with the upstream
agent and can be instantiated with a different LRS endpoint per use case.

---

## Common xAPI Verb IRIs

| Verb | IRI |
|---|---|
| completed | `http://adlnet.gov/expapi/verbs/completed` |
| attempted | `http://adlnet.gov/expapi/verbs/attempted` |
| passed | `http://adlnet.gov/expapi/verbs/passed` |
| failed | `http://adlnet.gov/expapi/verbs/failed` |
| experienced | `http://adlnet.gov/expapi/verbs/experienced` |
| answered | `http://adlnet.gov/expapi/verbs/answered` |
| initialized | `http://adlnet.gov/expapi/verbs/initialized` |
| terminated | `http://adlnet.gov/expapi/verbs/terminated` |

Full verb registry: https://registry.tincanapi.com/

---

## Project Structure

```text
xapi_learning_record/
├── __init__.py          # Package exports
├── __main__.py          # CLI entry point (click)
├── agent.py             # XAPILearningRecordAgent class + goal + edges
├── agent.json           # Declarative graph spec
├── config.py            # LRS credentials (env vars) + RuntimeConfig + AgentMetadata
├── tools.py             # build_xapi_statement, validate_statement, post_to_lrs
├── flowchart.json       # Flowchart metadata
├── mcp_servers.json     # MCP server config
├── nodes/
│   └── __init__.py      # 5 NodeSpec definitions
├── tests/
│   ├── conftest.py      # Test fixtures (sys.path + session fixtures)
│   └── test_xapi_learning_record.py  # 23 structural tests
└── README.md            # This file
```
