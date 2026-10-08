# Frontend Cleanup — Trigger System Simplification

The backend has collapsed the colony-lifecycle layer. Several pieces
of UI the frontend was asked to build (or has already built) are now
dead and should be removed. One new (small) piece of UI takes their
place: the missed-trigger handshake on session load.

This doc is organized as **Remove → Keep → Add → Migration checklist**.

---

## Remove

### Endpoints — gone

| Endpoint | Status |
|---|---|
| `GET    /api/sessions/{id}/colony/state` | **404** |
| `POST   /api/sessions/{id}/colony/activate` | **404** |
| `POST   /api/sessions/{id}/colony/deactivate` | **404** |

Any frontend code that fetches the colony's lifecycle through these
URLs needs to go. The information they exposed (loaded / active /
busy) was either redundant with the existing session signals or
artificial.

### Events — gone

| Event type | Status |
|---|---|
| `colony_activated` | no longer emitted |
| `colony_deactivated` | no longer emitted |
| `activation_missed_triggers` | renamed → `missed_triggers` |

Unsubscribe and delete the handlers for the first two. Subscribe to
the renamed `missed_triggers` event under its new name (details
below).

### Tool-response fields — gone

The queen's `set_trigger` tool no longer returns `colony_active`
on its response, and no longer returns the `"queued_for_next_activation"`
status string. The `trigger_activated` event payload also dropped the
`colony_active` field.

The response is now consistently `{ status: "activated", ... }` —
the trigger is registered and (because the session is loaded by
definition when the queen can call the tool) is firing.

### UI components — remove

- **Activate / Deactivate toggle** on the colony header.
  Loading the colony view *is* the activation; closing it *is* the
  deactivation. The toggle was duplicating the existing
  open/close-colony interaction.
- **"Active since …" badge** driven by `metadata.last_active_at`.
  That field no longer exists on disk. If you need a "session
  started at" stamp, the existing `loaded_at` on the session
  response covers it.
- **"Queued for next activation" indicator card** in the queen's
  transcript. There is no more queued middle state; a trigger is
  either configured (and runs while the session is open) or
  disabled/removed.
- **Sidebar dot that distinguished "loaded" from "active"**.
  Collapse to one dot: is the session currently loaded.

### `metadata.json` fields — gone

`metadata.active` and `metadata.last_active_at` are no longer written
by the backend. Anything that reads them client-side should be
removed — they are not part of the contract.

---

## Keep

The trigger system itself is unchanged. Everything below still works
exactly as before:

- **Trigger CRUD UI** — `set_trigger` / `remove_trigger` / `list_triggers`
  via the queen, plus the existing per-trigger HTTP routes
  (`/triggers/{id}/activate`, `/triggers/{id}/deactivate`,
  `/triggers/{id}/run`, `PATCH /triggers/{id}`).
- **`trigger_fired` event** — fires whenever a configured trigger
  fires (or whenever `resolve_missed` injects a catch-up). Render as
  before.
- **`trigger_available`, `trigger_activated`, `trigger_deactivated`,
  `trigger_removed`, `trigger_updated`** — still emitted for trigger
  CRUD. Same shape minus the `colony_active` field call-out above.
- **`triggers.json` per-trigger fields** — `id`, `name`,
  `trigger_type`, `trigger_config`, `task`, `enabled`,
  `last_fired_at`, `next_due_at`. Note `enabled` is the field name
  (the older `active` per-trigger name is gone).

---

## Add

### Subscribe to `missed_triggers`

On session load, if any enabled timer trigger has a stale
`last_fired_at` (i.e. cron / interval ticks would have fired while
the session was closed), a single `missed_triggers` event lands on
the session's SSE stream:

```json
{
  "type": "missed_triggers",
  "stream_id": "queen",
  "data": {
    "colony_id": "...",
    "missed": [
      {
        "trigger_id": "daily_outreach",
        "trigger_type": "timer",
        "count": 3,
        "ticks": [
          "2026-05-19T09:00:00+00:00",
          "2026-05-20T09:00:00+00:00",
          "2026-05-21T09:00:00+00:00"
        ],
        "next_due_at": "2026-05-22T09:00:00+00:00"
      }
    ]
  }
}
```

- `count` is the true total of missed ticks.
- `ticks` is capped at 100 entries — render `count` faithfully but
  truncate the list display if you show timestamps individually.
- `next_due_at` is the next future fire if the user does nothing.
- Webhook triggers are never reported (event-driven, no schedule to
  reconstruct).
- All timestamps are UTC ISO 8601 with explicit `+00:00`/`Z` suffix.
  Convert to local time at render via
  `new Date(iso).toLocaleString()` — do **not** display the raw UTC
  string.

### Show the "Catch up?" modal

Recommended shape:

- Title: *Catch up while you were away?*
- Subtitle: brief explanation that triggers don't fire while the
  colony is closed.
- For each row in `missed`:
  - Trigger name, missed count, "next due at <local time>".
  - Three buttons: *Fire latest* / *Skip* / *Reschedule*.
- One "Apply" button that POSTs the collected decisions.

### POST to `/colony/resolve_missed`

```
POST /api/sessions/{session_id}/colony/resolve_missed
Body: { "decisions": { "<trigger_id>": "fire_latest" | "skip" | "reschedule", ... } }
```

Per-trigger decision semantics:

- **`fire_latest`** — inject one catch-up trigger event into the
  queen (payload includes `catch_up: true` so she can compress
  workload). Advances `last_fired_at` to now.
- **`skip`** — advance `last_fired_at` to now without firing.
- **`reschedule`** — advance `last_fired_at` to now and recompute
  `next_due_at` to the next future tick. No fire.

**Response 200:**
```json
{
  "results": {
    "daily_outreach": "fired",
    "hourly_check":   "skipped",
    "ghost":          "unknown_trigger",
    "bad":            "invalid_decision:explode"
  }
}
```

The handler never fails the request on one bad row — show partial
success in the UI rather than aborting.

**Status codes:**
- `200` — request processed (read per-trigger `results`)
- `400` — `decisions` not an object
- `404` — unknown session
- `409` — session has no colony bound

---

## Migration checklist

- [ ] Remove all calls to `/api/sessions/{id}/colony/state`,
      `/activate`, `/deactivate`.
- [ ] Unsubscribe from `colony_activated`, `colony_deactivated`,
      `activation_missed_triggers`.
- [ ] Subscribe to `missed_triggers` (note the rename).
- [ ] Delete the Activate/Deactivate toggle component.
- [ ] Delete the "Active since…" badge.
- [ ] Delete the queen-transcript "queued for next activation"
      card; the queen tool no longer returns that status string.
- [ ] Stop reading `metadata.active` / `metadata.last_active_at`.
- [ ] Stop reading `colony_active` off `trigger_activated` and
      `set_trigger` responses.
- [ ] Sidebar dot: simplify to a single state (session loaded vs
      not), no per-colony lifecycle.
- [ ] Add the missed-trigger handshake modal and wire it to
      `POST /colony/resolve_missed`.

## Why we removed it

Short version: the four states the frontend was reconciling
(`loaded`, `metadata.active`, per-trigger `active`, `is_executing`)
collapsed to one user-facing question — "is the session for this
colony loaded?" — plus a per-trigger `enabled` config flag for power
users. Everything else was artificial layering. Loading the colony
*is* activating it; closing it *is* deactivating it.

Triggers fire **iff the colony's session is loaded** and the
trigger's `enabled` flag is true. No additional lifecycle toggle, no
"paused but loaded" state.
