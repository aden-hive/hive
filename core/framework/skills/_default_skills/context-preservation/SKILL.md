---
name: hive.context-preservation
description: Proactively extract critical values from tool results into working notes before automatic context pruning destroys them.
metadata:
  author: hive
  type: default-skill
---

## Operational Protocol: Context Preservation

You operate under a finite context window. Older tool results WILL be pruned. Extract what you need while it's still in context.

**Save-as-you-go.** After any tool call producing information you'll need later, immediately extract the key data into `_working_notes` or `_preserved_data`. Do not rely on referring back to old tool results — once they're pruned they're gone.

**What to extract:**
- URLs and key snippets (not full pages)
- Relevant API fields (not raw JSON blobs)
- Specific lines, values, or IDs (not entire files)
- Analysis conclusions (not raw data)

**Handoffs between tasks** happen through `progress.db`, not through shared-buffer handoff blobs. When you finish a task, any state the next worker needs goes into the task row itself (`steps.evidence`, `tasks.last_error`, `sop_checklist.note`) — see `hive.colony-progress-tracker`. Use `_working_notes` for things the DB schema doesn't cover.

You will receive an alert when context reaches {{warn_at_usage_ratio_pct}}% — preserve immediately.
