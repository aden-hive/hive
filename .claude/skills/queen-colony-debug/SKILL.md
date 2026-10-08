# Queen / Colony Debug Skill

SOP for live debugging of queen sessions, colony forks, worker spawns, and tracker DB plumbing without touching the user's production Hive Desktop. Use this when something is wrong in the create_colony → tracker → run_parallel_workers → worker pipeline.

## Trigger

User asks you to debug, reproduce, or verify behavior in:
- Queen DM sessions, colony sessions, `fork_session_into_colony`
- `ColonyBinding` propagation (queen exec context, worker `input_data`)
- `tracker_sql` / `tracker_register_writable` / `tracker_upsert` / `tracker_query`
- `run_parallel_workers` preflight
- Phantom `colonies/session_<uuid>/` shadow folders (the original split-brain bug)
- Session resume from disk, queen phase transitions (independent → incubating → colony)

Examples: "queen says no such table", "workers can't see what queen wrote", "phantom colony folder appeared", "verify my colony refactor didn't break anything".

## Hard rules

1. **Never run against the user's real Hive Desktop runtime by default.** Use an isolated `HIVE_HOME=/tmp/hive_e2e` first. Only switch to the real `HIVE_HOME` (`~/Library/Application Support/Hive/users/<hash>`) when the user has explicitly asked for live LLM verification or when an offline repro is impossible.
2. **Never read the real `secrets/`, `credentials/`, or `configuration.json` directories.** The auto-mode classifier will block credential exploration. You don't need their contents — the server reads them itself.
3. **Pick a non-default port** (`--port 8901`/`8902`/`8903`) so you don't collide with a running Hive Desktop on `8787`.
4. **Background the server, don't foreground it.** `&` redirects the log to a file you can `tail`/`grep` while you make HTTP calls in parallel.
5. **For "wait for thing X" patterns: use `Bash run_in_background:true` with an `until grep -q ...` loop** — never chain `sleep N`. The harness blocks long leading sleeps.
6. **LLM-driven turns cost real credits.** Budget your queen prompts: prefer terse, deterministic instructions ("just call create_colony with these exact args") over open-ended questions.

## What "correct" looks like (key invariants)

These are the invariants the refactor enforces; verifying them is most of the job:

- A DM queen session **must not** create `colonies/<session_uuid>/` (the phantom-folder bug). Only on-disk colony names live under `colonies/`.
- `worker.json` `input_data` carries exactly one key: `{"binding": {"name", "dir", "tracker_db"}}`. No `tracker_db_path`, no `colony_id` (those are legacy and get stripped by `_patch_worker_configs` on every server boot).
- The queen and her workers in a given colony share **one** `tracker.db` — the one inside `colonies/<name>/data/`.
- Tools refuse with `"no colony context — this tool only works inside a colony"` when called without a binding. They never synthesize paths.
- `run_parallel_workers` emits the log line `run_parallel_workers: attached binding to N spawn(s) (colony=<name>)`. If that line is missing, the binding plumbing is broken.

Authoritative source for the binding model: [core/framework/host/colony_binding.py](core/framework/host/colony_binding.py).

## SOP

### Step 1 — Pick a runtime

Default to isolated:

```bash
mkdir -p /tmp/hive_e2e/colonies /tmp/hive_e2e/agents/queens
PORT=8901
HIVE_HOME=/tmp/hive_e2e uv run hive serve --port $PORT --verbose 2>&1 > /tmp/hive_e2e/server.log &
echo "pid: $!"
```

Confirm it's up:

```bash
until curl -sf http://127.0.0.1:$PORT/api/health >/dev/null 2>&1; do sleep 1; done
curl -s http://127.0.0.1:$PORT/api/health
```

For real-runtime verification (only when explicitly requested):

```bash
REAL="/Users/aden/Library/Application Support/Hive/users/<the-user-hash>"  # find via: ls ~/Library/Application\ Support/Hive/users/
HIVE_HOME="$REAL" uv run hive serve --port 8903 --verbose 2>&1 > /tmp/hive_real.log &
```

Verify `Commercial extensions loaded` appears in the startup log; that's the green light.

### Step 2 — Snapshot the starting state

```bash
echo "=== colonies dir ==="; ls "$HIVE_HOME/colonies/"
echo "=== queens ==="; ls "$HIVE_HOME/agents/queens/" 2>&1 | head -10
echo "=== existing sessions ==="; curl -s http://127.0.0.1:$PORT/api/sessions | uv run python -m json.tool
```

Anything `session_*` under `colonies/` BEFORE you do anything is an existing phantom-folder issue.

### Step 3 — Drive the failing flow

#### (a) Create a DM session (queen-only, no LLM-side actions)

