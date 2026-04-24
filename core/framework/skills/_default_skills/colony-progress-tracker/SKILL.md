---
name: hive.colony-progress-tracker
description: Claim tasks, record step progress, and verify SOP gates in the colony SQLite queue. Applies when your spawn message includes a db_path field.
metadata:
  author: hive
  type: default-skill
  visibility: [worker]
---

## Operational Protocol: Colony Progress Tracker

**Applies when** your spawn message has `db_path:` and `colony_id:` fields. The DB is your durable working memory — tells you what's done, what to skip, which SOP gates you owe.

Access via `execute_command_tool` running `sqlite3 "<db_path>" "..."`. Tables: `tasks` (queue), `steps` (per-task decomposition), `sop_checklist` (hard gates).

### Claim: assigned task (check this FIRST)

If your spawn message includes a `task_id:` field, the queen pre-assigned a specific row to you. Claim that row by id — **do not** use the generic next-pending pattern below:

```bash
sqlite3 "<db_path>" <<'SQL'
UPDATE tasks SET status='claimed', worker_id='<worker-id>',
  claim_token=lower(hex(randomblob(8))),
  claimed_at=datetime('now'), updated_at=datetime('now')
WHERE id='<task_id>' AND status='pending'
RETURNING id, goal, payload;
SQL
```

Empty output → another worker raced you or the row is already done. Stop and report.  Non-empty → that row is yours, proceed to "Load the plan".

### Claim: next pending (fallback when no task_id is assigned)

If your spawn message did NOT include `task_id:` — you are a generic fan-out worker racing on a shared queue. Use the generic next-pending claim:

```bash
sqlite3 "<db_path>" <<'SQL'
UPDATE tasks SET status='claimed', worker_id='<worker-id>',
  claim_token=lower(hex(randomblob(8))),
  claimed_at=datetime('now'), updated_at=datetime('now')
WHERE id=(SELECT id FROM tasks WHERE status='pending'
  ORDER BY priority DESC, seq, created_at LIMIT 1)
RETURNING id, goal, payload;
SQL
```

Empty output → queue drained, exit. Otherwise the returned `id` is yours. **Never SELECT-then-UPDATE** — races.

### Load the plan

```bash
sqlite3 "<db_path>" "SELECT seq, id, title, status FROM steps WHERE task_id='<task-id>' ORDER BY seq;"
sqlite3 "<db_path>" "SELECT key, description, required, done_at FROM sop_checklist WHERE task_id='<task-id>';"
```

**Skip any step where status='done'.** That's the point — don't redo completed work.

### Execute a step

Before tool calls:
```bash
sqlite3 "<db_path>" "UPDATE steps SET status='in_progress', worker_id='<worker-id>', started_at=datetime('now') WHERE id='<step-id>';"
```
After success (one-line evidence: path, URL, key result):
```bash
sqlite3 "<db_path>" "UPDATE steps SET status='done', evidence='<what you did>', completed_at=datetime('now') WHERE id='<step-id>';"
```

### MANDATORY: SOP gate check before marking task done

```bash
sqlite3 "<db_path>" "SELECT key, description FROM sop_checklist WHERE task_id='<task-id>' AND required=1 AND done_at IS NULL;"
```

- Empty → proceed to "Mark task done".
- Non-empty → each row is work you still owe. Do it, then check it off:

```bash
sqlite3 "<db_path>" "UPDATE sop_checklist SET done_at=datetime('now'), done_by='<worker-id>', note='<why>' WHERE task_id='<task-id>' AND key='<key>';"
```

**Never mark a task done while this SELECT returns rows.** This gate exists specifically to stop you from declaring success while skipping required steps.

### Mark task done / failed

```bash
# Success:
sqlite3 "<db_path>" "UPDATE tasks SET status='done', completed_at=datetime('now'), updated_at=datetime('now') WHERE id='<task-id>' AND worker_id='<worker-id>';"

# Unrecoverable failure:
sqlite3 "<db_path>" "UPDATE tasks SET status='failed', last_error='<one sentence>', completed_at=datetime('now'), updated_at=datetime('now') WHERE id='<task-id>' AND worker_id='<worker-id>';"
```

The `AND worker_id=?` guard means a reclaimed row won't accept your write — treat zero rows affected as "your claim was revoked, stop."

### Loop

After done/failed → claim the next task. Exit only when claim returns empty.

### Errors + debug

- **"database is locked"**: retry with 100ms → 1s backoff, max 5 attempts. `busy_timeout=5000` handles most contention silently.
- **Queue health**: `SELECT status, count(*) FROM tasks GROUP BY status;`
- **Your in-flight work**: `SELECT id, goal, status FROM tasks WHERE worker_id='<worker-id>';`

### Anti-patterns (will break the queue)

- Don't DDL (CREATE/ALTER/DROP).
- Don't DELETE — failed tasks stay as `failed` for audit.
- Don't skip Protocol 4 (SOP gate) before marking done.
- Don't hold a task >15min without updates — the stale-claim reclaimer revokes your claim.
- Don't invent task IDs. Workers update existing rows; only the queen enqueues new ones.
