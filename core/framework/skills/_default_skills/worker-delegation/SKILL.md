---
name: hive.worker-delegation
description: Concrete patterns for breaking colony work into parallel worker jobs via run_playbook — when fan-out helps, how to model the goal as a tracker table, write the worker skill, author the playbook, pilot, and let convergence retry/resume the gap.
metadata:
  author: hive
  type: default-skill
  visibility: [colony]
---

## Operational Protocol: Worker Delegation

**Applies when** you're in COLONY mode and considering whether (and how) to fan out work to parallel workers via `run_playbook`. Read this before fan-out, not during.

### Mental model: the tracker is the spine, the playbook is the controller

You don't coordinate workers by reading their reports and deciding what's next each turn. You model the goal as a **tracker table** where every unit of work is a row, and you write a **playbook** — a deterministic Python script — that drives that table to completion:

> The playbook queries the rows that aren't done yet, dispatches one worker per undone row, and re-queries until none are left. Workers advance their own rows. Re-running the playbook resumes — done rows simply aren't in the work-list anymore.

This is a reconciliation loop. The tracker is the state; the playbook is the controller that converges it. Three artifacts, three jobs:

- **Tracker table** — the durable work-list and its state. The row's status column *is* the progress.
- **Skill** (`write_skill`) — the worker's operating procedure: schema, tool sequence, output format, quality bar. The risky part.
- **Playbook** (`run_playbook`) — the deterministic orchestration: which rows are undone, who runs them, rate limits, retry/convergence policy. The cheap part.

The worker's task string carries only the per-row slice; everything reusable lives in the skill, everything deterministic lives in the playbook.

### The decision: should you fan out at all?

Fan-out helps when:
- The work has **N independent units** (rows, person on linkedin, files, accounts, segments) and each unit takes meaningful tool time (browser, API, file read, LLM call).
- The units are **disjoint** — no two workers need to write the same row at the same time.
- You can describe one unit's work in <100 words once shared playbook is in the skill.

Fan-out HURTS when:
- N=1 or N=2 with cheap units. Spawning has overhead (fresh AgentLoop, separate conversation, no shared context). Below ~3 units of meaningful work, do it yourself.
- The work is exploratory ("figure out X"). Workers are bad at open-ended scope. Decompose first, then fan out the bounded parts.

When the user explicitly asks for fan-out, do not reject the request from an untested architecture guess. If you are unsure whether a browser session, API cursor, login, or other shared resource can be used by workers, ask the user. Workers you spawn get their own separate Chrome tab groups within the SAME Chrome profile — their tabs won't interfere with yours or each other's, and they share cookies / logged-in sessions with you.

### Pilot before fan-out (do the first one yourself)

You wrote the skill from your own walkthrough — but a walkthrough is not an execution. Selectors that worked when exploring can break under the exact tool sequence the skill prescribes; a page may paginate differently when fetched fresh; a field you eyeballed once might be intermittently null. Validate the skill yourself before paying N× to discover the bug.

**The queen runs the pilot, not a worker.** Pick ONE row from the tracker and execute the skill's protocol end-to-end with your own tools — the same `hive-browser` commands, `tracker_*`, `web_scrape`, etc. the workers would use. You see every tool result directly, with no `[WORKER_REPORT]` round-trip, and you can patch the skill mid-pilot as you discover gaps.

When to pilot (always, even when the user asks for "parallel"):
- You just wrote the skill from your own walkthrough, or you're recycling a skill across a UI/API you haven't driven this session.
- The work touches a UI surface that virtualizes, paginates, or has dynamic selectors (LinkedIn, Twitter, Notion, anything with virtual scroll or Shadow DOM).
- The per-unit work spans more than 2–3 tool calls.

How to pilot:
1. Pick ONE row — the most representative one, not the easiest.
2. Execute the skill yourself: run each tool in the prescribed order, advance the row to "done."
3. **If you hit a snag** — fix the skill in place before continuing. Capturing these patches is the whole point.
4. **If the row finishes cleanly:** the skill is validated. Run the playbook for the rest.
5. **If you can't finish the row at all:** the protocol is wrong (not one selector). Redesign before any worker touches it.

Skip the pilot only when the protocol is one you've already validated this session AND nothing about the target surface has changed.

### The loop (always, in order)