```bash
RESP=$(curl -s -X POST http://127.0.0.1:$PORT/api/sessions -H 'Content-Type: application/json' \
  -d '{"queen_name": "queen_technology"}')
SESSION_ID=$(echo "$RESP" | uv run python -c "import json,sys; print(json.load(sys.stdin)['session_id'])")
echo "$SESSION_ID"
```

**Invariant check:** `colonies/` should still be empty. If `colonies/session_$SESSION_ID/` appeared, the phantom-folder bug is back. Suspect: `ColonyRuntime.__init__` re-introduced an unconditional `ensure_task_list(colony:<colony_id>)` call.

#### (b) Fork DM into a colony — non-LLM path

This drives `fork_session_into_colony` without burning credits on a queen turn:

```bash
curl -s -X POST "http://127.0.0.1:$PORT/api/sessions/$SESSION_ID/colony-spawn" \
  -H 'Content-Type: application/json' \
  -d '{"colony_name":"debug_test","task":"debug"}' | uv run python -m json.tool
```

Expected response shape: `{colony_path, colony_name, queen_session_id, is_new, compaction_status}`. **No** `tracker_db_path` field — if it's there, the cleanup regressed.

Then verify the on-disk binding:

```bash
uv run python -c "
import json
cfg = json.load(open('$HIVE_HOME/colonies/debug_test/worker.json'))
print(json.dumps(cfg.get('input_data'), indent=2))
"
```

Expected:

```json
{
  "binding": {
    "name": "debug_test",
    "dir": "/.../colonies/debug_test",
    "tracker_db": "/.../colonies/debug_test/data/tracker.db"
  }
}
```

If you see `tracker_db_path` or `colony_id` keys here, [worker_definition.build_input_data](core/framework/agents/queen/worker_definition.py) or [routes_execution.fork_session_into_colony](core/framework/server/routes_execution.py) is writing the legacy shape.

#### (c) LLM-driven path (talk to the queen)

Only use when (b) isn't enough. Send a tight, deterministic prompt:

```bash
curl -s -X POST "http://127.0.0.1:$PORT/api/sessions/$SESSION_ID/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message": "Just call create_colony(colony_name=\"debug_e2e\", task=\"debug\"). Do nothing else."}'
```

Then watch for the actual tool call (this is the right way to wait — no sleep chains):

```bash
# In Bash with run_in_background:true
until grep -qE "tool_call: create_colony|Forked queen to colony|colony fork failed" /tmp/hive_e2e/server.log; do sleep 5; done
```

When background command exits, grep the log for what actually happened:

```bash
grep -E "tool_call: create_colony|Forked queen to colony|colony fork failed|fork_session" /tmp/hive_e2e/server.log | tail -10
```

#### (d) Activate the colony's queen session (post-fork, for tracker work)

`fork_session_into_colony` creates a **separate** colony-queen session on disk (returned as `queen_session_id`) that isn't loaded into the SessionManager until you ask. To talk to it:

```bash
COLONY_SESSION="<queen_session_id from fork response>"
COLONY_PATH="$HIVE_HOME/colonies/debug_e2e"
curl -s -X POST http://127.0.0.1:$PORT/api/sessions \
  -H 'Content-Type: application/json' \
  -d "{\"agent_path\":\"$COLONY_PATH\", \"queen_resume_from\":\"$COLONY_SESSION\", \"queen_name\":\"queen_technology\"}" \
  | uv run python -m json.tool
```

Verify `queen_phase: "colony"` in the response — that's when tracker tools are exposed. If she's still `"independent"`, she lost her binding on resume; check [queen_orchestrator.py:_queen_loop](core/framework/server/queen_orchestrator.py) — it should call `ColonyBinding.for_name(session.colony_name)` and stamp the exec context.

#### (e) Drive the queen→worker tracker flow

```bash
curl -s -X POST "http://127.0.0.1:$PORT/api/sessions/$COLONY_SESSION/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message": "Run tracker_sql to CREATE TABLE x (id INTEGER PRIMARY KEY, body TEXT). Then CREATE UNIQUE INDEX x_id ON x(id). Then tracker_register_writable(table=x, write_columns=[body], key_columns=[id]). Then INSERT INTO x VALUES (1, \"seed\"). Then run_parallel_workers with one task that calls tracker_upsert to set body=\"worker wrote\" on id=1, then report_to_parent."}'
```

