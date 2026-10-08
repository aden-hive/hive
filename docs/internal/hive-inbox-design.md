# Hive Inbox — Design

**Status:** Draft for review
**Scope:** 3 repos — `hive-desktop-runtime` (Python runtime/framework), `hive-backend` (Express/TS cloud), `hive-desktop` (Electron app)
**Author:** design conversation, 2026-06-23

## 1. Summary

Hive Inbox is a **first-party, account-bound, two-way message channel between a user and their colonies** — the native peer of the existing Telegram and Slack Sentinel channels, but served by our own backend instead of a third party.

It replaces the framing of a passive "notification center": the channel carries a **conversation** (a parked colony asks → the user answers → the colony resumes), and because the **backend is the hub**, any authenticated client is a valid endpoint — the desktop Inbox view today, a mobile app and email later.

Hive Inbox becomes the **default Sentinel channel** for every colony. Because it is always connected for a signed-in account, `sentinel_enabled` reduces to "a channel is connected," which makes Sentinel effectively **on by default**. Telegram/Slack remain opt-in "also notify me on…" upgrades.

This builds on the existing Sentinel autopilot (`core/framework/sentinel/`). See `core/framework/sentinel/escalation_source.py` (the in-loop decision engine) and `core/framework/sentinel/manager.py` (delivery/routing/resume).

## 2. Decisions locked

| # | Decision | Choice |
|---|----------|--------|
| 1 | Product name / internal channel id | **Hive Inbox** / `hive` (replaces working title "notification center" and id `builtin`) |
| 2 | Reach | **Backend-served**; identical mechanism for local-subprocess and cloud (e2b) runtimes — cloud is just a different place the same runtime runs |
| 3 | Store | **New, dedicated user-scoped Postgres table** (`inbox_messages`), not the team-scoped Mongo `honeycomb_notifications` |
| 4 | Realtime transport | **SSE down + POST up** (backend→client push via SSE; client→backend via plain POST) |
| 5 | Reply routing | Runtime **self-registers** its live connection; replies route by the **originating `runtime_id` recorded on the message** (NOT a colony→runtime lookup) |
| 6 | Cloud runtime identity | `runtime_id` = `account_vm.e2b_sandbox_id` (set by the cloud spawner). The registry is a **separate `runtime_connections` table** keyed by `runtime_id` (see §6.2), reconciled to the sandbox id rather than physically co-located. Backend-side reconciliation / clear-on-terminate is a P1.5 follow-up — **not yet wired** (see §14). |
| 7 | Inbox scope | **User-scoped, team-visible** — owner is the primary recipient; teammates can read/answer as a fallback |

## 3. Architecture

```
                    ┌─────────────────── hive-backend (hub) ──────────────────┐
                    │  inbox_messages  (user-scoped, team-visible)            │
                    │  runtime_connections  (runtime_id → live SSE conn)      │
                    │  Redis pub/sub fan-out                                   │
                    └───▲────────────▲───────────────────────┬────────────────┘
   outbound: authed POST│            │ reply-stream (SSE)     │ push (SSE) + list/reply (POST)
   /v1/inbox/messages   │            │ runtime subscribes     │ devices subscribe
              ┌─────────┴───┐  ┌─────┴───────┐         ┌──────▼──────────────┐
              │ runtime     │  │ runtime     │         │ clients             │
              │ local subpr │  │ cloud e2b   │         │ desktop Inbox view  │
              │  colony A   │  │  colony B   │         │ (+ future mobile,   │
              └─────────────┘  └─────────────┘         │  email fallback)    │
                                                       └─────────────────────┘
```

The runtime — wherever deployed — POSTs to the backend when Sentinel escalates, and holds an **outbound SSE subscription** to receive replies (NAT-friendly; the backend cannot call into a local subprocess). The backend persists each message, fans it to the user's devices for display, and routes any reply back to the runtime that originated it.

## 4. The channel abstraction

A Sentinel channel must support six things; Hive Inbox slots in alongside Telegram/Slack (`core/framework/sentinel/notifier.py`, `core/framework/sentinel/listeners.py`):

| Capability | Telegram | Slack | **Hive (`hive`)** |
|---|---|---|---|
| Outbound delivery | httpx → Telegram API | httpx → Slack API | authed POST → backend `/v1/inbox/messages` |
| Inbound reply | `getUpdates` long-poll | Socket Mode WS | SSE reply-stream subscription |
| Thread/anchor | `message_id` | `ts` | backend `message_id` |
| Target addressing | `chat_id` | `channel` | account (user id from JWT) — implicit |
| Connected status | bot token set | tokens set | **signed in AND reply-stream open** |
| Listener lifecycle | poll task | socket task | SSE subscription task |