1. **Model the goal as a table** — `tracker_sql('CREATE TABLE …')`. Every unit is a row. **Include a done-predicate column** (a status enum, or a `*_at` timestamp that is NULL until complete). The playbook's "what's left" query depends on it. Register the columns workers write with `tracker_register_writable(...)`.
2. **Write the worker protocol as a skill** — `write_skill(skill_name='<protocol>', skill_body='…')`. Or `write_skill(source_path='<root>')` to lift an existing skill into this colony to pilot-patch it. The worker's last act is to **advance its own row** to done.
3. **Pilot the first row yourself** — execute the skill end-to-end against one row. Patch the skill in place. Don't run the playbook until this row finishes cleanly.
4. **Author the playbook** — a Python script (`meta` + `async def run(args)`) that calls `converge(...)` over the table. Set `meta["concurrency"]` to how many workers run at once (you own that number; the framework honors it, rejecting only if it's too high). The script runs in the colony's full Python env — `import json` / `datetime` etc. just work. This is the deterministic orchestration (next section).
5. **Run it** — `run_playbook({playbook: '<script>'})`. It saves the script to the colony library (`playbooks/<meta-name>.play.py`), returns immediately, and notifies you on completion. The convergence loop dispatches undone rows, retries the gap, and dead-letters terminal failures — without bouncing every worker report back to you. *(If the script has a real error, you get it right away, not a false "started".)*
6. **Re-running is resuming** — call `run_playbook({playbook_name: '<meta name>'})` (no need to re-send the script) — or edit `playbooks/<name>.play.py` and re-run by name. It re-queries the undone rows; done rows are skipped. There is no manual "find the gap and re-dispatch" — the pending query *is* the gap.

Skipping step 1 means you have no done-predicate, so nothing can resume. Skipping step 2 means you pay N× tokens for duplicated protocol. Skipping step 3 means one bad skill becomes N failed workers.

### GTM work: bookend the loop with the shared CRM (queen-only)

When the units are **people / leads / accounts** (cold outreach, enrichment, etc.), the shared team CRM — the `hive-crm` CLI (people/companies/opportunities), team-wide and cross-colony — is queen-owned: workers never touch it; they only fill the local tracker and report up. Wrap the loop with two CRM steps, and **put both in your task plan** so they're tracked deliverables, not afterthoughts:

- **Before step 1 — CLAIM (dedup across colonies).** Two colonies running outreach at once will double-touch the same prospect unless you claim first. `hive-crm summary --json` (load state), then `hive-crm import --file leads.json --json` to create/dedup the target people team-wide (returns their `person_ids`), then `hive-crm claim <person_ids> --json` to atomically lock them — you win only the unclaimed; ids that come back under `skipped` are owned by another colony, so drop them. Seed the local tracker with only the people you won. Do **not** list-then-decide — that races the other colony.
- **After step 6 — PROMOTE.** On `[PLAYBOOK_COMPLETE]`, read the completed local rows, `hive-crm import` the finished people to update the shared record, then `hive-crm release <person_ids> --json` to hand them off. The playbook stays local; you do the promote.

(Recording outreach outcomes on a person — advancing stage, logging calls/emails/replies — is rolling out; for now `import` keeps the shared people record current.)

### What goes in the playbook

The playbook is plain deterministic code — pull everything OUT of the worker prompt that doesn't need judgment:

- **Concurrency** — `meta["concurrency"]`: how many workers run at once. You set it; the framework honors it.
- **Decomposition** — the `pending` query: the rows not yet done (`WHERE researched_at IS NULL`). Derived from tracker state every run.
- **Routing** — which `profile` (account binding) and which `lane` (rate limit) each row goes to.
- **Convergence policy** — `max_rounds` (how many times to retry the gap), `circuit_breaker` (abort a round if too many fail). (`chunk` defaults to `meta["concurrency"]`; only set it to override per-round in-flight count.)
- **Contract** — the receipt `schema` each worker must return, and the row transition that counts as done.
- **Reduce** — the final summary you hand back (counts, dead-letter list).

**The API contract — get these right or you dispatch 0 workers:**
- `tracker_query(sql)` / `tracker_count(sql)` are **synchronous** (no `await`). `tracker_query` returns a **list of row dicts** (`[{'id':'a', ...}, ...]`) — index a row's column (`row['id']`), never the list. A `SELECT COUNT(*)` returns ONE row `[{'cnt': N}]` — that's for counting, not the pending list.
- `converge(...)` and `worker(...)` are **async**: `await converge(...)`, and inside it `dispatch=lambda row, i: worker(...)` (converge awaits each `worker` for you). Never call `worker()` in a bare loop without `await` — the coroutine won't run and you dispatch nothing. And the inverse trap: `for row in rows: await worker(...)` runs SERIALLY — each `await` blocks until that worker reports, so `meta["concurrency"]` does nothing. Parallel dispatch happens ONLY through `converge` — hand rows in via `pending` and let `dispatch` build the worker coroutine.
- `pending` must SELECT the undone **rows**, not a COUNT.

Hooks available in the script: `converge`, `worker`, `tracker_query` / `tracker_count`, `lane`, `deadletter`, `log`, `phase`. There is no mid-run escalation: a worker unsure about a row records that in the row (e.g. a `needs_review` status) and moves on; you review those rows — and the dead-letter — after the run completes. Because re-running is resume, the completion boundary is the decision point: stop, decide, edit, re-run (done rows are skipped).

### Decomposition patterns

Pick ONE decomposition axis per playbook.

**Per-row** — one worker per undone row (the default). `pending` selects rows; `dispatch` runs one worker each. For very cheap units, group a few rows per worker by selecting in batches. Use when each row is independently researchable / fillable.

**Per-segment** — workers DISCOVER rows within a slice (alphabetical, geographic, time window) rather than filling seeded rows. Use a UNIQUE INDEX on the natural key so two segments finding the same entity don't duplicate (`INSERT OR IGNORE` in worker upserts). The done-predicate is "segment marked swept."

**Per-stage (state machine)** — a multi-phase pipeline becomes states on the row: `new → enriched → notified → done`. Each `converge` pass (or each playbook) advances rows at one state to the next. The row's status column carries the progress; stage-2 workers read what stage-1 wrote.

### Routing, lanes, and rate limits

Workers bound to the same external account must not hammer it in parallel. Two levers, both keyed off the row index:

```python
ACCOUNTS = ["li-work-1", "li-work-2", "li-work-3"]   # worker profiles, one per account
for a in ACCOUNTS:
    lane(a, concurrency=3, rate_per_min=20)          # throttle each account

# in dispatch: rotate the account by rotating the PROFILE (a profile *is* the
# account binding), and put each on its own lane:
dispatch=lambda row, i: worker(
    task=...,
    profile=ACCOUNTS[i % len(ACCOUNTS)],   # spread load across accounts
    lane=ACCOUNTS[i % len(ACCOUNTS)],       # cap concurrency per account
    skill="...")
```

`profile` selects which account a worker uses — to spread across accounts, rotate `profile`, not a separate `account` arg (there isn't one). `meta["concurrency"]` sets the run-level total in flight; `lane` caps how many run at once **per account** within that. Use both: rotate to spread, lane to throttle. Without them you risk bans.

### Browser accounts: one colony across several Chrome profiles

When the accounts are **logged-in Chrome profiles** (e.g. three Gmail/LinkedIn logins, each in its own Chrome profile), each profile runs its own copy of the Hive extension with a **label** (the name in its side panel, or an auto 3-word id). There is no Chrome-launch / `--user-data-dir` step. A worker targets a profile by passing `--browser-profile <label>` to its `hive-browser` commands — `--browser-profile` is a normal, visible flag on `hive-browser open`/`hive-browser navigate`/`hive-browser script`, NOT a hidden binding. The operating model:

1. **Discover connected labels** with `list_browser_profiles` (a queen tool — call it directly, it's always available; it is NOT an in-playbook function). It returns the labels currently connected. Do **not** invent labels (`Default`, `Profile 1`, … are Chrome's directory names and mean nothing to the bridge) — use exactly what this returns.
2. **Tell each worker its label in the task.** In the playbook's `dispatch`, put the target label in the task string, e.g. `worker(task=f"... your --browser-profile is '{row['label']}' ...", ...)`. (There is no need to pre-create worker profiles or call `update_worker_profile` — that's not available in the playbook scope.)
3. **The worker passes it through**: the worker's skill should run `hive-browser open <url> --browser-profile "<its label>" --json` in the terminal. Every browser result echoes the browser profile actually used — the worker should verify it matches before proceeding.

Routing contract: a `--browser-profile` that no connected extension advertises → the `hive-browser` command **fails fast** with `no_browser_profile` listing the connected labels (it never silently uses a different account). Omitting `--browser-profile` → the **starred default** if set, else the **first-connected** profile (so it never hard-fails on ambiguity) — which is convenient but can be the wrong account, so for multi-account work always pass the label. With exactly one profile connected, everything routes to it.

### Idempotency: workers must be safe to re-run

Re-running the playbook re-dispatches any row not marked done — including a row whose worker **crashed mid-action**. Tracker upserts are safe (same key overwrites). But an **external side effect is not** — if a worker sends a message then crashes before marking its row done, a resume will re-dispatch it. The send tool itself must be idempotent ("already messaged this thread today?"). Design worker protocols so the side-effecting step can detect "already done" before repeating it. The receipt a worker returns is its *claim*; the tracker row is the *truth* — if they disagree, the row wins and the row is re-dispatched.

### Worked example

Goal: "Research 25 fintech competitors and fill in funding, pricing, customer logos."

```
1. tracker_sql:
     CREATE TABLE competitors (
       slug TEXT PRIMARY KEY, name TEXT, website TEXT,
       funding_usd TEXT, pricing_model TEXT, customer_logos INTEGER,
       notes TEXT, researched_at TEXT          -- done-predicate: NULL until complete
     );
     INSERT INTO competitors(slug,name) VALUES ('stripe','Stripe'), ... 25 rows ...;

2. tracker_register_writable(
     table='competitors',
     write_columns=['website','funding_usd','pricing_model',
                    'customer_logos','notes','researched_at'],
     key_columns=['slug'])

3. write_skill(
     skill_name='fintech-competitor-research',
     skill_body='# Protocol\n For each assigned slug:\n
       1. web_scrape the company website + crunchbase.\n
       2. tracker_upsert: website, funding_usd ("$1.2B"/"$45M est."/"N/A"),
          pricing_model (usage|seat|flat|hybrid), customer_logos (int, -1 if none),
          notes (2-3 sentences VC-relevant), and researched_at (the run date)
          AS THE LAST STEP — researched_at marks the row done.\n
       3. If a field can\'t be verified after 2 attempts, write "N/A" + a one-line
          reason in notes. Don\'t fabricate.')

4. Pilot 'stripe' yourself — run the protocol end-to-end with your own tools.
   Patch 'fintech-competitor-research' if funding lived on a different page than
   expected. Only proceed once the stripe row reaches researched_at != NULL.

5. Write the playbook and run it inline (it's saved to the library as
   fintech-competitor-research-batch.play.py):

     meta = {"name": "fintech-competitor-research-batch",
             "description": "Converge the competitors table: every row researched",
             "concurrency": 4}          # 4 workers at once — you own this number

     RECEIPT = {"type": "object", "required": ["slug", "status"],
                "properties": {"slug": {"type": "string"},
                               "status": {"enum": ["researched", "no-data"]}}}

     async def run(args):
         await converge(
             # pending() returns a LIST OF ROW DICTS; tracker_query is SYNC (no await)
             pending=lambda: tracker_query(
                 "SELECT slug, name FROM competitors WHERE researched_at IS NULL"),
             # converge awaits each worker(...) for you — don't await it yourself
             dispatch=lambda row, i: worker(
                 task=f"Research {row['slug']} ({row['name']}) using the "
                      f"fintech-competitor-research skill; upsert its row.",
                 skill="fintech-competitor-research",
                 timeout=400, schema=RECEIPT),
             max_rounds=3,        # re-derive the gap from the tracker, up to 3 times
         )
         gap = tracker_count("SELECT slug FROM competitors WHERE researched_at IS NULL")
         log(f"converged; {gap} unresolved -> dead-letter")
         return {"unresolved": gap, "deadletter": deadletter.list()}

6. run_playbook({playbook: '<the script above>'})
   It dispatches the 24 remaining rows 8 at a time, retries failures, and notifies
   you when the table converges. If any rows are left, resume with
   run_playbook({playbook_name: 'fintech-competitor-research-batch'}) — done rows
   are skipped.
```

That's the whole pattern. Apply it to anything with row shape: model it as a table with a done-predicate, write the worker skill, pilot one row, let the playbook converge the rest.