(Note: `INTEGER PRIMARY KEY` does NOT register as a unique index in SQLite's `PRAGMA index_list` — you need an explicit `CREATE UNIQUE INDEX`. This is pre-existing validator behavior in tracker_tools, not a refactor regression.)

Then wait for the marker line:

```bash
# Bash run_in_background:true
until grep -q "attached binding to" /tmp/hive_e2e/server.log; do sleep 3; done
grep "attached binding to" /tmp/hive_e2e/server.log
```

Expected line: `run_parallel_workers: attached binding to N spawn(s) (colony=debug_e2e)`. Missing → binding plumbing broken in [queen_lifecycle_tools.py::run_parallel_workers](core/framework/tools/queen_lifecycle_tools.py).

### Step 4 — Verify with sqlite3 directly

Cut out the HTTP layer and look at the raw tracker DB:

```bash
sqlite3 "$HIVE_HOME/colonies/debug_e2e/data/tracker.db" ".schema"
sqlite3 "$HIVE_HOME/colonies/debug_e2e/data/tracker.db" "SELECT * FROM _tracker_registry"
sqlite3 "$HIVE_HOME/colonies/debug_e2e/data/tracker.db" "SELECT * FROM x"  # or whatever table
```

Confirm there is **no second DB** at a session-id-named path:

```bash
ls "$HIVE_HOME/colonies/" | grep "^session_" && echo "PHANTOM FOLDER PRESENT (BUG)" || echo "clean ✓"
find "$HIVE_HOME/colonies" -name "tracker.db" -type f
```

There should be exactly one `tracker.db` per real colony. Multiple means split-brain.

### Step 5 — Test refusal behavior without an LLM

Cheap Python repro of "tools refuse without binding":

```bash
HIVE_HOME=/tmp/hive_e2e uv run python -c "
import asyncio
from framework.tools.tracker_tools import _make_tracker_sql_executor, _make_tracker_query_executor, _make_tracker_upsert_executor, _make_tracker_register_executor

async def main():
    for name, mk in [
        ('tracker_sql', _make_tracker_sql_executor),
        ('tracker_query', _make_tracker_query_executor),
        ('tracker_upsert', _make_tracker_upsert_executor),
        ('tracker_register', _make_tracker_register_executor),
    ]:
        r = await mk()({'sql': 'SELECT 1', 'table': 'x', 'row': {'a': 1}, 'write_columns': ['a'], 'key_columns': ['a']})
        ok = r.get('success') is False and 'no colony context' in r.get('error', '')
        print(f'  {name}: {\"REFUSED ✓\" if ok else \"UNEXPECTED ✗\"} → {r}')

asyncio.run(main())
"
```

### Step 6 — Test queen↔worker tracker sharing (offline)

Exercises the entire binding flow in-process, no LLM cost:

```bash
HIVE_HOME=/tmp/hive_e2e uv run python -c "
import asyncio
from framework.host.colony_binding import ColonyBinding
from framework.host.tracker_db import ensure_tracker_db
from framework.loader.tool_registry import ToolRegistry
from framework.tools.tracker_tools import (
    _make_tracker_sql_executor,
    _make_tracker_register_executor,
    _make_tracker_upsert_executor,
    _make_tracker_query_executor,
)

async def main():
    binding = ColonyBinding.for_name('offline_test')
    ensure_tracker_db(binding.dir)

    # Queen: DDL + register + seed
    tok = ToolRegistry.set_execution_context(binding=binding)
    try:
        sql = _make_tracker_sql_executor()
        await sql({'sql': 'CREATE TABLE t (k TEXT PRIMARY KEY, v TEXT)'})
        await sql({'sql': 'CREATE UNIQUE INDEX t_k ON t(k)'})
        await _make_tracker_register_executor()({'table': 't', 'write_columns': ['v'], 'key_columns': ['k']})
        await sql({'sql': \"INSERT INTO t VALUES ('a', 'queen')\"})
    finally:
        ToolRegistry.reset_execution_context(tok)

    # Worker: read + upsert from a SEPARATE exec context (binding comes via input_data)
    binding_from_input = ColonyBinding.from_dict(binding.to_dict())
    tok = ToolRegistry.set_execution_context(binding=binding_from_input)
    try:
        r = await _make_tracker_query_executor()({'sql': 'SELECT * FROM t'})
        print('worker SELECT:', r.get('rows'))
        assert r.get('rows') == [['a', 'queen']], 'split-brain: worker saw a different DB!'

        await _make_tracker_upsert_executor()({'table': 't', 'row': {'k': 'a', 'v': 'worker'}})
    finally:
        ToolRegistry.reset_execution_context(tok)

    # Queen: confirm worker's write is visible
    tok = ToolRegistry.set_execution_context(binding=binding)
    try:
        r = await _make_tracker_sql_executor()({'sql': 'SELECT * FROM t'})
        assert r.get('rows') == [['a', 'worker']], 'split-brain: queen lost worker write!'
        print('queen SELECT:', r.get('rows'))
    finally:
        ToolRegistry.reset_execution_context(tok)
    print('✓ queen+worker share the same tracker.db')

asyncio.run(main())
"
```

If both asserts pass: binding plumbing intact. If either fails: the split-brain bug is back; check `_resolve_tracker_db_path`-equivalents weren't reintroduced in [tracker_tools.py](core/framework/tools/tracker_tools.py).

### Step 7 — Shut down cleanly

```bash
pkill -f "hive serve --port $PORT"
sleep 2
ps aux | grep "hive serve" | grep -v grep || echo "(clean)"
```

If you used `HIVE_HOME=/tmp/hive_e2e`, optionally `rm -rf /tmp/hive_e2e` when done.

If you used the real HIVE_HOME: **do not auto-clean.** Tell the user which colonies you created (`debug_test`, `debug_e2e`, etc.) and which orphan queen sessions exist under `agents/queens/<queen_id>/sessions/`, and let them decide.

## Common failure patterns

| Symptom | First place to look |
|---|---|
| `colonies/session_<uuid>/` directory exists after a DM session | `ColonyRuntime.__init__` — check the `ensure_task_list` call is guarded by `if self._binding:` |
| Worker gets `sqlite error: no such table` even though queen registered it | Two tracker.db files exist; queen and worker have different `binding` paths. `grep "attached binding"` log — colony name should match the on-disk dir. |
| Tools refuse with "no colony context" mid-session | Queen lost her exec context. After `fork_session_into_colony`, `ToolRegistry.set_execution_context(binding=...)` must run in the queen's task (the tool path), or `session.binding` must be set so `_queen_loop` re-stamps on next iteration. |
| `worker.json input_data` has `tracker_db_path` instead of `binding` | Either `build_input_data` regressed, or `_patch_worker_configs` didn't run on startup. Logs show `tracker_db: patched N worker config(s) ... with fresh binding` if the migration fired. |
| `run_parallel_workers` returns `"no colony binding in the execution context"` | The queen's tool runs **inside** the queen's asyncio task. If you got there via HTTP `/colony-spawn` instead of the queen calling `create_colony` herself, her contextvar wasn't updated. Drive it through the queen's chat instead. |
| Colony queen session opens in `independent` phase, missing tracker tools | `session.colony_name` was None when `_queen_loop` started. Check `_load_worker_core` / `create_session` path is setting both `colony_name` and `binding`. |

## Key file index

When investigating, these are the load-bearing files:

- [core/framework/host/colony_binding.py](core/framework/host/colony_binding.py) — the dataclass + `current_binding()` accessor.
- [core/framework/host/colony_runtime.py](core/framework/host/colony_runtime.py) — `ColonyRuntime` (constructor invariants, `stream_id` vs `binding` separation).
- [core/framework/host/worker.py](core/framework/host/worker.py) — worker reads `input_data.binding` and stamps it on its own exec context.
- [core/framework/host/tracker_db.py](core/framework/host/tracker_db.py) — `ensure_tracker_db`, `_patch_worker_configs` (startup migration).
- [core/framework/tools/tracker_tools.py](core/framework/tools/tracker_tools.py) — `_require_binding()` gate, executor implementations.
- [core/framework/tools/queen_lifecycle_tools.py](core/framework/tools/queen_lifecycle_tools.py) — `run_parallel_workers` preflight, `create_colony` tool.
- [core/framework/server/routes_execution.py](core/framework/server/routes_execution.py) — `fork_session_into_colony`, `handle_colony_spawn`.
- [core/framework/server/queen_orchestrator.py](core/framework/server/queen_orchestrator.py) — `_queen_loop` initial exec-context stamp.
- [core/framework/server/session_manager.py](core/framework/server/session_manager.py) — `Session` dataclass, `_start_queen`, `_load_worker_core`.
- [core/framework/agents/queen/worker_definition.py](core/framework/agents/queen/worker_definition.py) — `build_input_data` serialization.

## Anti-patterns

- ❌ Long leading `sleep N` to wait for an LLM turn → use Bash `run_in_background:true` with `until grep -q ...; do sleep N; done`.
- ❌ `cat` the real `secrets/`/`credentials/`/`configuration.json` → the classifier blocks it and you don't need it.
- ❌ Open-ended prompts like "please test the colony stuff for me" → the queen will spend 5+ turns researching. Always say exactly which tool to call with which args.
- ❌ Asserting success purely from the JSON response — always cross-check `sqlite3` and `ls colonies/` for invariants.
- ❌ Running against the user's real Hive port (default 8787) if their desktop app is up → port-conflict crash. Use 8901+.