The symmetry with `TelegramListener` is the proof the abstraction holds: Hive Inbox's reply-stream is the same shape as Telegram's outbound long-poll, just pointed at our backend.

## 5. `sentinel_enabled` redefinition, defaults, migration

Today: `sentinel_enabled` defaults `False` and additionally requires a channel token (`core/framework/sentinel/store.py`). New model:

- **`channel` defaults to `hive`**, **`sentinel_enabled` defaults `True`** for any colony with no explicit config.
- `sentinel_enabled` now means **"a channel is connected"**; `hive` is always connected when signed in → on by default.
- Keep an explicit **off-switch** (disable Sentinel for a colony) and a **channel switch** (`hive` → telegram/slack, which still require that channel's token).
- **Migration (back-compat trap):** flipping the dataclass default changes behavior for every colony at once. Rule:
  - **missing `notifications.json` → `hive` + enabled**;
  - **existing file with explicit `sentinel_enabled`/`channel` is honored as-is** (users who turned it off, or set telegram, are untouched);
  - **absent `channel` on an existing file → resolve to `hive`**.

## 6. Data model

### 6.1 Backend — `inbox_messages` (new **Postgres** table, user-scoped, team-visible)

| Field | Notes |
|---|---|
| `id` | message id (also the anchor returned to the runtime) |
| `user_id` | **primary recipient** = colony owner (from runtime JWT `id`) |
| `team_id` | for team-visible fallback reads (from JWT `current_team_id`) |
| `runtime_id` | **originating runtime** — the routing key for replies |
| `session_id` | parked session to resume |
| `colony_id` | source colony (deep-link target) |
| `kind` | `blocker` \| `heartbeat` (mirrors `escalation_source.ESCALATE_*`) |
| `title`, `body` | rendered message |
| `correlation_token` | matches back to the runtime's escalation record |
| `status` | `open` \| `resolved` |
| `resolved_by` | user id / channel that answered |
| `read` | per-recipient read state — implemented as a **separate `inbox_message_reads` table** (absence of a row = unread), not a column, so each viewer has independent state |
| `created_at`, `deep_link`, `reply_text`, `resolved_at`, `updated_at` | timestamps + the stored answer |

`honeycomb_notifications` is **not** reused (team-scoped, Mongo, different lifecycle). Inbox uses **Postgres** to co-locate with `account_vm` and the runtime registry — transactional reads across messages + registry, and relational joins for the team-visible ACL.

### 6.2 Backend — runtime connection registry

A Postgres companion table (`runtime_connections`) keyed by `runtime_id`, holding **only** `runtime_id → live SSE connection` (+ presence). Does **not** map colony→runtime (that would drift against `account_vm_pushed_colonies`).

- **Cloud runtime:** `runtime_id = account_vm.e2b_sandbox_id`. Registration state is **keyed by `runtime_id` (the sandbox id), not by `team_id`** — see the cardinality principle below. It is reconciled to the sandbox record and cleared when that sandbox terminates (today: the same transaction as `DELETE /v1/workspace`, which already wipes `account_vm_pushed_colonies`).
- **Local runtime:** stable per-device `runtime_id`, self-registered fresh (no `account_vm` row exists for local).
- Presence/expiry mirrors the existing desktop→backend heartbeat / `last_heartbeat_at` staleness pattern (`account_vm`). A stale runtime = unreachable → its parked colonies' replies queue or fail gracefully.

**Cardinality principle — do not bake in one-sandbox-per-team.** `account_vm` today has PK `team_id` (one sandbox per team), but this is expected to become **multiple sandboxes per team**. The Inbox registry is therefore keyed by **`runtime_id`** (globally unique per sandbox/device) and **never by `team_id`**, so it already supports N runtimes per user/team. When `account_vm` goes multi-row (PK becomes `(team_id, e2b_sandbox_id)` or a child table), nothing in routing changes: replies still resolve `message.runtime_id → live connection`. The only adjustments at that point are operational — the "co-located with the sandbox record / clear-on-terminate" reconciliation moves from the single team row to the per-sandbox row, and `team_id` stays purely a scoping/visibility attribute, never a routing key.

### 6.3 Runtime — per-colony config (`notifications.json`)

Unchanged shape; new defaults (channel `hive`, enabled true). Add a stable `runtime_id` the runtime registers with each message.

## 7. Why routing can't drift

The authoritative answer to "where does this reply go?" is **the runtime that sent the escalation** — unambiguous and recorded on the message (`runtime_id`). Reply routing:

1. reply arrives (device → backend POST), carries the `message_id`;
2. backend loads the message → reads `runtime_id`;
3. resolve `runtime_id` → current live SSE connection in the registry;
4. push the reply down that stream → runtime `manager.on_inbound("hive", …)` → `_resume()` (unchanged, `manager.py`).

Deployment placement (`account_vm_pushed_colonies`) is **never consulted for routing**, so it cannot diverge from a second colony→runtime copy — there is no second copy.

## 8. Backend endpoints (new, `/v1/inbox/*`)

| Method | Path | Caller | Purpose |
|---|---|---|---|
| POST | `/v1/inbox/messages` | runtime | ingest an escalation (user_id/team_id from JWT) |
| GET | `/v1/inbox/messages` | device | list (own + team-visible), unread filter |
| GET | `/v1/inbox/stream` | device | **SSE** push of new/updated messages |
| POST | `/v1/inbox/messages/:id/reply` | device | user's answer |
| POST | `/v1/inbox/resolve` | runtime | cross-channel close (session answered in-app/elsewhere) — see §10 |
| POST | `/v1/inbox/messages/:id/read` | device | read state |
| POST | `/v1/inbox/messages/mark-all-read` | device | clear unread |
| GET | `/v1/inbox/messages/unread-count` | device | badge |
| GET | `/v1/inbox/runtime/stream` | runtime | **SSE** reply-stream + registers `runtime_id` (self-registration) |
| POST | `/v1/inbox/runtime/heartbeat` | runtime | presence keep-alive (mirrors workspace heartbeat) — **endpoint exists; runtime does not call it yet** (§14) |

Auth: JWT on all; `user_id`/`team_id` from the token; replies verified to belong to the message's `user_id` (or team for team-visible). Both auth schemes are accepted by the backend's passport strategy: the runtime sends `Authorization: Bearer <jwt>` (as `cloud_sync` does), the desktop sends `Authorization: jwt <jwt>`.

**Built but not consumed by P1 desktop:** `GET /v1/inbox/stream` (device SSE) exists, but the P1 desktop Inbox **polls** every 15s instead — consuming the SSE is a fast-follow (§14).

## 9. Per-repo work

### hive-backend
- `inbox_messages` table + repository (§6.1).
- Runtime connection registry + presence; cloud rows reconciled to `account_vm.e2b_sandbox_id`; clear-on-terminate in the existing `DELETE /v1/workspace` transaction.
- `/v1/inbox/*` endpoints (§8), SSE writer (pattern exists in `honeycomb.controller.ts`), Redis pub/sub fan-out (already used for session invalidation).
- Reply routing by `message.runtime_id` (§7).

### hive-desktop-runtime
- `CHANNEL_HIVE = "hive"` in `notifier.py`; add to `_VALID_CHANNELS`; make it the default.
- `notifier.send()` `hive` branch → authed POST to backend (reuse `HIVE_CLOUD_JWT` / `HIVE_CLOUD_BASE`, already wired in `core/framework/cloud_sync.py`). Returns backend `message_id` for anchoring.
- `HiveInboxListener` (mirror `TelegramListener`) — SSE subscription to `/v1/inbox/runtime/stream`, self-registers `runtime_id`, forwards to `manager.on_inbound("hive", …)`. Started by `manager.refresh_listeners()` whenever signed in. Replies are wrapped with the escalation's `(ref: token)` footer so they resolve through the existing `on_inbound` token path and `strip_ref` cleans them before injecting into the queen.
- Config defaults + migration (§5); stable `runtime_id`.

**Runtime identity contract (integration).** `runtime_identity.get_runtime_id()/get_runtime_kind()` resolve in this order: `HIVE_RUNTIME_ID`/`HIVE_RUNTIME_KIND` env → e2b sandbox id (`E2B_SANDBOX_ID`, ⇒ cloud) → a uuid persisted at `$HIVE_HOME/runtime_id` (⇒ local). **The spawners must set these:** the desktop app, when launching the local runtime subprocess, should pass `HIVE_RUNTIME_KIND=local` (id auto-persists); the backend cloud spawn must pass `HIVE_RUNTIME_ID=<e2b_sandbox_id>` + `HIVE_RUNTIME_KIND=cloud` so the runtime's `runtime_id` reconciles with `account_vm.e2b_sandbox_id`.
- **Suppression fix:** the UI-attached gate (`escalation_source.py`, `manager.has_attached_ui`) must become channel-aware — `hive` always posts to the Inbox (passive); only an OS toast is presence-gated. Telegram/Slack keep today's behavior.

### hive-desktop
- **Inbox view** — drawer/list subscribing to the **backend** `/v1/inbox/stream` (not the runtime); unread badge; per-entry deep-link to the colony; inline reply → `/v1/inbox/messages/:id/reply`. Reuse the OS-notification pattern in `src/renderer/src/hooks/use-away-queen-notifications.ts`.
- Sentinel setup UI (`SentinelSection.tsx`): `hive` shown as the default always-connected channel; telegram/slack demoted to advanced "also notify" options.
- The Inbox view is **one client** of the channel, not the channel itself (mobile/email are peers).

## 10. Flows

**Report (every evaluation):** Sentinel always tells the human *something* — escalation is just one report kind. `escalation_source._decide` picks a `kind`:
- `blocker` — judge says needs-human, or a hard/broken park; **parks for a reply**, notifies (loud).
- `done` — judge says the goal is **complete** (a real classifier verdict, never inferred from an empty task list); terminal report, notifies (quiet).
- `heartbeat` — auto-continued for `max_nudges` cycles; a louder checkpoint, parks.
- `progress` — judge says continue; an FYI of what the colony is doing **and** an internal nudge to keep it moving.

Each report → `notifier.send("hive", …)` → `inbox_messages` row → SSE fan-out. **`progress` is Inbox-feed-only** (never pushed to telegram/slack) and **does not toast**; `blocker`/`done`/`heartbeat` notify. Identical consecutive reports are de-duped. The idle budget before the first evaluation is **5 min** (`classify_after_seconds`).

**One open item per session (supersede).** Reports reuse the escalation record/row, which are "open until resolved" — so FYI reports (`progress`/`done`) would otherwise pile up as stale "open" rows. To keep the inbox a *live status* rather than a log, each new report **supersedes any prior open report for the same session**: resolved (`resolved_by='superseded'`) on both the runtime (`manager._handle_escalation`) and the backend (ingest calls `resolveBySession`). A `blocker` **holds** the source (stops evaluating until resume), so it is never superseded while awaiting a reply. The decision engine was also simplified — `_decide` returns a plain `kind`, the report path is one method, and the "hold" is a bool.

**Reply → resume:** device POSTs reply → backend loads message → routes by `runtime_id` to the live runtime SSE stream → `on_inbound` → `_resume` injects into the parked queen → backend marks `resolved`, fans the resolution to devices.

**Cross-channel resolution (implemented):** a Hive reply closes the row via the reply endpoint; answering **in-app** triggers `manager.on_local_resume`, which now also calls `POST /v1/inbox/resolve` (scoped by `session_id`, authed as the owner) to close the backend Hive row — so a colony answered in-app no longer lingers as a stale Inbox item. (A telegram/slack colony creates no Hive row, so there is nothing to cross-close for those.)

**Presence/expiry (live-connection-only today):** routing uses the **live SSE connection** (`runtime_connections` row presence is set at register and is *not* refreshed — the runtime does not heartbeat yet, and there is no staleness sweeper). So a reply to an offline runtime currently fails to deliver (`delivered:false` from the reply endpoint) rather than queuing; surfacing "this colony is offline" in the Inbox and the heartbeat/sweeper are P1.5 (§14).

## 11. What must be supported (checklist)

- [ ] Identical `hive` mechanism for local and cloud runtimes (backend-served).
- [ ] Default-on Sentinel via `hive`; explicit off-switch; back-compat migration (§5).
- [ ] Per-colony channel switch `hive` ↔ telegram/slack (additive: `hive` + telegram together is desirable).
- [ ] Two-way: outbound ingest + inbound reply → resume.
- [ ] Reply routing by originating `runtime_id` (no colony→runtime drift).
- [ ] Runtime self-registration + presence/expiry (mirror workspace heartbeat).
- [ ] Cloud `runtime_id` = `e2b_sandbox_id`, cleared with the sandbox lifecycle.
- [ ] Multi-runtime per account (local + cloud) routed correctly.
- [ ] User-scoped, team-visible store; read/unread, dismiss, history, unread count.
- [ ] Multi-colony aggregation; `blocker` vs `heartbeat` framing.
- [ ] Cross-channel resolution sync (Inbox / telegram / in-app).
- [ ] Channel-aware suppression (Inbox always posts; toast presence-gated).
- [ ] Security: user-scoped isolation, team-visible fallback ACL, reply sender verified.
- [ ] Multi-client ready: desktop now; mobile + email as peer clients on the same channel.

## 12. Phasing

- **P1 — channel end-to-end:** backend `inbox_messages` + `/v1/inbox/*` + SSE; runtime `hive` notifier + `HiveInboxListener` + self-registration + defaults; desktop Inbox view + reply. Covers local and cloud uniformly (per decision #2). Ships the core vision.
- **P2 — reach + polish:** email fallback (reuse SendGrid/Mailjet) for away/offline; presence-aware toast tuning; cross-channel resolution sync hardening.
- **P3 — mobile app** as a peer client on the same `/v1/inbox/*` channel.

## 13. Open items / risks

- **Multiple sandboxes per team is an anticipated evolution**, not just a risk: `account_vm` is one-per-team today but expected to go multi-row. The design absorbs this by routing on `runtime_id` and never on `team_id` (see the cardinality principle in §6.2) — the registry must allow multiple live `runtime_id`s per user/team from day one, even while `account_vm` is still one-per-team.
- **Reverse-connection infra is new** to the backend (no runtime→backend stream exists today) — the largest backend build item; mirror the existing heartbeat/idle-sweeper lifecycle.
- **Team-visible ACL** rules (who may answer, dedupe when two teammates reply) need precise definition in P1.
- **Local runtime offline** = parked local colony cannot resume until the app reopens; surface this state honestly in the Inbox.

## 14. Implementation status (as built)

Reconciled against the code on branch `feature/hive-inbox`. Verified by `tsc`, the runtime sentinel unit suite, and a real e2e against the dev backend (real Postgres + Redis + account JWT).

**Done (P1 spine):**
- Backend: migration `034_inbox.sql` (`inbox_messages`, `inbox_message_reads`, `runtime_connections`), `inbox-db.service.ts`, `inbox-realtime.service.ts` (Redis single-channel fan-out + in-process SSE registry), `inbox.controller.ts`, wired in `app.ts`.
- Runtime: `CHANNEL_HIVE` + `_send_hive` + `resolve_hive_session`, `runtime_identity.py`, `HiveInboxListener`, default-on migration, channel-aware suppression, `on_local_resume` cross-channel close.
- Desktop: `api/inbox.ts`, `InboxButton.tsx` (badge + drawer + reply + OS notification), `hive` in the Sentinel config types.
- **Web dashboard** (`open-hive-site`, Nuxt 3): `composables/useInbox.ts` + `components/Dashboard/InboxBell.vue` (header bell + badge + dropdown + reply, polling) mounted in `Dashboard/User.vue` — a second peer client of the same `/v1/inbox/*` channel, proving the multi-client design (desktop + web today; mobile/email later).
- **Cross-channel resolution** (§10) — in-app resume closes the backend row.
- **Report-everything model** (§10) — Sentinel reports on every evaluation (`blocker`/`progress`/`done`/`heartbeat`), not just blockers. Completion is **judged** via a new classifier `done` verdict (replacing the earlier deterministic "TURN_DONE + no tasks" guess). Idle budget lowered to **5 min**. `progress` is feed-only + non-notifying; de-duped.

**Pending DB step:** `kind` widened to `blocker|heartbeat|progress|done` via migration **`035_inbox_report_kinds.sql`** — written but **not yet applied** to the dev DB (needs explicit authorization; applies on next backend boot). Until applied, a `progress`/`done` ingest would be rejected by the old CHECK constraint.

**Divergences from the original design (intentional P1 scope):**
- **Device display polls** (15s) instead of consuming `GET /v1/inbox/stream` SSE (decision #4 / §9). The endpoint exists; the runtime reply path is real SSE.
- **Sentinel setup UI** surfaces `hive` only minimally (status label + types); the modal does not yet present `hive` as the default channel or demote telegram/slack (§9).
- **Deep-link to colony** from an Inbox entry is not wired (notification just focuses the window; `deep_link` sent as `null`) (§9).
- **Team-visible is read-on-refresh, not live**: live push goes to the owner's devices only; teammates see team-visible rows on list (§10/§11).

**Not yet built (P1.5 / correctness debt to close before "done"):**
- **Cloud `runtime_id` ↔ `account_vm` reconciliation + clear-on-terminate** — `account_vm` is untouched; a terminated sandbox leaves a stale `runtime_connections` row (decision #6 / §6.2).
- **Presence/expiry operationally** — `runtime_connections.last_heartbeat_at` is set at register and never refreshed; the runtime does not call `POST /runtime/heartbeat`, and there is no sweeper. Routing tolerates this (it uses the live connection), but DB presence is not trustworthy yet (§6.2/§10).
- **Spawner env contract** — desktop must launch the local runtime with `HIVE_RUNTIME_KIND=local`; the backend cloud-spawn must set `HIVE_RUNTIME_ID=<e2b_sandbox_id>` + `HIVE_RUNTIME_KIND=cloud` (§9). Without these, replies can't route.
