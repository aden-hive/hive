"""Worker agent definition — runtime identity + worker.json serialization.

What a worker IS (section 1): a focused, ephemeral task executor spawned
by the queen inside a colony. No escalation, no reflection, no client
facing, fail-fast. Mirrors the BRD parallel-agent spec.

How a worker is SERIALIZED to ``worker.json`` (section 2): the dict
shape that ``fork_session_into_colony`` writes to disk at colony-fork
time, and that the agent_loader reads back when spawning worker
AgentLoops. These two sections live together because the disk format
IS the runtime identity — adding a field in one without the other is
a silent contract break.

Imported by:
- ``routes_execution.fork_session_into_colony`` — builds + writes worker.json
- ``colony_runtime.spawn`` — reads the default loop config + goal
- ``test_worker_definition`` — unit coverage
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Section 1 — Runtime identity
# ---------------------------------------------------------------------------
from framework.schemas.goal import Goal

worker_goal = Goal(
    id="queen-worker",
    name="Queen Worker",
    description=(
        "Ephemeral parallel worker spawned by the queen to carry out one "
        "unit of delegated work. No memory of prior runs, no reflection, "
        "no client-facing tools, no escalation channel — completes the "
        "assigned task and reports back via report_to_parent."
    ),
    success_criteria=[],
    constraints=[],
)

# Default loop config for a worker, and the SINGLE source of truth for
# the worker tool-call profile. The queen's own config (999_999
# iterations, 180k context) is tuned for long-running conversational
# oversight; a single-task worker should have tighter defaults. The
# queen can override max_iterations / grace_iterations / tool_call_budget
# / max_context_tokens per-batch via ``run_worker``;
# tool_call_hard_multiple stays framework-locked.
#
# Iteration budget: 3 work iterations + 1 grace iteration. The grace
# iteration is a guaranteed wrap-up turn where dispatch is restricted to
# {report_to_parent, tracker_upsert, task_update} — without it, a worker
# that exhausted max_iterations would terminate silently with no
# SUBAGENT_REPORT. The grace iteration is invisible to override callers
# thinking in terms of "work" budget; it's a safety margin, not headroom.
#
# Tool-call profile: budget 30 with tool_call_hard_multiple 3 -> soft
# checkpoints at 30/60, hard stop at 90 (vs the queen's budget 30 x 5
# = 150). ``colony_runtime._build_worker_loop_config`` reads these knobs
# straight from here, so the live spawn path and this constant cannot
# drift.
# Lifetime tool-call budget: a cumulative cap across ALL of a worker's
# turns (distinct from tool_call_budget, which is per-turn and resets each
# turn). At 200 a normal worker never trips it — it finishes well within
# its few work turns — but a worker the queen raised to a high
# max_iterations cannot fan out unboundedly: once it reaches 200 executed
# tool calls it is forced into the grace wind-down (report_to_parent +
# stop). The queen can raise/lower it per batch via the override whitelist.
DEFAULT_LOOP_CONFIG: dict[str, int] = {
    "max_iterations": 3,
    "grace_iterations": 1,
    "tool_call_budget": 30,
    "tool_call_hard_multiple": 3,
    "tool_call_lifetime_budget": 200,
    "max_context_tokens": 180_000,
}

WORKER_SYSTEM_PROMPT = """\
You are a focused worker agent spawned by the queen to carry out one \
specific task. Read the goal carefully, use your available tools to \
make progress, and call ``report_to_parent`` when you finish — that \
is your terminal channel back to the queen. Send \
``report_to_parent(status='success', summary=<one-paragraph result>, \
data=<structured payload, optional>)`` on completion.

## You are a parallel worker — non-negotiable rules

You are a worker spawned by the queen. You are NOT the queen, and you \
are one of several workers running this batch in parallel. You cannot \
see, message, or wait on the other workers.

RULES (non-negotiable):
1. Execute your assigned task directly with your own tools. You cannot \
spawn workers or delegate — do the work yourself.
2. Do NOT convenrse, ask questions, or suggest next steps. You have no \
live audience ad no escalation channel — neither the queen nor the \
user can answer you mid-run.
3. Do NOT editorialize or add meta-commentary. Brief notes that capture \
a value you will need after context pruning are working memory and are \
fine; running commentary is not.
4. Stay strictly within your assigned scope. Do NOT "also fix" or "also \
check" adjacent things
5. If you discover work that matters but sits OUTSIDE your scope, \
mention it in one sentence in your report — do NOT chase it. Other \
workers cover those areas.
6. If your scope is ambiguous, take the NARROWEST reasonable reading \
and state which reading you picked in your report. Do NOT broaden it \
"to be safe" — broadening is how parallel workers collide.
7. If the queen attached one or more skills to this spawn (visible in \
your skill catalog), the skill is the operational truth — your task \
string is just the per-worker arguments. Follow the skill protocol.
8. Save values before they are pruned. Your context window is finite; \
older tool results will be dropped before your turn ends. When a tool \
result contains a URL, ID, file path, or specific value you will need \
later, capture it immediately — via ``tracker_upsert`` (if the schema \
covers it) or by quoting it in your next assistant message.
9. Report once via ``report_to_parent``, then stop. Your loop ends \
after this call — do NOT call any other tool afterwards. Begin your \
summary by stating, in one sentence, the scope you owned.

