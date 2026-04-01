---
name: hive.context-preservation
description: Proactively preserve critical information before automatic context pruning destroys it.
metadata:
  author: hive
  type: default-skill
---

## Operational Protocol: Context Preservation

You operate under a finite context window. Important information WILL be pruned.

Save-As-You-Go: After any tool call producing information you'll need later,
immediately extract key data into `_working_notes` or `_preserved_data`.
Do NOT rely on referring back to old tool results.

What to extract: URLs and key snippets (not full pages), relevant API fields
(not raw JSON), specific lines/values (not entire files), analysis results
(not raw data).

Before transitioning to the next phase/node, write a handoff summary to
`_handoff_context` with everything the next phase needs to know.

You will receive an alert when context reaches {{warn_at_usage_ratio_pct}}% — preserve immediately.
