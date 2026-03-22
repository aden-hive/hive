# Slash Commands — Frontend Chat UI Plan

## Background

The Hive frontend has a slash command system that end users type into the chat input box on the home page. Currently only `/resume` exists. This document plans out the full set of essential commands.

---

## How the System Currently Works

**Location:** `core/frontend/src/pages/home.tsx`

The slash command system lives entirely on the **home page** (landing screen with the agent input box).

```typescript
// home.tsx ~line 120 — command registry
const SLASH_COMMANDS = [
  { id: "resume", label: "resume", description: "Continue a previous session", Icon: RotateCcw },
] as const;
```

**UX flow:**
1. User types `/` → `handleInputChange` detects it → `slashMenuOpen = true`
2. Autocomplete dropdown appears above textarea with icon + label + description
3. Arrow keys navigate, Enter selects, Escape closes
4. `handleSlashSelect(id)` routes to the right handler

**`/resume` currently does:**
1. Opens a session picker modal
2. Calls `sessionsApi.history()` — fetches all live + cold sessions
3. Groups by date (Today / Yesterday / Last 7 days / Older), searchable
4. User picks → navigates to `/workspace?agent=<path>&session=<id>`

**Key finding:** The workspace chat (`workspace.tsx` `handleSend()`) has **no slash command parsing today** — commands only work on the home page. Workspace-level commands require adding a new slash detection layer there.

---

## Critical Files

| File | Role |
|------|------|
| `core/frontend/src/pages/home.tsx` | All current slash command logic (~lines 120–360) |
| `core/frontend/src/pages/workspace.tsx` | `handleSend()` ~line 2759 — intercept point for workspace commands |
| `core/frontend/src/components/ChatPanel.tsx` | Chat input textarea + submit handler |
| `core/frontend/src/api/execution.ts` | `pause`, `stop`, `cancelQueen`, `resume`, `replay`, `goalProgress` |
| `core/frontend/src/api/sessions.ts` | `history`, `workerSessions`, `checkpoints`, `stats`, `entryPoints` |
| `core/frontend/src/api/logs.ts` | `summary`, `details`, `tools` level log fetchers |

---

## Commands

Split into two groups based on where they live.

---

### Group A — Home Page Commands

Add to existing `SLASH_COMMANDS` array and `handleSlashSelect()` in `home.tsx`. These apply before/between sessions.

---

#### `/new` — Browse agents and start a fresh session

**Why:** `/resume` covers returning users; there's no quick command to browse and launch a new agent. Complements `/resume` as the "start fresh" counterpart.

**UX flow:**
1. Open agent picker modal
2. Calls `agentsApi.discover()` → shows agents grouped by category
3. User selects agent → navigates to `/workspace?agent=<path>` (no session ID = fresh session)

**Backend:** `GET /api/discover` ✅

---

#### `/history` — Browse all past sessions (read-only)

**Why:** Sometimes users want to look at a past run — read its output, find something — without resuming or re-running it. `/resume` always opens in workspace; `/history` is a lighter read-only view.

**UX flow:**
1. Open history modal — same session list as `/resume` (calls `sessionsApi.history()`)
2. Shows last message preview, status badge, elapsed duration per session
3. Selecting a session navigates to workspace in read-only/view mode (worker not re-loaded unless explicitly resumed)

**Backend:** `GET /api/sessions/history` ✅

---

### Group B — Workspace Chat Commands

These require a new slash command layer inside the workspace. Implementation involves:

1. **Autocomplete dropdown in `ChatPanel.tsx`** — same pattern as `home.tsx`: watch textarea input, show dropdown when text starts with `/`
2. **Intercept in `workspace.tsx` `handleSend()`** — before `executionApi.chat()` is called, check `text.startsWith("/")` and dispatch to the right handler
3. **Availability rules** — commands show/hide based on current state (see table below)

---

#### `/pause` — Pause the current worker execution

**Why:** The most common in-run control action. User sees the agent going off-track mid-run and wants to pause without fully stopping. Currently requires using the UI buttons, which may not be visible in chat-focused mode.

**UX flow:**
1. Immediate action — no modal
2. Calls `executionApi.pause(sessionId, activeExecutionId)`
3. Toast: *"Execution paused. Type /resume to continue."*
4. Queen phase transitions to `staging`

**Available when:** `workerRunState === "running"`

**Backend:** `POST /api/sessions/{id}/pause` ✅

---

#### `/stop` — Stop the current execution cleanly

**Why:** User wants to fully abort the run (not just pause). Saves progress/checkpoints and marks the execution as stopped.

**UX flow:**
1. Inline confirmation rendered in chat: *"Stop this execution? Progress will be saved."* with **Stop** / **Cancel** buttons
2. On confirm → `executionApi.stop(sessionId, activeExecutionId)`
3. Toast: *"Execution stopped."*

**Available when:** `workerRunState === "running"`

**Backend:** `POST /api/sessions/{id}/stop` ✅

---

#### `/replay` — Re-run from a saved checkpoint

**Why:** The replay system is one of Hive's most powerful features but is buried behind API calls. Users should be able to say "try that again from the start" or "replay from step 3" directly in chat.

