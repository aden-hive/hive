# Document Intelligence Agent Team

> **First Hive template implementing the Queen Bee + Worker Bees (A2A) coordination pattern.**

## Architecture

```
User Input
    ↓
[Intake]           ← Client-facing: receive document, clarify needs
    ↓
[Coordinator]      ← Queen Bee: delegates to 3 Worker Bees
    → delegate_to_sub_agent("researcher", task)
    → delegate_to_sub_agent("analyst", task)
    → delegate_to_sub_agent("strategist", task)
    → Cross-reference findings, generate report
    ↓
[Intake]           ← Forever-alive loop

Sub-agents (no edge connections):
[researcher]       ← Worker Bee: entity/fact extraction
[analyst]          ← Worker Bee: consistency/contradiction detection
[strategist]       ← Worker Bee: risk/impact assessment
```

## Key Concepts

### A2A Coordination via `delegate_to_sub_agent`

Unlike linear pipeline agents, this template uses Hive's native sub-agent mechanism:

- **Coordinator** declares `sub_agents=["researcher", "analyst", "strategist"]`
- Each Worker Bee runs in an **isolated conversation context** with its own system prompt
- Workers can use `report_to_parent()` for progress updates
- Each worker can optionally use a **different LLM model** for cross-model verification

### Multi-Model Cross-Reference

Configure per-worker models in `config.py`:

```python
from document_intelligence_agent_team.config import worker_models

worker_models.researcher = "claude-sonnet-4-20250514"
worker_models.analyst = "gpt-4o"
worker_models.strategist = "gemini-2.0-flash"
```

## Usage

```bash
# Show agent info
python -m document_intelligence_agent_team info

# Validate graph structure
python -m document_intelligence_agent_team validate

# Launch TUI dashboard
python -m document_intelligence_agent_team tui

# Interactive shell
python -m document_intelligence_agent_team shell

# Run with document
python -m document_intelligence_agent_team run --document "Your document text here"
```

## Nodes

| Node | Role | Client-Facing | Sub-Agents |
|------|------|:---:|------------|
| `intake` | Document intake | ✅ | — |
| `coordinator` | Queen Bee | ✅ | researcher, analyst, strategist |
| `researcher` | Worker Bee | ❌ | — |
| `analyst` | Worker Bee | ❌ | — |
| `strategist` | Worker Bee | ❌ | — |

## Related

- [Hive Roadmap — Queen Bee / Worker Bee](../../docs/roadmap.md)
- [Issue #5523](https://github.com/aden-hive/hive/issues/5523)
