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

### Validation Layer (Inter-Agent Handoff Gate)

Each Worker Bee output passes through a validation gate before entering synthesis:

| Worker Bee | Required fields | On failure |
|---|---|---|
| **Researcher** | entities list + confidence score (0–1) | Retry once → `LOW_CONFIDENCE` |
| **Analyst** | consistency_score + findings | Retry once → `UNVERIFIED` |
| **Strategist** | recommendations with priority | Retry once → `ADVISORY_ONLY` |

One worker failing validation does **not** halt the pipeline — the Coordinator proceeds
with remaining agents and annotates the report with `⚠️ PARTIAL_ANALYSIS`.
This implements the **circuit breaker pattern** for multi-agent reliability.

### Long-Term Memory (Cross-Session Pattern Retention)

The Coordinator uses `append_data`/`load_data` to maintain episodic memory across sessions:

- **Prior consensus ranges** for recurring document types seed new analyses
- **Outlier detection**: if a model consistently diverges, it is flagged in the log
- **Cold-start context**: the 3 most recent analyses are loaded before each new run

Memory files (stored in agent storage):
- `ltm_analyses.json` — structured analysis patterns per session
- `worker_behavior.jsonl` — per-worker reliability log (one line per session)

### Behavior Monitoring (Worker Reliability Tracking)

Each session logs worker behavior to `worker_behavior.jsonl`:

```json
{"worker": "researcher", "validation": "PASS", "confidence": 0.87, "was_outlier": false}
```

This addresses the **compound error probability problem**: tracking per-agent reliability
over time allows the Coordinator to calibrate synthesis confidence and flag models that
consistently underperform — before their errors cascade into the final report.

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