**UX flow:**
1. Open checkpoint picker modal
2. Fetches most recent worker session: `sessionsApi.workerSessions(sessionId)`
3. Fetches its checkpoints: `sessionsApi.checkpoints(sessionId, wsId)`
4. Shows checkpoints as a list with timestamps and node names (e.g., *"After research_node — 2 min ago"*)
5. User picks → `executionApi.replay(sessionId, wsId, checkpointId)`
6. Live SSE events stream into the chat as the replay runs

**Available when:** At least one prior worker session exists

**Backend:** `GET /worker-sessions`, `GET /checkpoints`, `POST /replay` ✅

---

#### `/status` — Show current execution state inline

**Why:** During a long run the chat fills up with output. Users lose track of where the agent is, how long it's been running, and what node is active. `/status` surfaces a snapshot without having to look at the graph panel.

**UX flow:**
1. No modal — renders a **status card inline** in the chat thread (special non-message UI element)
2. Calls `sessionsApi.stats(sessionId)` + `sessionsApi.entryPoints(sessionId)` in parallel
3. Card shows:
   - Queen phase (planning / building / staging / running)
   - Active node name + current iteration
   - Elapsed time since execution started
   - Context usage % (from latest `context_usage_updated` SSE event if available)

**Available when:** Worker is loaded (any phase)

**Backend:** `GET /sessions/{id}/stats`, `GET /sessions/{id}/entry-points` ✅

---

#### `/goals` — Show structured goal progress

**Why:** Agents have explicit `success_criteria` defined in their goal. The raw chat output doesn't show how those criteria map to what's been completed. `/goals` brings the structured progress view into the conversation.

**UX flow:**
1. Renders an **inline card** in the chat thread
2. Calls `executionApi.goalProgress(sessionId)`
3. Shows each success criterion with a pass ✅ / fail ❌ / in-progress ⏳ indicator

**Available when:** Worker is loaded (any phase)

**Backend:** `GET /sessions/{id}/goal-progress` ✅

---

#### `/logs` — Show latest run logs in a modal

**Why:** When something goes wrong the user needs the actual execution logs immediately. Today logs are only visible in the node detail panel, which requires navigating away from the chat. `/logs` surfaces all three log levels in one place.

**UX flow:**
1. Open modal with 3 tabs: **Summary** / **Details** / **Tools**
2. Automatically selects most recent worker session ID
3. Fetches in parallel:
   - `logsApi.summary(sessionId, wsId)` — high-level run summary
   - `logsApi.details(sessionId, wsId)` — step-by-step detail log
   - `logsApi.tools(sessionId, wsId)` — all tool call inputs/outputs
4. Searchable, copy-to-clipboard per tab

**Available when:** At least one prior worker session exists

**Backend:** `GET /sessions/{id}/logs?level=summary|details|tools` ✅

---

## Command Availability Rules

| Command | Show when |
|---------|-----------|
| `/pause` | `workerRunState === "running"` |
| `/stop` | `workerRunState === "running"` |
| `/replay` | Prior worker session exists |
| `/status` | Worker is loaded (any state) |
| `/goals` | Worker is loaded (any state) |
| `/logs` | Prior worker session exists |

The workspace autocomplete dropdown should filter commands based on these rules — only show commands that are actionable right now.

---

## Full Command Summary

| Command | Location | Backend Endpoint(s) | Notes |
|---------|----------|---------------------|-------|
| `/resume` | Home page | `GET /sessions/history` | ✅ Already built |
| `/new` | Home page | `GET /discover` | Add to home.tsx |
| `/history` | Home page | `GET /sessions/history` | Add to home.tsx |
| `/pause` | Workspace chat | `POST /sessions/{id}/pause` | New workspace command system |
| `/stop` | Workspace chat | `POST /sessions/{id}/stop` | Needs inline confirmation |
| `/replay` | Workspace chat | `GET /worker-sessions`, `GET /checkpoints`, `POST /replay` | Needs checkpoint picker modal |
| `/status` | Workspace chat | `GET /stats`, `GET /entry-points` | Renders inline card in chat |
| `/goals` | Workspace chat | `GET /goal-progress` | Renders inline card in chat |
| `/logs` | Workspace chat | `GET /logs?level=*` | Needs 3-tab modal |

---

## Build Order

### Phase 1 — Home page additions (lowest effort, same pattern as `/resume`)
- `/new` — agent picker modal, navigate to workspace
- `/history` — session list modal, read-only view

### Phase 2 — Workspace slash command infrastructure (one-time setup)
- Add autocomplete dropdown to `ChatPanel.tsx`
- Add slash intercept to `workspace.tsx` `handleSend()`
- Add availability-aware `WORKSPACE_SLASH_COMMANDS` array

### Phase 3 — Simple workspace commands (no complex modals)
- `/status` — inline status card render
- `/goals` — inline goals card render

### Phase 4 — Action commands (need confirmation UX)
- `/pause` — immediate with toast
- `/stop` — inline confirmation buttons

### Phase 5 — Data commands (modal + async fetch)
- `/replay` — checkpoint picker modal
- `/logs` — 3-tab log viewer modal