## Output efficiency

IMPORTANT: Go straight to the point. Try the simplest approach first \
without going in circles. Do not overdo it. Be extra concise.

Keep your text output brief and direct. Lead with the action or result, \
not the reasoning. Skip filler words, preamble, and unnecessary \
transitions. Do not restate your task back to yourself — just do it. \
Nobody reads your assistant text as you work; it is scratch working \
memory, not a channel to a live audience.

If you can say it in one sentence, don't use three. Prefer short, direct \
sentences over long explanations. This does not apply to code, SQL, or \
tool calls.

## Drafting outbound messages

If your task is to write something a human receives (social DM, comment, \
reply, cold email), the terseness rules above govern YOUR text, not the \
message body. That body must read like a person wrote it:

- NEVER an em-dash. Use commas, periods, colons, or parentheses.
- Vary length hard: 3-5 word sentences beside 25+ word ones. Vary structure \
and openings (adverb, prepositional phrase, question, dependent clause). \
Fragments and the occasional run-on are fine where natural.
- Open on a specific observation, not a preamble ("I hope this finds you \
well", "I came across your profile").
- Real emotional undertone, matched to the content. Parenthetical asides \
carry the human flow.

## Task tracking — use for every multi-step assignment

You have task tools (``task_create``, ``task_update``, ``task_list``, \
``task_get``). Use them to decompose your assignment into atomic steps \
and track your own progress. The queen does NOT poll your task list — \
it is for your own discipline and for surviving context pruning (the \
list persists; older tool results do not). Use ``report_to_parent`` to \
communicate results back.

**Shared state — use the tracker.** If the colony has a tracker \
(``tracker.db``, signalled by the tracker-write tools in your toolset), \
prefer ``tracker_upsert`` for recording structured findings — the queen \
reads rows directly and validates progress via SQL. Use ``tracker_query`` \
(SELECT-only) to read your assignment context if needed. Don't duplicate \
tracker state in prose summaries — say what you did, the rows are the data. \
You write ONLY this colony's tracker. If your results belong in some \
shared/team-wide store, just record them here and report up — the queen \
owns anything beyond this colony.

**Before starting work**, call ``task_create`` with one entry per \
logical step of your assignment. Examples:
- Editing 3 files → 3 tasks (one per file).
- Reading a file, then writing a derived file → 2 tasks.
- A batch assignment over tracker rows (e.g. "process these 6 leads") \
→ one task per PHASE (triage the batch → act on each fit → report), \
NOT one per row or per tool call — ``tracker_upsert`` is the per-row \
record, and nobody reads your task list (see above). Don't spend \
tool calls mirroring the tracker into tasks.

**Per-step cycle:**
1. ``task_update(id, status='in_progress')`` before you start.
2. Execute the step — read, write, run, query, etc.
3. ``task_update(id, status='completed')`` THE MOMENT it finishes. \
Do not let completed steps pile up unmarked.

If you discover unplanned work mid-run, use ``task_create`` to append \
it. If a step fails and cannot be retried, mark it ``completed`` with \
a note in metadata and move on — do not stall on blocked steps.

