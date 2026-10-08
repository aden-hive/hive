# Handover: Detecting task-system updates per session (frontend)

**Audience:** frontend engineer building/maintaining the Action Plan panel.
**Goal:** know exactly when a session's task list changes so the UI can refresh
for the user — without polling.

---

## TL;DR

1. Each session owns **exactly one** task list, keyed by `session_id`.
2. Subscribe to the session SSE stream: `GET /api/sessions/{session_id}/events`.
3. React to four event types: `task_created`, `task_updated`, `task_deleted`,
   `task_list_reset`.
4. **Task events are NOT replayed on reconnect.** On connect (and reconnect),
   fetch the snapshot `GET /api/sessions/{session_id}/tasks` first, then apply
   live events on top.

---

## 1. How tasks are scoped to a session

There is no separate task-list identifier — a task list **is** the session's
list, and the `session_id` is the only key needed. The on-disk location is
resolved server-side by scanning the canonical session-folder layouts (queen
DM, queen overseer, worker); the frontend never composes a path.

Every task event payload carries `session_id` explicitly, so the frontend
can match an event to the panel it belongs to without any parsing.

---

## 2. The SSE channel

Route: `GET /api/sessions/{session_id}/events`
Source: [`routes_events.py`](../core/framework/server/routes_events.py)

The four task event types are already in `DEFAULT_EVENT_TYPES`, so an
unfiltered subscription receives them. If you pass a `?types=` filter, you
must include them explicitly:

```
/api/sessions/{session_id}/events?types=task_created,task_updated,task_deleted,task_list_reset
```

Keepalives arrive every 15s. On disconnect, reconnect and re-snapshot (see §4).

---

## 3. The task events and their payloads

All emitted from [`tasks/events.py`](../core/framework/tasks/events.py). Each
event is **one task** — a batch creation of N tasks fires N separate
`task_created` events.

Envelope (all task events): `type`, `stream_id` (`"primary"`), `data`,
`timestamp`, `seq` (monotonic — use it to dedupe). `node_id`,
`execution_id`, `correlation_id`, `colony_id`, `run_id` are unset.

### `task_created`
```jsonc
{
  "type": "task_created",
  "data": {
    "session_id": "session_<timestamp>_<uuid>",
    "task": { /* full task record — see §3.1 */ }
  }
}
```

### `task_updated`
```jsonc
{
  "type": "task_updated",
  "data": {
    "session_id": "...",
    "task_id": 7,
    "after": { /* full task record, post-update */ },
    "fields": ["status"]   // which fields changed
  }
}
```
`fields` tells you what changed (`status`, `description`, etc.) — useful for
targeted re-render. Note `task_updated` is **not emitted when `fields` is
empty**.

### `task_deleted`
```jsonc
{
  "type": "task_deleted",
  "data": {
    "session_id": "...",
    "task_id": 7,
    "cascade": [8, 9]   // dependent task ids also removed
  }
}
```
Remove `task_id` **and** every id in `cascade`.

### `task_list_reset`
Declared and already in the SSE default set, but **not emitted by the backend
today**. Handle it defensively (treat as "drop local state and re-snapshot"),
but do not depend on it firing yet.

### 3.1 Task record shape

`task_created.data.task` and `task_updated.data.after` use the same shape
(`_serialize_record`):

```jsonc
{
  "id": 7,
  "subject": "string",
  "description": "string",
  "active_form": "string",       // present-tense label, e.g. "Searching LinkedIn"
  "owner": "string",
  "status": "pending|in_progress|completed|abandoned|...",  // string enum value
  "blocks": [8, 9],              // task ids this one blocks
  "blocked_by": [3],             // task ids blocking this one
  "metadata": { },
  "created_at": "...",
  "updated_at": "..."
}
```

---

## 4. The reconnect gap — important

The SSE handler replays buffered history on connect, but **task events are
NOT in the replay set** (`_REPLAY_TYPES` in `routes_events.py`). Only
chat/execution/trigger events are replayed.

Consequence: if the SSE connects *after* tasks were created (page load,
reconnect, tab restore), those `task_created` events are already gone — the
panel would be empty or stale.

**Required pattern:**

1. On SSE connect/reconnect, call `GET /api/sessions/{session_id}/tasks` for
   the authoritative snapshot.
2. Apply live SSE events on top, deduping by event `seq`.
3. Treat the snapshot as truth on every reconnect; never assume the live
   stream alone is complete.

### Snapshot endpoint

`GET /api/sessions/{session_id}/tasks` → [`routes_tasks.py`](../core/framework/server/routes_tasks.py)

```jsonc
{
  "session_id": "...",
  "role": "session",
  "meta": { /* list metadata, may be null */ },
  "tasks": [ /* array of task records, same shape as §3.1 */ ]
}
```

- `404` with `"tasks": []` if the list does not exist yet (no tasks created).
- The snapshot call also lazily sweeps stale `in_progress` tasks to
  `abandoned` and emits `task_updated` for each — so calling it can itself
  produce SSE events. That's expected; just apply them.

---

## 5. Recommended frontend flow

```
on session open / SSE (re)connect:
  1. open SSE: /api/sessions/{sessionId}/events
  2. snapshot:  GET /api/sessions/{sessionId}/tasks
  3. render panel from snapshot.tasks

on SSE event (dedupe by seq):
  task_created  -> upsert data.task into list, open panel if first task
  task_updated  -> replace task data.task_id with data.after (use data.fields
                   to scope re-render)
  task_deleted  -> remove data.task_id and all data.cascade ids
  task_list_reset -> clear list, re-snapshot (defensive; not emitted today)

on SSE disconnect:
  reconnect, then re-run snapshot (step 2) — task events are not replayed
```

### Gotchas

- **No batch event.** N tasks created together = N `task_created` events.
  Debounce panel render if needed.
- **Dedupe by `seq`.** The same event can reach you via both live stream and
  (for replayed types) history; task events aren't replayed, but the snapshot
  + live stream overlap, so reconcile by task `id` and event `seq`.
- **Match on `data.session_id`.** If the UI ever shows multiple sessions,
  route each event to the right panel by its `session_id`.
- **Worker tasks.** Worker streams are filtered out of the session SSE in DM
  mode. Worker task activity is only visible via the per-worker route
  `/api/workers/{worker_id}/events`. Session-scoped tasks are unaffected.

---

## Source references

- Event emit + payload shapes: [`core/framework/tasks/events.py`](../core/framework/tasks/events.py)
- SSE route, default/replay sets: [`core/framework/server/routes_events.py`](../core/framework/server/routes_events.py)
- Snapshot route: [`core/framework/server/routes_tasks.py`](../core/framework/server/routes_tasks.py)
- Event enum: [`core/framework/host/event_bus.py`](../core/framework/host/event_bus.py) (`EventType.TASK_*`)
