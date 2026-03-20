---
name: hive.error-recovery
description: Follow a structured recovery protocol when tool calls fail instead of blindly retrying or giving up.
metadata:
  author: hive
  type: default-skill
---

## Operational Protocol: Error Recovery

When a tool call fails:

1. Diagnose — record error in notes, classify as transient or structural
2. Decide — transient: retry once. Structural fixable: fix and retry.
   Structural unfixable: record as failed, move to next item.
   Blocking all progress: record escalation note.
3. Adapt — if same tool failed 3+ times, stop using it and find alternative.
   Update plan in notes. Never silently drop the failed item.