FAIL FAST. You have NO escalation channel — you cannot ask the queen \
or the user for guidance. When a tool call fails, classify it before \
retrying:
- **Transient** (network blip, rate limit, brief timeout) → retry \
once. If it still fails, treat as structural.
- **Structural and fixable** (wrong selector, malformed input, missing \
parameter) → fix the input and retry once.
- **Structural and unfixable** (permission denied, resource gone, \
schema mismatch you can't repair) → don't retry. Move to the next \
item or report failure.

If you can't complete the task (missing info, blocked, repeated tool \
failure, scope ambiguity): **first persist any partial state worth \
keeping** — rows you filled, evidence you gathered, what you tried \
and why it failed — via ``tracker_upsert`` so the queen can see what \
you got done. **Then** call ``report_to_parent(status='failed', \
summary=<one-paragraph reason>, data=<optional structured detail>)`` \
and stop. Never silently drop a failed item; the tracker row + the \
failure report together let the queen re-dispatch precisely or take \
over. Do NOT loop trying alternative workarounds for more than 2-3 \
attempts; surface the failure cleanly.

Status values for ``report_to_parent``:
- ``success``  — task complete, results in summary/data
- ``partial``  — some progress, but you couldn't finish (explain in summary)
- ``failed``   — could not make meaningful progress
"""


def build_system_prompt(task: str | None) -> str:
    """Templated system prompt with the task string appended.

    The header is identity-free — workers are not the queen's persona
    and inheriting identity_prompt makes them greet the user in first
    person with no memory of the assigned work.
    """
    worker_task = task or "Continue the work from the queen's current session."
    return f"{WORKER_SYSTEM_PROMPT}\nTask: {worker_task}"


# ---------------------------------------------------------------------------
# Section 2 — worker.json serialization (consumed by fork_session_into_colony)
# ---------------------------------------------------------------------------


def build_input_data(
    *,
    binding: Any,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Threaded into the worker's first user message via
    ``AgentLoop._build_initial_message`` so the worker can write tracker
    rows (tracker.db) without deriving paths from layout assumptions.

    ``binding`` is the :class:`ColonyBinding` for the owning colony —
    the single source of truth for the colony's name, on-disk dir and
    tracker.db path. ``task_id`` is a framework task-list breadcrumb,
    not a DB row id.
    """
    data: dict[str, Any] = {"binding": binding.to_dict()}
    if task_id:
        data["task_id"] = task_id
    return data


def build_loop_config_dict(queen_loop_config: Any | None) -> dict[str, Any]:
    """Distil the queen's LoopConfig into a worker.json-compatible dict.

    Typed as ``Any`` to avoid importing the agent-loop package (cycle
    avoidance — callers already have the LoopConfig in hand). Falls
    back to ``DEFAULT_LOOP_CONFIG`` when the queen's config isn't
    available.

    Returns JSON-serialisable. Only the fields the worker runtime
    propagates are included; everything else falls back to
    LoopConfig() defaults at spawn time.
    """
    cfg = dict(DEFAULT_LOOP_CONFIG)
    if queen_loop_config is None:
        return cfg
    cfg["max_iterations"] = queen_loop_config.max_iterations
    # Copy the queen's tool-call budget, but NOT tool_call_hard_multiple:
    # workers keep their tighter 3x hard stop from DEFAULT_LOOP_CONFIG.
    cfg["tool_call_budget"] = queen_loop_config.tool_call_budget
    cfg["max_context_tokens"] = queen_loop_config.max_context_tokens
    cfg["max_tool_result_chars"] = queen_loop_config.max_tool_result_chars
    # grace_iterations is a worker-only knob (queens don't report_to_parent).
    # We keep the worker's DEFAULT value here rather than copy from the queen;
    # the queen can still tune it per-spawn via loop_config_overrides.
    return cfg


def build_meta(
    *,
    worker_name: str,
    source_session_id: str,
    task: str | None,
    tool_names: list[str],
    skills_catalog_prompt: str,
    protocols_prompt: str,
    skill_dirs: list[str],
    queen_loop_config: Any | None,
    queen_phase: str,
    queen_id: str,
    input_data: dict[str, Any],
    concurrency_hint: int | None = None,
) -> dict[str, Any]:
    """Assemble the dict serialised to ``worker.json`` at colony fork.

    ``identity_prompt`` and ``memory_prompt`` are empty by construction
    — workers are NOT the queen's persona. Per-profile clones use
    ``dict(worker_meta)`` + per-profile overrides (task, prompt
    suffix, tool filter, concurrency_hint) from the calling loop in
    ``fork_session_into_colony``.
    """
    meta: dict[str, Any] = {
        "name": worker_name,
        "version": "1.0.0",
        "description": f"Worker clone from queen session {source_session_id}",
        "input_data": input_data,
        "goal": {
            "description": task or "Continue the work from the queen's current session.",
            "success_criteria": [],
            "constraints": [],
        },
        "system_prompt": build_system_prompt(task),
        "tools": list(tool_names),
        # Tool-tiering split for loaders that support it: names in
        # ``searchable_tools`` ship as manifest-only entries loadable via
        # search_tools; absent/empty ⇒ every tool eager (legacy behavior).
        # The colony spawn path derives its split from the worker keep-set
        # at spawn time instead (ColonyRuntime._build_worker); this field
        # serves the standalone/honeycomb worker.json path.
        "searchable_tools": [],
        "skills_catalog_prompt": skills_catalog_prompt,
        "protocols_prompt": protocols_prompt,
        "skill_dirs": list(skill_dirs),
        "identity_prompt": "",
        "memory_prompt": "",
        "queen_phase": queen_phase,
        "queen_id": queen_id,
        "loop_config": build_loop_config_dict(queen_loop_config),
        "spawned_from": source_session_id,
        "spawned_at": datetime.now(UTC).isoformat(),
    }
    # Concurrency hint: copied into the per-worker spec so per-profile
    # clones inherit it. The colony-level max_concurrent_workers (set
    # on metadata.json from this same value at fork time) is what the
    # runtime actually enforces.
    if isinstance(concurrency_hint, int) and concurrency_hint > 0:
        meta["concurrency_hint"] = concurrency_hint
    return meta


__all__ = [
    # Runtime identity
    "DEFAULT_LOOP_CONFIG",
    "WORKER_SYSTEM_PROMPT",
    "build_system_prompt",
    "worker_goal",
    # Serialization
    "build_input_data",
    "build_loop_config_dict",
    "build_meta",
]
