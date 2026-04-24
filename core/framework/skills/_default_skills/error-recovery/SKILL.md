---
name: hive.error-recovery
description: Follow a structured recovery decision tree when tool calls fail instead of blindly retrying or giving up.
metadata:
  author: hive
  type: default-skill
  visibility: [worker]
---

## Operational Protocol: Error Recovery

When a tool call fails:

1. **Diagnose** — classify the failure as *transient* (network blip, rate limit, timeout) or *structural* (wrong selector, missing auth, invalid schema, permission denied).

2. **Decide:**
   - Transient → retry once.
   - Structural + fixable → fix the input and retry.
   - Structural + unfixable → record the failure and move to the next item.
   - Blocking all progress → escalate.

3. **Adapt** — if the same tool has failed {{max_retries_per_tool}}+ times in a row, stop using it and find an alternative approach.

**Never silently drop a failed item.** If the item is a task in the colony queue, write the failure to the DB instead of an in-memory buffer:

```bash
sqlite3 "$DB_PATH" "UPDATE tasks SET status='failed', last_error='<one-sentence reason>', completed_at=datetime('now'), updated_at=datetime('now') WHERE id='<task-id>' AND worker_id='<your-worker-id>';"
```

The `tasks.retry_count` column and the stale-claim reclaimer handle auto-retry for crashes; your job is the within-run decision tree above. See `hive.colony-progress-tracker` for the full queue protocol.
