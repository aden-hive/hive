"""Queen orchestrator — builds and runs the queen executor.

Extracted from SessionManager._start_queen() to keep session management
and queen orchestration concerns separate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time as _time_mod
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.agent_loop.internals.types import HookContext, HookResult
    from framework.loader.tool_registry import ToolRegistry
    from framework.server.session_manager import Session

logger = logging.getLogger(__name__)

# Maximum number of unanswered worker escalations the queen's inbox will
# buffer before auto-replying queue_full to new ones.
MAX_PENDING_ESCALATIONS = 32


def _make_pivot_payload_sink(session: Session):
    """Build the pivot_payload_sink callback for an AgentContext.

    Called by the ``task_create(new_colony=true)`` synthetic intercept
    in :mod:`framework.agent_loop.agent_loop` with the rich
    ``{goal, handoff, tasks, source_phase}`` payload the queen
    authored. The callback validates against session-level state the
    agent_loop can't see, then stashes the payload on the live Session
    so the popup-accept route handler
    (``_create_sibling_colony_from_colony``) can read it back.

    Returns None to accept, or a non-empty string to veto — the
    intercept surfaces vetoes as is_error tool results without opening
    the popup.
    """

    def sink(payload: dict) -> str | None:
        # Recursion base case: a colony that was itself just created by
        # a fork must not re-pivot on its synthetic kickoff turn — the
        # handoff seed may re-trigger divergence detection and chain-
        # fork (A → B → C → ...). The flag clears on the first genuine
        # user message in this colony.
        if getattr(session, "fork_kickoff_pending", False):
            return (
                "This colony was just created by a fork — its task plan "
                "already exists and this IS the new colony. Do NOT spawn "
                "another colony or re-create tasks. Call task_list to "
                "see the plan, then task_update to work it. new_colony "
                "becomes available again only after the user sends a new "
                "message in this colony."
            )
        # Concurrent-popup guard: one open popup at a time per session.
        if getattr(session, "pending_colony_pivot", None) is not None:
            return (
                "A new_colony popup is already open and waiting for the "
                "user. Do not call task_create(new_colony=true) again "
                "until the current popup resolves."
            )
        session.pending_colony_pivot = payload
        return None

    return sink


def _resolve_effective_max_concurrent_workers(session: Session) -> int:
    """Return the colony cap the runtime will actually enforce.

    Mirrors the lookup in ``SessionManager._start_unified_colony_runtime``
    (per-colony ``metadata.json`` ``max_concurrent_workers`` overrides the
    framework default in ``ColonyConfig``). Inlined rather than imported
    because the colony runtime is constructed *after* ``create_queen``
    returns, so ``session.colony`` does not exist yet at prompt-assembly
    time — but ``session.colony_id`` is already set when loading or
    forking into a colony.
    """
    from framework.host.colony_runtime import ColonyConfig

    colony_id = getattr(session, "colony_id", None)
    if colony_id:
        try:
            from framework.config import COLONIES_DIR

            meta_path = COLONIES_DIR / colony_id / "metadata.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                v = meta.get("max_concurrent_workers")
                if isinstance(v, int) and v > 0:
                    return v
        except Exception:
            logger.debug(
                "_resolve_effective_max_concurrent_workers: metadata read failed for colony_id=%s; falling back to default",
                colony_id,
                exc_info=True,
            )
    return ColonyConfig().max_concurrent_workers


def install_worker_escalation_routing(
    session: Session,
    *,
    colony_runtime: Any | None = None,
) -> str | None:
    """Install the colony-scoped worker escalation handler on the queen bus.

    Every worker ``escalate()`` call emits ESCALATION_REQUESTED stamped with
    colony_id (by StreamEventBus) and a request_id (by AgentLoop). This
    handler records the escalation in ``session.pending_escalations`` so the
    queen can look it up by request_id later, and surfaces it to the queen
    loop as an addressed [WORKER_ESCALATION] inject.

    When ``colony_runtime`` is provided the subscription is scoped with
    ``filter_colony`` so only escalations from workers in *this* queen's
    colony are delivered — cross-colony leakage is structurally impossible.
    Falls back to the raw session bus when no colony is attached.

    Returns the subscription id (for unsubscribe) or ``None`` on failure.
    """
    from framework.host.event_bus import EventType

    async def _on_worker_escalation(event):
        stream_id = event.stream_id or ""
        # Defensive: ignore any stray non-worker origin (e.g. queen).
        if not stream_id.startswith("worker:"):
            return
        worker_id = stream_id[len("worker:") :]
        data = event.data or {}
        request_id = data.get("request_id")
        reason = str(data.get("reason", "")).strip()
        context_text = str(data.get("context", "")).strip()
        node_label = event.node_id or "unknown_node"

        # Back-pressure: if the queen's inbox is full, auto-reply to the
        # worker so it unblocks instead of wedging forever.
        if len(session.pending_escalations) >= MAX_PENDING_ESCALATIONS:
            runtime = session.colony
            if runtime is not None and worker_id:
                try:
                    await runtime.inject_input(
                        worker_id,
                        "[QUEEN_REPLY] queue_full — queen inbox saturated; proceed with best judgment or retry later.",
                    )
                except Exception:
                    logger.warning(
                        "Failed to send queue_full reply to worker %s",
                        worker_id,
                        exc_info=True,
                    )
            return

        # Record the pending entry so reply_to_worker can address it.
        if request_id:
            session.pending_escalations[request_id] = {
                "request_id": request_id,
                "worker_id": worker_id,
                "colony_id": event.colony_id,
                "node_id": node_label,
                "reason": reason,
                "context": context_text,
                "opened_at": _time_mod.time(),
            }

        # Surface the escalation to the queen as an addressed
        # [WORKER_ESCALATION] message.
        lines = ["[WORKER_ESCALATION]"]
        if request_id:
            lines.append(f"request_id: {request_id}")
        lines.append(f"worker_id: {worker_id or 'unknown'}")
        lines.append(f"node_id: {node_label}")
        lines.append(f"reason: {reason or 'unspecified'}")
        if context_text:
            lines.append("context:")
            lines.append(context_text)
        if request_id:
            lines.append("Use reply_to_worker(request_id, reply) to unblock, or list_worker_questions() to see all pending.")
        else:
            lines.append("No request_id — use inject_message(content=...) to relay guidance manually.")
        handoff = "\n".join(lines)

        # Fallback: if the queen loop has gone away, publish a
        # CLIENT_INPUT_REQUESTED so the human sees the question and the
        # worker does not wedge.
        queen_node = session.queen_executor.node_registry.get("queen") if session.queen_executor is not None else None
        if queen_node is None or not hasattr(queen_node, "inject_event"):
            if session.event_bus is not None:
                # Stream the handoff text so the human sees the worker's
                # question, then request input so the reply input appears.
                await session.event_bus.emit_client_output_delta(
                    stream_id="queen",
                    node_id="queen",
                    content=handoff,
                    snapshot=handoff,
                    execution_id=session.id,
                )
                await session.event_bus.emit_client_input_requested(
                    stream_id="queen",
                    node_id="queen",
                    execution_id=session.id,
                )
            return

        await queen_node.inject_event(handoff, is_client_input=False)

    # Prefer colony-scoped subscription when a colony is loaded so
    # filter_colony does the isolation work for us.
    runtime = colony_runtime if colony_runtime is not None else session.colony
    if runtime is not None:
        try:
            return runtime.subscribe_to_events(
                [EventType.ESCALATION_REQUESTED],
                _on_worker_escalation,
                filter_colony=runtime.stream_id,
            )
        except Exception:
            logger.warning("Failed to install colony-scoped escalation sub", exc_info=True)
            # fall through to session bus
    if session.event_bus is None:
        return None
    return session.event_bus.subscribe(
        event_types=[EventType.ESCALATION_REQUESTED],
        handler=_on_worker_escalation,
    )


# Cache TTL for the ambient credentials block. The block is rebuilt at most
# once per this interval; routes_credentials.invalidate_credentials_cache()
# forces an immediate rebuild on save/delete.
_CREDENTIALS_BLOCK_TTL_SECONDS = 30.0


def _build_credentials_provider(session_id: str | None = None) -> Any:
    """Return a closure that renders the ambient credentials block.

    By default the Queen sees only a COMPACT summary (provider names +
    counts) — enough to know what's connected without dumping every account
    into the prompt. Full per-account detail is re-injected only for
    credentials the Queen explicitly attaches to THIS session via the
    ``credentials`` tool. The connected-accounts snapshot (the network-bound
    part) is cached briefly; session attachments are read fresh each call so
    an attach/detach shows up on the very next turn.
    """
    import time

    state: dict[str, Any] = {"accounts": None, "cached_at": 0.0}

    def _provider() -> str:
        from aden_tools.credentials.store_adapter import CredentialStoreAdapter

        from framework.agent_loop.internals.credential_tool import (
            attachment_matches,
            read_attachments,
        )
        from framework.orchestrator.prompting import (
            build_accounts_prompt,
            build_credentials_summary,
        )

        now = time.monotonic()
        if state["accounts"] is None or (now - state["cached_at"]) >= _CREDENTIALS_BLOCK_TTL_SECONDS:
            try:
                adapter = CredentialStoreAdapter.default()
                state["accounts"] = adapter.get_all_account_info()
            except Exception:
                logger.debug("Failed to snapshot connected accounts", exc_info=True)
                state["accounts"] = []
            state["cached_at"] = now

        accounts = state["accounts"] or []
        parts: list[str] = []

        summary = build_credentials_summary(accounts)
        if summary:
            parts.append(summary)

        # Attached (pinned) credentials get full detail re-injected each turn.
        try:
            refs = read_attachments(session_id)
        except Exception:
            refs = []
        if refs:
            attached = [a for a in accounts if attachment_matches(a, refs)]
            if attached:
                detail = build_accounts_prompt(attached)
                if detail:
                    parts.append("Pinned to this session:\n" + detail)

        return "\n\n".join(parts)

    def _invalidate() -> None:
        state["cached_at"] = 0.0

    _provider.invalidate = _invalidate  # type: ignore[attr-defined]
    return _provider


def initialize_memory_scopes(session: Session, phase_state: Any) -> tuple[Path, Path]:
    """Create and cache the global and queen-scoped memory directories."""
    from framework.agents.queen.queen_memory_v2 import (
        global_memory_dir,
        init_memory_dir,
        queen_memory_dir,
    )

    global_dir = global_memory_dir()
    queen_dir = queen_memory_dir(session.queen_name)
    init_memory_dir(global_dir)
    init_memory_dir(queen_dir)
    phase_state.global_memory_dir = global_dir
    phase_state.queen_memory_dir = queen_dir
    return global_dir, queen_dir


# The fixed Head-of-RevOps queen the CRM "Set up" / "Configure" buttons hand off
# to — the board the CRM renders IS a sales pipeline, and setup is a conversation
# about how this team's deals actually move. When she is active the session is
# about the CRM, so we force the current global state to be loaded before any
# change. Not sufficient on its own to mean "a setup session", though: she is an
# ordinary queen the user can also just talk to. ``Session.crm_setup`` is the
# label for that.
CRM_QUEEN_ID = "queen_sales"

# Always on for the CRM host queen, setup or not: she owns this team's board, so
# any change she makes has to start from its current state — which is the one
# thing the comment above says her identity IS sufficient to establish. Scoped to
# that mandate and to tooling hygiene; the setup PLAYBOOK is a separate string
# below, gated separately.
_CRM_STATE_DIRECTIVE = """\

# CRM — load the current state FIRST (mandatory)
Before you change ANYTHING in this team's CRM — before your first user-facing \
sentence about what to do — call the `crm_summary` tool. It returns the \
up-to-date GLOBAL picture: contact / company / opportunity counts and their \
lifecycle distribution, the custom fields already defined, data-quality signals, \
and this team's existing CRM steering rules. Base every change on what the \
summary returns and follow the steering rules it surfaces. The CRM will refuse \
writes until you have loaded it. Do not describe the tool, the data plumbing, or \
that you "loaded" anything to the user — just speak to their pipeline in \
business terms (you are their Head of RevOps, not their engineer).

# Never debug the CRM in front of the user
`hive-crm whoami --json` returns `commands.available` and \
`commands.not_in_this_build`. Read it once and route around what is missing. Do \
NOT run `--help` on one noun after another to discover the surface, and do NOT \
write a test/placeholder record to check whether writes work — the user sees \
every record you create, and watching you probe your own tooling reads as a \
broken product."""


# The setup PLAYBOOK — appended only while a setup handoff is actually owed.
#
# Every line here presumes the user is locked out of a CRM they have never seen:
# the two rounds of questions, the example records, the five-minute budget, and
# above all "your FINAL action of the turn is `hive-crm reveal` — always, and
# without being asked". In an ordinary post-setup chat that premise is simply
# false, and the reveal mandate is unconditional enough that the queen follows it
# anyway — handing a user who asked a casual question a fresh "your CRM's ready
# to explore" card. Hence the gate in `_with_crm_directives`: identity alone is
# NOT a setup session (see CRM_QUEEN_ID above), and a setup session whose reveal
# already happened is not one either.
_CRM_SETUP_DIRECTIVE = """\

# CRM configuration — you are here to configure this team's CRM
The `crm_summary` above also carries — automatically, for you — a `campaigns` \
INDEX of every existing campaign: each colony's one-line goal and its tracker \
tables with column names and a `row_count`. That index answers exactly ONE \
question — which campaign already produced leads worth importing — and `row_count` \
is the answer (see "do not hand back an EMPTY CRM" below). It carries no row \
values, and you must NOT go read colony databases to make up the difference. \
Campaigns are evidence of what this user has WORKED ON; they are NOT a \
specification of what their business is, and you must not infer their pipeline, \
their ICP or their fields from one. What they sell you learn by ASKING them.

# If the CRM is fresh or still on the default pipeline, ASK BEFORE YOU BUILD
When the summary comes back near-empty, or its `pipelines_configured.person` is \
false (this team is still on the stock pipeline), you do NOT yet know enough to \
recommend anything — you do not know what this user sells. Fill that gap by \
ASKING, and only by asking. Do not substitute a stock pipeline or a stale memory \
file — and do NOT go read their website or marketing pages. Their site tells you \
how they position, never how they sell; it is the slowest possible route to a \
worse answer than one question gets you, and the user is sitting on a locked \
screen while you browse. Map their sales process WITH \
them, starting from the product itself: what EXACTLY they sell and what the \
buyer walks away with (push past the category to the real thing), what makes \
someone buy or pass, who signs off, their most recent real deal end to end, where \
deals stall, what makes a lead worth their time, what they must know before \
calling one qualified, and what a deal is worth. A few questions per round is \
fine — the ROUND is the unit, and what matters is that round 2 is built from \
their round-1 answers rather than written in advance. You will not get all of \
that in two rounds and you should not try: ask what you need to build a board \
they recognize, and let the rest come from them correcting it.

EVERY QUESTION IN BOTH ROUNDS IS ABOUT THEIR BUSINESS, NOT THEIR DATA. Never \
spend a question on cleaning up stale records, on reconciling stage names against \
whatever is already stored, or on whether to import their existing contacts. None \
of that teaches you what they sell, and it turns a five-minute setup into data-ops \
decisions about a board they have not seen yet. Whatever is already in the CRM, \
leave it: build their pipeline from what they tell you, and show it to them. Any \
decision the stored data really needs comes AFTER the reveal, with the board in \
front of them — and bringing in their campaign leads is gated until then anyway.

AT LEAST TWO ROUNDS OF QUESTIONS BEFORE YOU CONFIGURE ANYTHING — a hard floor, \
not a target. One round only ever yields labels ("I sell to VCs", "enterprise \
SaaS"), which is exactly enough to build a generic template and no more. Round 1 \
establishes what the business IS (what they sell, what the buyer gets, who signs \
off). Round 2 is built FROM their round-1 answers, not from a pre-written list — \
walk me through your last real deal, where did it stall, what made it worth your \
time, what did you need to know before taking the call. NEVER write schema in \
the same turn as the first answer: if you are reaching for `stages set` or \
`fields add` after one exchange, you do not yet know enough — ask the second \
round first. But two rounds is also the NORMAL number: a third only if an \
answer genuinely opened something up, and never a fourth. You are not trying to \
understand their business completely — only well enough to build a first board \
they recognize, which they will correct once they can see it.

You are their Head of RevOps, so as you build, say the ONE thing you would \
change about how they sell — a leak in the process, a qualification bar set too \
loose or too tight, something they should be tracking and aren't. One \
observation, offered as a recommendation they can reject, in the same breath as \
the work. Not a consulting report, not its own turn, never instead of \
configuring.

Then make their answers REAL: their stages (in their words, in their order, with \
the gate on each) via `hive-crm stages set`, and the facts they track via \
`hive-crm fields add` — 4-8 fields specific to THEIR business, and then actually \
populate them (`person add --field name=value`), because a declared field nobody \
fills is a permanently empty column. Resist a ninth: fields are trivial to add \
later with the user watching the board, and every one you declare now is one you \
owe a value for on every record you write. A pipeline captured only as prose in \
`hive-crm memory` is invisible to the user — they will open the CRM and see the \
same generic template they started with, which is a failed setup no matter how \
good the conversation was. Use memory for behavior and judgment, never for \
structure.

Name stages after what the BUYER has done ("replied", "took a demo", "pilot \
running"), never after your own activity ("emailed", "followed up") — an \
activity board looks busy and tells the user nothing about which deals are real.

Finally, do not hand back an EMPTY CRM — it teaches nothing and feels broken. \
Fill it in TWO STAGES, in this order, and the order is enforced:

(1) BEFORE you reveal: write 3-5 records YOURSELF that are PLAUSIBLE for this \
specific business, with the custom fields filled and spread across stages so the \
board reads. Build them from what THIS user told you they sell — if you are \
inventing a vertical they never mentioned, stop and use theirs. Say plainly they \
are examples you will replace with their real data. Never junk placeholders \
("Test Person", test@example.com): the user sees everything you leave behind. \
That is enough to reveal — you are NOT waiting for real data here.

DO NOT PREPARE THE IMPORT BEFORE YOU REVEAL. The reveal needs nothing from you \
about the campaign data — no chosen campaign, no column mapping, no plan. So \
before revealing: do not open a colony's tracker, do not work out which columns \
map to which fields, do not decide which campaign to pull in. Being confident \
about the import is not a precondition for revealing; it is the conversation you \
have AFTER, with the user, who is the one who knows which list is real. Anything \
you prepare first is prepared blind — if they choose a different campaign, or \
none, it is all thrown away, and every minute of it was a minute they sat locked \
out of a CRM you had already finished building.

(2) AFTER the reveal: `hive-crm import` is REFUSED until the user has seen their \
board (exit 6, `reveal_required`) — that is the ordering, not an error to route \
around. Once revealed, if the `campaigns` index shows a tracker table with a \
non-zero `row_count`, pull it in with `hive-crm import --file`; you supply the \
column mapping and the bulk upsert is done for you. When more than one campaign \
has data, ASK which one matters rather than taking the biggest — the largest \
table is usually a scraped list, not their pipeline. Then DELETE the example \
records you wrote, so the board is not part fiction. Tell the user in one line \
what landed. The big import running while they are already looking at their \
board is the entire point: they are never locked out waiting for it.

DO NOT RESEARCH INDIVIDUAL COMPANIES OR PEOPLE DURING SETUP. No `web_scrape`, \
no browser, no looking up a prospect's headcount or funding round to fill a \
field — not for imported rows, not for records that were already in the CRM \
before you started. If you do not know a value, leave it blank or write the \
plausible one. Enrichment is real work, but it is work you offer AFTER the \
reveal, as its own task the user opts into. A single company lookup is the \
first step of a twenty-minute detour that ends with the user still unable to \
see their CRM.

Likewise: do not audit or clean up records that predate this session. They are \
not your setup's problem, and a board with some older rows in it is far better \
than a board the user cannot open yet.

# Setup is a FIVE MINUTE job — reveal early, refine after
The user was told this takes about five minutes, and they are staring at a \
locked setup screen until you reveal. Treat that as the budget: roughly two \
rounds of questions, stages, fields, something in the board, reveal. If you have \
been working for more than about ten minutes and have not revealed, you have \
already gone wrong — stop whatever you are perfecting and reveal what you have.

Reveal is a CHECKPOINT, not a finish line. The board does not have to be \
finished or complete; it has to be honest and recognizable — their stages in \
their words, columns that read as their business, a few records so it is not \
blank, and nothing they would have to explain away. That bar is reachable in \
minutes. Everything past it — more fields, real leads, enrichment, cleanup — is \
better done WITH them looking at the board than in front of a locked screen, \
because that is when their corrections start, and their corrections are worth \
more than your extra polish.

The only thing that justifies delaying a reveal is that the board would \
genuinely embarrass them: stock template columns, or zero records. Not "I could \
make this better."

# `hive-crm reveal` — run it, or the user never sees the CRM (mandatory)
"Reveal" is a COMMAND you run, not a quality bar you describe. Running \
`hive-crm reveal` is the ONLY thing that gives the user a button to open their \
CRM. Until you run it they are still sitting on the setup prompt — no matter how \
much you configured, no matter how clearly you summarized it. A report is not a \
reveal: telling them what you built while they have no way to look at it is the \
single worst way to end a setup turn.

So: as soon as the CRM clears that bar, your FINAL action of the turn is \
`hive-crm reveal` — always, and without being asked. If you ever find yourself \
writing "I'm done" or "that's the finished configuration", you should already \
have run it. Never make the user ask you to reveal, and never answer "is it \
done?" with anything but a reveal or a one-line reason you are not ready.

Keep the message you send alongside it SHORT — two or three plain sentences on \
what is there and what you would do next. No headers, no "Done / Not done" \
lists, no tables, no dumps of the summary JSON. Never announce the CRM as \
complete: configuration continues after the reveal."""


async def materialize_queen_identity(
    session: Session,
    phase_state: Any,
    queen_profile: dict,
    event_bus: Any,
) -> None:
    """Format the queen identity prompt and set phase state.

    Called after SessionManager has resolved and loaded the profile.
    This function does no I/O — it only formats and caches.
    """
    from framework.agents.queen.queen_profiles import format_queen_identity_prompt
    from framework.host.event_bus import AgentEvent, EventType

    queen_id = session.queen_name

    phase_state.queen_id = queen_id
    phase_state.queen_profile = queen_profile
    # max_examples=0 omits the <roleplay_examples> block from the live prompt;
    # <behavior_rules> still drives the internal assessment. Examples remain in
    # profiles for authoring/eval (format with max_examples=None to render them).
    phase_state.queen_identity_prompt = format_queen_identity_prompt(queen_profile, max_examples=0)

    if event_bus is not None:
        await event_bus.publish(
            AgentEvent(
                type=EventType.QUEEN_IDENTITY_SELECTED,
                stream_id="queen",
                data={
                    "queen_id": queen_id,
                    "name": queen_profile.get("name", ""),
                    "title": queen_profile.get("title", ""),
                },
            )
        )


_SCOPE_SENSITIVE_MCP_SERVERS: frozenset[str] = frozenset({"memory-tools"})
"""MCP servers whose subprocesses bind to a queen/colony scope via env vars
(e.g. memory-tools reads HIVE_QUEEN_ID at startup). The bare bootstrap
registry is queen-agnostic, so spawning these here would pool a stale
empty-env subprocess that later queen sessions would silently inherit
(returning ``scope_unbound`` from every tool call). Real queen sessions
load these servers through queen_orchestrator's slow path with the right
env injected, so skipping them in the bootstrap is safe."""


def build_queen_tool_registry_bare() -> tuple[Any, dict[str, list[dict[str, Any]]]]:
    """Build a Queen ``ToolRegistry`` and a (server_name → tools) catalog.

    Used by the Tool Library GET route to populate the MCP tool surface
    without needing a live queen session. We DO NOT register queen
    lifecycle tools here (they require a Session stub); the catalog only
    covers MCP-origin tools, which is what the allowlist gates.

    Loading MCP servers spawns subprocesses, so call this once per
    backend process and cache the result. Scope-sensitive servers (those
    whose subprocesses read identity env vars set per queen session) are
    excluded — their tools are added to the catalog by the queen session
    that owns the scope, not by this queen-agnostic bootstrap.
    """
    from pathlib import Path

    import framework.agents.queen as _queen_pkg
    from framework.loader.mcp_registry import MCPRegistry
    from framework.loader.tool_registry import ToolRegistry

    queen_registry = ToolRegistry()
    queen_pkg_dir = Path(_queen_pkg.__file__).parent

    mcp_config = queen_pkg_dir / "mcp_servers.json"
    if mcp_config.exists():
        try:
            queen_registry.load_mcp_config(mcp_config)
        except Exception:
            logger.warning("build_queen_tool_registry_bare: MCP config failed", exc_info=True)

    try:
        reg = MCPRegistry()
        reg.initialize()
        if (queen_pkg_dir / "mcp_registry.json").is_file():
            queen_registry.set_mcp_registry_agent_path(queen_pkg_dir)
        registry_configs, selection_max_tools = reg.load_agent_selection(queen_pkg_dir)
        registry_configs = [c for c in registry_configs if c.get("name") not in _SCOPE_SENSITIVE_MCP_SERVERS]

        already = {cfg.get("name") for cfg in registry_configs if cfg.get("name")}
        extra: list[str] = []
        try:
            for entry in reg.list_installed():
                if entry.get("source") != "local":
                    continue
                if not entry.get("enabled", True):
                    continue
                name = entry.get("name")
                if not name or name in already:
                    continue
                if name in _SCOPE_SENSITIVE_MCP_SERVERS:
                    continue
                extra.append(name)
        except Exception:
            pass
        if extra:
            try:
                extra_configs = reg.resolve_for_agent(include=extra)
                registry_configs = list(registry_configs) + [reg._server_config_to_dict(c) for c in extra_configs]
            except Exception:
                logger.debug("build_queen_tool_registry_bare: resolve_for_agent(extra) failed", exc_info=True)

        if registry_configs:
            queen_registry.load_registry_servers(
                registry_configs,
                preserve_existing_tools=True,
                log_collisions=False,
                max_tools=selection_max_tools,
            )
    except Exception:
        logger.warning("build_queen_tool_registry_bare: MCP registry load failed", exc_info=True)

    # Build the catalog from the registry's pre-credential-gate snapshot
    # so the Tool Library can list every credentialed tool — including
    # those whose provider isn't authorized yet — and the UI can show a
    # greyed-out row + Connect button. The strict admission gate still
    # governs what the queen actually sees in her prompt.
    full_catalog = queen_registry.get_full_mcp_catalog()
    catalog: dict[str, list[dict[str, Any]]] = {}
    for server_name in sorted(full_catalog):
        catalog[server_name] = sorted(
            (dict(entry) for entry in full_catalog[server_name]),
            key=lambda e: e.get("name", ""),
        )

    return queen_registry, catalog


# Serializes the lazy tool-registry bootstrap. Without this, the startup burst
# of concurrent GET /api/{queen,colony}/.../tools requests each see an unset
# manager._bootstrap_tool_registry and run build_queen_tool_registry_bare() in
# parallel — spawning every MCP server and re-probing every credential N times.
_bootstrap_registry_lock = asyncio.Lock()


async def ensure_bootstrap_tool_registry(manager: Any) -> Any | None:
    """Build the queen-agnostic MCP tool registry at most once per process.

    Both the queen-tools and colony-tools routes call this. The lock plus a
    double-checked read of ``manager._bootstrap_tool_registry`` collapses the
    startup request burst to a single build. On failure the attribute is left
    unset so the next request retries rather than caching a broken state.
    """
    registry = getattr(manager, "_bootstrap_tool_registry", None)
    if registry is not None:
        return registry
    async with _bootstrap_registry_lock:
        registry = getattr(manager, "_bootstrap_tool_registry", None)
        if registry is not None:
            return registry
        try:
            registry, _initial = await asyncio.to_thread(build_queen_tool_registry_bare)
        except Exception:
            logger.warning("Tool catalog bootstrap failed", exc_info=True)
            return None
        manager._bootstrap_tool_registry = registry
        return registry


async def create_queen(
    session: Session,
    session_manager: Any,
    worker_identity: str | None,
    queen_dir: Path,
    queen_profile: dict,
    initial_prompt: str | None = None,
    initial_phase: str | None = None,
    tool_registry: ToolRegistry | None = None,
) -> asyncio.Task:
    """Build the queen executor and return the running asyncio task.

    Handles tool registration, phase-state initialization, prompt
    composition, queen identity materialization, colony preparation, and the queen
    event loop.
    """
    from framework.agents.queen.agent import (
        queen_colony_loop_config as _colony_loop_config,
        queen_goal,
        queen_loop_config as _base_loop_config,
    )
    from framework.agents.queen.nodes import (
        _QUEEN_COLONY_TOOLS,
        _QUEEN_INDEPENDENT_TOOLS,
        _queen_behavior_always,
        _queen_behavior_colony,
        _queen_behavior_independent,
        _queen_character_core,
        _queen_role_colony,
        _queen_role_independent,
        _queen_tools_colony,
        _queen_tools_independent,
        finalize_queen_prompt,
    )
    from framework.config import get_max_tokens as _get_max_tokens
    from framework.host.event_bus import AgentEvent, EventType
    from framework.llm.capabilities import supports_image_tool_results
    from framework.loader.mcp_registry import MCPRegistry
    from framework.loader.tool_registry import ToolRegistry
    from framework.tools.queen_lifecycle_tools import (
        QueenPhaseState,
        normalize_legacy_phase,
        register_queen_lifecycle_tools,
    )

    # ---- Tool registry ------------------------------------------------
    # Use pre-loaded cached registry if available (fast path)
    if tool_registry is not None:
        queen_registry = tool_registry
        logger.info("Queen: using pre-loaded tool registry with %d tools", len(queen_registry.get_tools()))
    else:
        # Build fresh (slow path - for backwards compatibility)
        queen_registry = ToolRegistry()
        # Inject the queen's identity into every MCP subprocess this
        # registry spawns. The memory-tools server reads HIVE_QUEEN_ID
        # to scope `search_messages` to this queen's own history (the
        # model never picks the scope itself). Set BEFORE MCP servers
        # are registered, since env is captured at MCPClient construction.
        queen_registry.set_mcp_extra_env({"HIVE_QUEEN_ID": session.queen_name or "default"})
        import framework.agents.queen as _queen_pkg

        queen_pkg_dir = Path(_queen_pkg.__file__).parent
        mcp_config = queen_pkg_dir / "mcp_servers.json"
        if mcp_config.exists():
            try:
                queen_registry.load_mcp_config(mcp_config)
                logger.info("Queen: loaded MCP tools from %s", mcp_config)
            except Exception:
                logger.warning("Queen: MCP config failed to load", exc_info=True)

        try:
            registry = MCPRegistry()
            registry.initialize()
            if (queen_pkg_dir / "mcp_registry.json").is_file():
                queen_registry.set_mcp_registry_agent_path(queen_pkg_dir)
            registry_configs, selection_max_tools = registry.load_agent_selection(queen_pkg_dir)

            # Auto-include every user-added local MCP server that the repo
            # selection hasn't already loaded. Users register servers via
            # the `/api/mcp/servers` route (or `hive mcp add`); they live in
            # ~/.hive/mcp_registry/installed.json with source == "local".
            # New servers take effect on the next queen session start; the
            # prompt cache and ToolRegistry are still loaded once per boot.
            already_loaded_names = {cfg.get("name") for cfg in registry_configs if cfg.get("name")}
            extra_names: list[str] = []
            try:
                for entry in registry.list_installed():
                    if entry.get("source") != "local":
                        continue
                    if not entry.get("enabled", True):
                        continue
                    name = entry.get("name")
                    if not name or name in already_loaded_names:
                        continue
                    extra_names.append(name)
            except Exception:
                logger.debug("Queen: list_installed() failed while auto-including user servers", exc_info=True)

            if extra_names:
                try:
                    extra_configs = registry.resolve_for_agent(include=extra_names)
                    extra_dicts = [registry._server_config_to_dict(c) for c in extra_configs]
                    registry_configs = list(registry_configs) + extra_dicts
                    logger.info(
                        "Queen: auto-including %d user-added MCP server(s): %s",
                        len(extra_dicts),
                        [c.get("name") for c in extra_dicts],
                    )
                except Exception:
                    logger.warning(
                        "Queen: failed to resolve user-added MCP servers %s",
                        extra_names,
                        exc_info=True,
                    )

            if registry_configs:
                results = queen_registry.load_registry_servers(
                    registry_configs,
                    preserve_existing_tools=True,
                    log_collisions=True,
                    max_tools=selection_max_tools,
                )
                logger.info("Queen: loaded MCP registry servers: %s", results)
        except Exception:
            logger.warning("Queen: MCP registry config failed to load", exc_info=True)

    # ---- Phase state --------------------------------------------------
    # Phase resolution cascade — first non-empty wins:
    #   1. explicit ``initial_phase`` from caller (tests, tool-driven boot)
    #   2. meta.json["phase"] on disk — the canonical persisted answer
    #      written by every prior phase transition. Survives restarts.
    #   3. physical session bindings (colony_id / binding / worker_path)
    #      populated by _load_worker_core or the queen-only colony bootstrap
    #   4. fall back to "independent"
    # QueenPhaseState then owns meta.json on every subsequent switch, so
    # the canonical answer stays in sync without scattered _update_meta_json
    # calls in tool handlers.
    meta_path = queen_dir / "meta.json"
    persisted_phase: str | None = None
    # Tools the queen loaded via ``search_tools`` in a prior run of this
    # session. Restored (and healed against the current allowlist/catalog)
    # further down so a restart keeps them loaded without re-searching.
    persisted_loaded_tools: list[str] = []
    if meta_path.exists():
        try:
            _persisted = json.loads(meta_path.read_text(encoding="utf-8"))
            persisted_phase = normalize_legacy_phase(_persisted.get("phase"))
            _lt = _persisted.get("loaded_tools")
            if isinstance(_lt, list):
                persisted_loaded_tools = [str(n) for n in _lt if isinstance(n, str)]
            # A setup conversation that spans a restart is still a setup
            # conversation. Sticky by design: the flag only ever arrives on
            # create, and a resume passes no body at all.
            if _persisted.get("crm_setup"):
                session.crm_setup = True
        except (json.JSONDecodeError, OSError):
            persisted_phase = None
    bound_to_colony = bool(session.colony_id or session.binding or session.worker_path)
    effective_phase = initial_phase or persisted_phase or ("colony" if bound_to_colony else "independent")
    phase_state = QueenPhaseState(
        phase=effective_phase,
        event_bus=session.event_bus,
        meta_path=meta_path,
    )
    # Stamp the resolved phase into meta.json so a freshly created queen
    # that never calls switch_to_* still leaves a canonical answer for
    # the next cold-resume.
    phase_state.persist_phase()
    if getattr(session, "crm_setup", False):
        phase_state.persist_crm_setup()
    session.phase_state = phase_state

    # ---- Ambient credentials provider --------------------------------
    # Renders the "Connected integrations" block injected into every Queen
    # phase prompt so the Queen always knows which credentials are connected
    # without having to call list_credentials. Cached briefly to keep the
    # per-iteration prompt rebuild cheap; invalidated by routes_credentials
    # when the user adds/removes an integration.
    phase_state.credentials_prompt_provider = _build_credentials_provider(session.id)

    # ---- Lifecycle tools (always registered) --------------------------
    register_queen_lifecycle_tools(
        queen_registry,
        session=session,
        session_id=session.id,
        session_manager=session_manager,
        manager_session_id=session.id,
        phase_state=phase_state,
    )

    # ---- Task system tools --------------------------------------------
    # Every queen gets the four session task tools. The queen ALSO gets
    # a pivot field on task_create that varies by phase: DM queens see
    # `new_session` (fork into a fresh DM session), colony queens see
    # `new_colony` (spawn a sibling colony). The wiring below picks one
    # PivotHandler per phase; the task system itself stays generic.
    # Workers / colony stages pass no handler, so the field is absent
    # from their schema entirely.
    from framework.tasks.tools import register_task_tools
    from framework.tasks.tools.session_tools import PivotHandler

    _NEW_SESSION_DESC = (
        "Whether to start this plan in a fresh session. Default false. "
        "This is the DM-phase pivot field; in COLONY phase the equivalent "
        "is `new_colony` (different field, same criteria — see `<pivot>` "
        "in the queen prompt for the universal contract).\n\n"
        "Set true ONLY for a clean pivot: the user introduces big new "
        "work that shares no goal, files, or topic with the current task "
        "list — typically the prior task is finished and they ask for "
        "something unrelated.\n\n"
        "Examples of the boundary:\n"
        "- Just finished pulling a news digest; user says 'now start a "
        "CTO sourcing campaign.' -> new session (true): zero overlap "
        "with the digest.\n"
        "- Running a CTO sourcing campaign; user says 'tweak the scoring "
        "rubric.' -> same session (false): it refines the work already "
        "underway.\n\n"
        "When true: a fresh session is created carrying ONLY your "
        "`handoff` note and this `tasks` plan — the old conversation is "
        "left behind, not copied or summarized. The user is silently "
        "swapped into it. Set this on your FIRST tool call of the turn, "
        "then end the turn — the new session's queen continues the work "
        "from there.\n\n"
        "Keep it false for follow-ups, clarifications, continuations, "
        "or anything that touches the current plan. When unsure, ask "
        "the user before forking."
    )

    _NEW_COLONY_DESC = (
        "Whether to spawn a NEW colony for this plan. Default false. "
        "This is the COLONY-phase pivot field; in DM the equivalent is "
        "`new_session` (different field, same criteria — see `<pivot>` "
        "in the queen prompt for the universal contract).\n\n"
        "Set true ONLY when the user has clearly pivoted to work that "
        "doesn't belong in THIS colony — a different goal, different "
        "tracker shape, different cadence. A colony is scoped by "
        "construction; off-goal work should live in its own colony, not "
        "be absorbed silently into this one.\n\n"
        "Examples of the boundary:\n"
        "- This colony tracks competitor pricing weekly; user says "
        "'also build a daily news digest' -> new colony (true): "
        "different goal AND different cadence.\n"
        "- This colony tracks competitor pricing; user says 'also add "
        "headcount tracking for these same competitors' -> same colony "
        "(false): same row shape, related signal.\n\n"
        "When true: a 'Create Colony' popup opens for the user with the "
        "slug field blank — they fill in the name and confirm. On "
        "accept, a fresh colony is spawned carrying ONLY your `handoff` "
        "brief and this `tasks` plan (no transcript, no compaction), "
        "and the user is navigated to it. This colony stays alive and "
        "untouched. On dismiss, the tool returns failure and you must "
        "call `ask_user` to decide what to do — do NOT silently add the "
        "off-goal tasks to this colony's list. After accept, end_turn "
        "immediately — you (this colony's queen) stay idle here, the "
        "new colony's queen takes over there."
    )

    async def _fork_session_with_task_plan(*, goal, handoff, tasks):
        """Handler for task_create(new_session=true) — DM phase only.

        Forks the queen's session into a fresh, lean one. Nothing is
        copied or summarized from the old session — the new session
        carries only the queen-authored ``handoff`` brief and this task
        plan. The frontend then swaps the user there.
        """
        # Recursion base case: a session that was itself just created by
        # a fork must not fork again on its synthetic kickoff turn — the
        # pivot was already consumed. The flag clears on the first
        # genuine user message (see handle_chat). Without this, the
        # forked session re-reads the inherited pivot context and forks
        # endlessly (A -> B -> C -> ...).
        if getattr(session, "fork_kickoff_pending", False):
            return {
                "success": False,
                "error": (
                    "This session was just created by a fork — its task "
                    "plan already exists and this IS the new session. Do "
                    "NOT start another new session or re-create tasks. "
                    "Call task_list to see the plan, then task_update to "
                    "work it. new_session becomes available again only "
                    "after the user sends a new message in this session."
                ),
            }
        # Defense in depth: a queen booted in DM phase could have
        # transitioned to colony via switch_to_colony without restarting
        # — the schema's new_session field is still wired even though
        # the queen is now structurally inside a colony.
        if phase_state is not None and phase_state.phase != "independent":
            return {
                "success": False,
                "error": (
                    f"new_session is only available in the 'independent' phase (currently '{phase_state.phase}'). "
                    "This queen is inside a colony — new scope belongs in a new chat or a new colony, not a forked session here."
                ),
            }
        if session_manager is None:
            return {
                "success": False,
                "error": "session_manager not available; cannot fork a new session.",
            }
        # Hard gate: the new session inherits NOTHING from this
        # conversation except the handoff. An empty handoff would fork a
        # session that starts blind — only the bare task list, no goal,
        # no data, no decisions. Refuse before forking so the queen
        # retries with a real handoff instead of silently producing a
        # context-less session.
        if not (handoff or "").strip():
            return {
                "success": False,
                "error": (
                    "new_session=true requires a `handoff`, and you did "
                    "not provide one. The new session inherits NOTHING "
                    "from this conversation — without a handoff it starts "
                    "blind. Call task_create again with a COMPLETE, "
                    "objective handoff: the user's goal in their terms, "
                    "the concrete data (names, URLs, IDs, file paths, the "
                    "account to use, exact requirements), decisions made "
                    "and options ruled out, constraints, and what 'done' "
                    "looks like."
                ),
            }
        from framework.server.routes_execution import (
            ForkSessionError,
            fork_queen_session_for_split,
        )

        try:
            result = await fork_queen_session_for_split(
                session=session,
                manager=session_manager,
                handoff=(handoff or "").strip() or None,
                publish_event=True,
                tasks=tasks,
                goal=goal,
            )
        except ForkSessionError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — surface as soft tool error
            logger.exception("task_create(new_session): unexpected fork failure")
            return {"success": False, "error": f"unexpected fork failure: {exc}"}

        task_ids = result.get("task_ids", [])
        return {
            "success": True,
            "new_session": True,
            "new_session_id": result["new_session_id"],
            "compacted_from": result["compacted_from"],
            "task_ids": task_ids,
            "message": (
                f"Forked into a fresh session ({result['new_session_id']}) "
                f"and seeded {len(task_ids)} task(s). The user has been "
                f"silently swapped there."
            ),
            "instruction": (
                "The user is now in the new session, where this task plan "
                "lives. Do NOT produce any further response in this turn — "
                "end_turn now. The new session's queen picks up the user's "
                "latest message and works the plan there."
            ),
        }

    async def _request_new_colony_with_plan(*, goal, handoff, tasks):
        """Defensive stub — should never run in practice.

        ``task_create(new_colony=true)`` is intercepted synthetically in
        ``AgentLoop`` (search for ``_pending_colony_pivot`` in
        agent_loop.py): the intercept stashes the rich payload on
        ``session.pending_colony_pivot`` via the ``pivot_payload_sink``
        callback wired below, sets ``user_input_requested=True``, and
        returns a "popup opened" tool result — all BEFORE the registered
        executor runs.

        Going through the executor would re-introduce the 60s
        ``tool_call_timeout_seconds`` cancel that broke the original
        await-on-future implementation (linkedin_4 session
        ``20260519_165518``: queen called the pivot correctly, framework
        cancelled at 60s, queen fell back to doing the off-goal work
        inline). If somehow this stub runs, surface a clear internal
        error instead of silently re-introducing the bug.
        """
        return {
            "success": False,
            "error": (
                "internal: task_create(new_colony=true) reached the "
                "executor instead of being handled by the agent_loop "
                "synthetic intercept. This is a wiring bug — the "
                "intercept at agent_loop.py "
                "(`elif tc.tool_name == 'task_create' and "
                "tc.tool_input.get('new_colony') is True:`) should fire "
                "first."
            ),
        }

    if phase_state.phase == "independent":
        _pivot_handler = PivotHandler(
            field_name="new_session",
            field_description=_NEW_SESSION_DESC,
            handle=_fork_session_with_task_plan,
        )
    else:
        _pivot_handler = PivotHandler(
            field_name="new_colony",
            field_description=_NEW_COLONY_DESC,
            handle=_request_new_colony_with_plan,
        )
    register_task_tools(queen_registry, pivot_handler=_pivot_handler)

    # ---- Worker monitoring tools (only when a colony is bound) -----------
    if session.colony_id:
        from framework.tools.worker_monitoring_tools import register_worker_monitoring_tools

        register_worker_monitoring_tools(
            queen_registry,
            session.worker_path,
            worker_graph_id=None,
            default_session_id=session.id,
        )

    # ---- Tracker tools ------------------------------------------------
    # The queen always gets all three (tracker_sql, tracker_register_writable,
    # tracker_upsert). Phase tool lists in agents/queen/nodes filter which
    # ones are visible per phase; the tracker tools are listed in WORKING
    # and REVIEWING only. Workers inherit tracker_upsert through the fork
    # snapshot — the queen-only pair is filtered out by
    # ``_resolve_queen_only_tools`` so they never appear in worker.json.
    from framework.tools.tracker_tools import register_tracker_tools

    register_tracker_tools(queen_registry)

    # Browser discovery tool: browser_setup keeps the terminal-driven `hive-browser`
    # CLI discoverable (the runtime sees tool names, not subprocess calls) and its
    # `browser_` prefix pre-activates the browser-automation skill. Read-only.
    from framework.tools.browser_tools import register_browser_tools

    register_browser_tools(queen_registry)

    queen_tools = list(queen_registry.get_tools().values())
    queen_tool_executor = queen_registry.get_executor()

    # Phase 2 wiring: stash the resolved tool list + executor on the
    # session so SessionManager._start_queen can build a real
    # ColonyRuntime sharing the queen's tools, llm, and event bus.
    # The unified runtime is what run_worker (Phase 4) will
    # call into to fan out parallel workers from the queen.
    session._queen_tools = queen_tools  # type: ignore[attr-defined]
    session._queen_tool_executor = queen_tool_executor  # type: ignore[attr-defined]
    # Tool Library live-session reads need the registry, not just the flat
    # tool list, so server-scoped defaults like @server:files-tools can
    # expand correctly while a queen DM is active.
    session._queen_tool_registry = queen_registry  # type: ignore[attr-defined]

    # ---- Partition tools by phase ------------------------------------
    independent_names = set(_QUEEN_INDEPENDENT_TOOLS)
    colony_ids = set(_QUEEN_COLONY_TOOLS)
    mcp_server_tools_map: dict[str, set[str]] = dict(getattr(queen_registry, "_mcp_server_tools", {}))
    mcp_tool_names_all = set().union(*mcp_server_tools_map.values()) if mcp_server_tools_map else set()

    registered_names = {t.name for t in queen_tools}
    logger.info("Queen: registered tools: %s", sorted(registered_names))

    # Visibility for the "tool silently missing" failure mode. A bundled
    # server absent from this boot snapshot means its tools (e.g. chart_render
    # from chart-tools) won't exist in the live catalog even though the Tool
    # Library still shows them as allowlisted — so search_tools reports them as
    # "no such tool". The cap-exemption above prevents the budget-driven drop;
    # this warns if one still fails to register (e.g. a transient connect flake).
    from framework.loader.mcp_registry import DEFAULT_LOCAL_SERVER_NAMES

    # Works on both the fast (pre-loaded) and slow registry paths since it only
    # reads the live snapshot. A bundled server can be absent for two reasons:
    # it failed to start (the bug — its allowlisted tools then silently vanish
    # and search_tools reports them as "no such tool"), or the user deliberately
    # disabled it. We can't tell them apart here, so the message covers both
    # rather than asserting a failure.
    missing_essential = sorted(DEFAULT_LOCAL_SERVER_NAMES - set(mcp_server_tools_map))
    if missing_essential:
        logger.warning(
            "Queen %s: bundled MCP server(s) absent from this session's catalog: %s — "
            "their tools won't exist in the live catalog even if still allowlisted. "
            "If unexpected (not deliberately disabled), this is likely a transient MCP "
            "startup failure that a session restart usually recovers.",
            session.queen_name,
            missing_essential,
        )

    # Phase lists gate Hive lifecycle/system tools (run_worker,
    # trigger controls, etc.). User-configurable MCP tools should not
    # disappear just because the queen changes phase, so MCP-origin tools
    # (browser_*, web integrations, file tools, etc.) are appended to
    # every phase and then filtered by the per-queen MCP allowlist.
    mcp_tools = [t for t in queen_tools if t.name in mcp_tool_names_all]

    # Phase tool lists in ``agents/queen/nodes`` are the single source of
    # truth and may include the names of phase-gated synthetic tools
    # (e.g. ``suggest_colony``). Synthetics aren't in the queen registry
    # because their dispatch is intercepted framework-side in AgentLoop
    # before the executor runs, so we fall through to the builder map
    # for any name not found in ``queen_tools``.
    from framework.agent_loop.internals.synthetic_tools import (
        SYNTHETIC_PHASE_TOOL_BUILDERS,
    )

    def _phase_tools(system_names: set[str]) -> list:
        seen: set[str] = set()
        out = []
        registry_resolved = [t for t in queen_tools if t.name in system_names]
        synthetic_resolved = [builder() for name, builder in SYNTHETIC_PHASE_TOOL_BUILDERS.items() if name in system_names]
        for tool in registry_resolved + synthetic_resolved + mcp_tools:
            if tool.name in seen:
                continue
            seen.add(tool.name)
            out.append(tool)
        return out

    phase_state.independent_tools = _phase_tools(independent_names)
    phase_state.colony_tools = _phase_tools(colony_ids)

    logger.info(
        "Queen: independent tools: %s",
        sorted(t.name for t in phase_state.independent_tools),
    )
    logger.info(
        "Queen: colony tools: %s",
        sorted(t.name for t in phase_state.colony_tools),
    )

    # ---- Per-queen MCP tool allowlist --------------------------------
    # Capture the set of MCP-origin tool names so the allowlist in
    # ``QueenPhaseState`` only gates MCP tools (lifecycle and synthetic
    # tools always pass through). Then apply the queen profile's stored
    # allowlist (if any) and memoize the filtered independent tool list.
    phase_state.mcp_tool_names_all = mcp_tool_names_all
    # The queen's MCP tool allowlist now lives in a dedicated
    # ``tools.json`` sidecar next to ``profile.yaml``. ``load_queen_tools_config``
    # migrates any legacy ``enabled_mcp_tools`` field out of profile.yaml
    # on first read, so existing installs upgrade silently.
    from framework.agents.queen.queen_tools_config import load_queen_tools_config

    # Build a minimal catalog for default-tool resolution. The full
    # ``session_manager._mcp_tool_catalog`` snapshot is written further
    # down the flow; a queen booted for the first time needs the catalog
    # now so ``@server:NAME`` shorthands in the role-default table can
    # expand against the just-loaded MCP servers.
    _boot_catalog: dict[str, list[dict]] = {srv: [{"name": name} for name in sorted(names)] for srv, names in mcp_server_tools_map.items()}
    # ``queen_dir`` is ``queens/<queen_id>/sessions/<session_id>``; the
    # allowlist sidecar is keyed by queen_id, not session_id.
    phase_state.enabled_mcp_tools = load_queen_tools_config(session.queen_name, _boot_catalog)
    # Always-enabled / searchable split. ``always_enabled_names`` is the global
    # eager set (file ops, terminal, context helpers); everything else the
    # queen is allowed to use is searchable and loaded on demand via
    # search_tools. Populated BEFORE rebuild so the memoized eager list is
    # correct from the first turn. An empty set (expansion failure) disables
    # the split — fail-open, queen keeps the full surface.
    from framework.agents.queen.queen_tools_defaults import always_enabled_tool_names

    phase_state.always_enabled_names = always_enabled_tool_names(_boot_catalog)
    # Heal-on-read: re-adopt tools searched in a prior run of this session,
    # dropping any no longer registered or no longer allowed. Needs the
    # allowlist + always_enabled_names + mcp_tool_names_all all set (above).
    phase_state.restore_loaded_tools(persisted_loaded_tools, registered_names)
    if persisted_loaded_tools:
        logger.info(
            "Queen: restored %d/%d searched tool(s) from meta.json: %s",
            len(phase_state.loaded_tool_names),
            len(persisted_loaded_tools),
            sorted(phase_state.loaded_tool_names),
        )
    # image_generate is a first-class capability for the queens granted it
    # (visual roles via the `media` category, or an explicit opt-in), so load
    # it EAGERLY rather than leaving it in the searchable tier — otherwise it
    # shows in the Tool Library but never appears in the queen's live tools
    # until the agent happens to search for it. Seeding loaded_tool_names (not
    # always_enabled_names) keeps it gated by the allowlist in
    # rebuild_independent_filter: queens not granted it are unaffected, and an
    # explicit un-tick still removes it.
    if (
        "image_generate" in registered_names
        and "image_generate" not in phase_state.loaded_tool_names
        and (phase_state.enabled_mcp_tools is None or "image_generate" in phase_state.enabled_mcp_tools)
    ):
        phase_state.loaded_tool_names.append("image_generate")
    phase_state.rebuild_independent_filter()
    if phase_state.enabled_mcp_tools is not None:
        total_mcp = len(phase_state.mcp_tool_names_all)
        allowed_mcp = len(set(phase_state.enabled_mcp_tools) & phase_state.mcp_tool_names_all)
        logger.info(
            "Queen: per-queen MCP allowlist active — %d of %d MCP tools enabled",
            allowed_mcp,
            total_mcp,
        )

    # ---- MCP tool catalog for the frontend ---------------------------
    # Snapshot per-server tool metadata so the Queen Tools API can render
    # the tool surface without spawning MCP subprocesses. Keyed by server
    # name so the UI can group tools by origin. Updated every time a
    # queen boots, so installing a new server and starting a new queen
    # session refreshes the catalog.
    #
    # We source from the registry's full pre-credential-gate catalog so
    # the Library shows credentialed tools whose provider isn't yet
    # authorized — they appear greyed-out with a Connect button rather
    # than vanishing entirely. The strict admission gate still controls
    # what the queen sees in her prompt.
    full_catalog = queen_registry.get_full_mcp_catalog()
    mcp_tool_catalog: dict[str, list[dict[str, Any]]] = {}
    for server_name, entries in full_catalog.items():
        mcp_tool_catalog[server_name] = sorted(
            (dict(e) for e in entries),
            key=lambda e: e.get("name", ""),
        )
    # All queens share one MCP registry, so the catalog is a manager-level
    # fact; stash it on the SessionManager so the Queen Tools route can
    # render the tool list even when no queen session is currently live.
    if session_manager is not None:
        try:
            session_manager._mcp_tool_catalog = mcp_tool_catalog  # type: ignore[attr-defined]
        except Exception:
            logger.debug("Queen: could not attach mcp_tool_catalog to manager", exc_info=True)

    # ---- Global + queen-scoped memory ----------------------------------
    global_dir, queen_mem_dir = initialize_memory_scopes(session, phase_state)

    # Materialize the selected queen identity before building the initial
    # system prompt so the first turn includes the profile's core identity.
    await materialize_queen_identity(
        session=session,
        phase_state=phase_state,
        queen_profile=queen_profile,
        event_bus=session.event_bus,
    )

    # ---- Compose phase-specific prompts ------------------------------
    from framework.agents.queen.nodes import queen_node as _orig_node

    # Resolve vision-only prompt sections based on the session's LLM.
    # session.llm is immutable for the session's lifetime, so this check
    # is stable — prompts never need to be recomposed mid-session.
    _has_vision = bool(session.llm and supports_image_tool_results(getattr(session.llm, "model", "")))

    phase_state.prompt_independent = finalize_queen_prompt(
        (_queen_character_core + _queen_role_independent + _queen_tools_independent + _queen_behavior_always + _queen_behavior_independent),
        _has_vision,
    )
    # Concurrency is no longer a fixed colony cap rendered into the prompt —
    # the queen declares it per-playbook via ``meta["concurrency"]`` (run_playbook
    # honors it, rejecting only when too high). So the prompt no longer needs the
    # cap substituted in.

    # Colony composition deliberately puts ``_queen_behavior_colony``
    # (delegation loop + colony operating rules) BEFORE the shared
    # ``_queen_behavior_always`` so the colony-specific "first
    # substantive step = tracker_sql CREATE TABLE" anchor reads ahead of
    # the generic "task_create FIRST" default. The independent prompt
    # keeps the original order (always → independent) because there is
    # no contradiction to resolve there.
    phase_state.prompt_colony = finalize_queen_prompt(
        (_queen_character_core + _queen_role_colony + _queen_tools_colony + _queen_behavior_colony + _queen_behavior_always),
        _has_vision,
    )

    # ---- Default skill protocols -------------------------------------
    _queen_skill_dirs: list[str] = []
    try:
        from framework.config import QUEENS_DIR
        from framework.skills.discovery import ExtraScope
        from framework.skills.manager import SkillsManager, SkillsManagerConfig

        # Queen home backs the queen-UI skill scope and the queen's
        # override store. The directory already exists (or is created on
        # demand by queen_profiles.py); treat a missing queen_name as the
        # default queen to preserve backwards compatibility.
        _queen_id = getattr(session, "queen_name", None) or "default"
        _queen_home = QUEENS_DIR / _queen_id
        _queen_skills_mgr = SkillsManager(
            SkillsManagerConfig(
                queen_id=_queen_id,
                queen_overrides_path=_queen_home / "skills_overrides.json",
                extra_scope_dirs=[
                    ExtraScope(
                        directory=_queen_home / "skills",
                        label="queen_ui",
                        priority=2,
                    )
                ],
                # No project_root — queen's project is her own identity;
                # user-scope discovery still runs without one.
                project_root=None,
                skip_community_discovery=True,
                interactive=False,
            )
        )
        _queen_skills_mgr.load()
        phase_state.protocols_prompt = _queen_skills_mgr.protocols_prompt
        phase_state.skills_catalog_prompt = _queen_skills_mgr.skills_catalog_prompt
        # Also store the manager so get_current_prompt() can render a
        # phase-filtered catalog on each turn (skills with a `visibility`
        # frontmatter that excludes the current phase are dropped).
        phase_state.skills_manager = _queen_skills_mgr
        _queen_skill_dirs = _queen_skills_mgr.allowlisted_dirs
    except Exception:
        logger.debug("Queen skill loading failed (non-fatal)", exc_info=True)

    # ---- Queen identity + recall -------------------------------------
    _session_llm = session.llm
    _session_event_bus = session.event_bus

    # Wire the queen's session event bus into the task lifecycle emitters.
    # Mirrors what colony_runtime does for colonies — without this, the
    # task store's create/update/delete events have nowhere to publish in
    # queen DM mode (no colony spins up), so the action plan rail in the
    # frontend never sees a `task_created` SSE and never auto-opens.
    # Idempotent — last writer wins.
    try:
        from framework.tasks.events import set_default_event_bus

        set_default_event_bus(session.event_bus)
    except Exception:
        logger.debug("Failed to register default task event bus for queen", exc_info=True)

    async def _refresh_recall_cache(query: str) -> None:
        """Populate the cached recall block for the next queen prompt."""
        if not query or not isinstance(query, str):
            return
        try:
            from framework.agents.queen.recall_selector import (
                build_scoped_recall_blocks,
            )

            global_block, queen_block = await build_scoped_recall_blocks(
                query,
                _session_llm,
                global_memory_dir=phase_state.global_memory_dir,
                queen_memory_dir=phase_state.queen_memory_dir,
                queen_id=phase_state.queen_id or session.queen_name,
            )
            phase_state._cached_global_recall_block = global_block
            phase_state._cached_queen_recall_block = queen_block
        except Exception:
            logger.debug("recall: cache update failed", exc_info=True)

    # ---- Recall on each real user turn --------------------------------
    # Recall blocks are delivered as a <system-reminder> injected into the
    # conversation, NOT via the system prompt: the system prompt precedes
    # the entire message history in the request, so a per-turn recall block
    # there would invalidate the cached history prefix on every refresh.
    # An injected reminder appends near the tail instead, and stays in
    # history — so it is only re-injected when its content changes.
    _last_injected_recall = ""

    # NOTE: this helper MUST NOT be named `_queen_loop` — the main
    # `async def _queen_loop()` defined later in create_queen rebinds that
    # name in this shared scope, so closures calling it at runtime would
    # invoke the ASYNC loop instead, get a never-awaited coroutine (truthy!),
    # and crash on `.inject_event` — silently killing recall injection.
    # (Observed live 2026-07-23: "coroutine ... was never awaited".)
    def _get_queen_node() -> Any:
        executor = getattr(session, "queen_executor", None)
        registry = getattr(executor, "node_registry", None) or {}
        return registry.get("queen")

    async def _inject_recall_if_changed() -> None:
        nonlocal _last_injected_recall
        loop = _get_queen_node()
        if loop is None:
            return
        block = phase_state.render_recall_block()
        if not block or block == _last_injected_recall:
            return
        _last_injected_recall = block
        await loop.inject_event(
            "<system-reminder>\nRecalled memories relevant to the latest "
            "user message (supersedes earlier recall reminders):\n\n"
            f"{block}\n</system-reminder>"
        )

    async def _recall_on_user_input(event: AgentEvent) -> None:
        """On real user input, deliver cached recall and refresh in background.

        The EventBus drops handlers that exceed 15s, so we MUST return fast.
        Recall selection queries the LLM and can take >15s on slow backends;
        we fire it off as a background task. The immediate injection delivers
        whatever recall we already cached (seeding or the prior turn's
        refresh) so this turn starts with relevant memories; the background
        refresh injects the fresh blocks mid-turn if they differ — but only
        while the queen is still executing, so a slow refresh landing after
        the turn ended doesn't wake her into a spurious reply. Phase-change
        injections and worker-report injections go through
        agent_loop.inject_event() and do NOT publish CLIENT_INPUT_RECEIVED,
        so this runs exactly once per real user turn.
        """
        query = (event.data or {}).get("content", "")
        await _inject_recall_if_changed()

        async def _bg_refresh() -> None:
            try:
                await _refresh_recall_cache(query)
                from framework.agent_loop.reminders import LoopActivity

                loop = _get_queen_node()
                if loop is not None and getattr(loop, "activity", None) == LoopActivity.EXECUTING:
                    await _inject_recall_if_changed()
            except Exception:
                logger.debug("background recall refresh failed", exc_info=True)

        import asyncio as _asyncio

        _asyncio.create_task(_bg_refresh())

    session.event_bus.subscribe(
        [EventType.CLIENT_INPUT_RECEIVED],
        _recall_on_user_input,
        filter_stream="queen",
    )

    async def _queen_identity_hook(ctx: HookContext) -> HookResult | None:
        from framework.agent_loop.internals.types import HookResult
        from framework.agents.queen.queen_profiles import (
            ensure_default_queens,
            format_queen_identity_prompt,
            load_queen_profile,
            select_queen,
        )

        ensure_default_queens()
        trigger = ctx.trigger or ""
        # If the session was pre-bound to a queen (user clicked a specific
        # queen in the UI), use that identity instead of LLM auto-selection.
        # Also skip LLM auto-selection if queen was already selected during
        # session creation (e.g., from home screen classification).
        if session.queen_name and session.queen_name != "default":
            queen_id = session.queen_name
            logger.info("Using pre-selected queen: %s", queen_id)
        else:
            # This should rarely happen now - queen is selected at session creation
            logger.warning("No pre-selected queen, falling back to LLM classification")
            queen_id = await select_queen(trigger, _session_llm)
        try:
            profile = load_queen_profile(queen_id)
        except FileNotFoundError:
            logger.warning("Queen profile %s not found after selection", queen_id)
            return None
        # max_examples=0: omit <roleplay_examples> from the live prompt (see
        # the sibling call site above for rationale).
        identity_prompt = format_queen_identity_prompt(profile, max_examples=0)
        # Store on phase_state so identity persists across dynamic prompt refreshes
        phase_state.queen_id = queen_id
        phase_state.queen_profile = profile
        phase_state.queen_identity_prompt = identity_prompt
        # Route session storage to ~/.hive/agents/queens/{queen_id}/sessions/
        session.queen_name = queen_id

        # Relocate session dir from default/ to the selected queen's dir
        # so all writes (conversations, events) go to the correct queen.
        if queen_id != "default" and session.queen_dir:
            import json as _json
            import shutil as _shutil

            _old_dir = session.queen_dir
            # Pattern: queens/default/sessions/<sid> -- parent.parent.name == "default"
            # (pre-rebind _start_queen sessions live under the default queen).
            if _old_dir.exists() and _old_dir.parent.parent.name == "default":
                from framework.config import queen_session_dir as _qcd

                _new_dir = _qcd(queen_id, _old_dir.name)
                _new_dir.parent.mkdir(parents=True, exist_ok=True)
                _shutil.move(str(_old_dir), str(_new_dir))
                session.queen_dir = _new_dir
                logger.info(
                    "Relocated queen session dir: %s -> %s",
                    _old_dir,
                    _new_dir,
                )
                # Update meta.json queen_id
                _meta_path = _new_dir / "meta.json"
                if _meta_path.exists():
                    try:
                        _meta = _json.loads(_meta_path.read_text(encoding="utf-8"))
                        _meta["queen_id"] = queen_id
                        _meta_path.write_text(_json.dumps(_meta, ensure_ascii=False), encoding="utf-8")
                    except (OSError, _json.JSONDecodeError):
                        pass
                # Re-point event bus log to new location, preserving offset
                _offset = getattr(session.event_bus, "_session_log_iteration_offset", 0)
                session.event_bus.set_session_log(_new_dir / "events.jsonl", iteration_offset=_offset)

        if _session_event_bus is not None:
            await _session_event_bus.publish(
                AgentEvent(
                    type=EventType.QUEEN_IDENTITY_SELECTED,
                    stream_id="queen",
                    data={
                        "queen_id": queen_id,
                        "name": profile.get("name", ""),
                        "title": profile.get("title", ""),
                    },
                )
            )

        # Seed recall cache so the first turn has relevant memories.
        # Use a short timeout to avoid blocking the first turn on slow models.
        if trigger:
            try:
                import asyncio

                from framework.agents.queen.recall_selector import (
                    format_recall_injection,
                    select_memories,
                )

                mem_dir = phase_state.global_memory_dir
                selected = await asyncio.wait_for(
                    select_memories(trigger, _session_llm, mem_dir),
                    timeout=3.0,
                )
                phase_state._cached_global_recall_block = format_recall_injection(selected, mem_dir)
            except TimeoutError:
                logger.debug("recall: initial seeding timed out, will retry on first turn")
            except Exception:
                logger.debug("recall: initial seeding failed", exc_info=True)

        # Seeded recall is delivered by _recall_on_user_input's immediate
        # injection on the first CLIENT_INPUT_RECEIVED; the system prompt
        # itself stays static. The CRM host queen gets the forced "load the CRM
        # summary first" directive appended — in her DM, never once bound to a
        # colony — plus the setup playbook while that handoff is still owed.
        return HookResult(system_prompt=phase_state.get_current_prompt())

    # ---- Colony preparation -------------------------------------------
    initial_prompt_text = phase_state.get_current_prompt()

    registered_tool_names = set(queen_registry.get_tools().keys())
    declared_tools = _orig_node.tools or []
    available_tools = [t for t in declared_tools if t in registered_tool_names]

    node_updates: dict = {
        "system_prompt": initial_prompt_text,
    }
    if set(available_tools) != set(declared_tools):
        missing = sorted(set(declared_tools) - registered_tool_names)
        if missing:
            logger.debug("Queen: tools not yet available (registered on worker load): %s", missing)
        node_updates["tools"] = available_tools

    _orig_node.model_copy(update=node_updates)

    # Determine session mode:
    # - RESTORE: Resume cold session with history, no initial prompt -> wait for user
    # - FRESH:   New session OR explicit initial prompt -> greet immediately
    _is_restore_mode = bool(session.queen_resume_from) and initial_prompt is None

    _queen_loop_config = {**(_colony_loop_config if effective_phase == "colony" else _base_loop_config)}

    # ---- Queen event loop (AgentLoop directly, no Orchestrator) -------
    from types import SimpleNamespace

    from framework.agent_loop.agent_loop import AgentLoop, LoopConfig
    from framework.agent_loop.types import AgentContext, AgentSpec
    from framework.storage.conversation_store import FileConversationStore

    async def _queen_loop():
        logger.debug("[_queen_loop] Starting queen loop for session %s", session.id)
        # Scope the browser profile to this session so parallel queens each
        # drive their own Chrome tab group instead of fighting over "default".
        # Browser tools run in a stdio MCP subprocess, so we can't set a
        # contextvar across processes — instead we inject `profile` as a
        # CONTEXT_PARAM that ToolRegistry passes into every MCP call. The
        # token stays local to this task.
        # Pre-bound so the colony_id resolution at the AgentContext below is
        # safe even if the binding-resolve block raises before assigning it.
        binding = None
        try:
            from framework.host.colony_binding import ColonyBinding
            from framework.loader.tool_registry import ToolRegistry

            queen_agent_id = getattr(session, "agent_id", None) or "queen"
            queen_session_id = session.id
            # Restore the colony binding when this queen has already
            # forked a colony in a prior process so tracker_sql /
            # tracker_query resolve against the real colony's tracker.db.
            # Order: explicit ``session.binding`` (set by ``fork_session_into_colony``)
            # > ``session.colony_id`` (set when loading a colony session).
            binding: ColonyBinding | None = getattr(session, "binding", None)
            if binding is None:
                colony_id = getattr(session, "colony_id", None)
                if colony_id:
                    binding = ColonyBinding.for_name(colony_id)
                    session.binding = binding
            # usage_agent_id is the cloud-side identity stamped on Hive
            # LLM proxy calls (X-Hive-Agent) for per-agent usage attribution.
            # Distinct from agent_id, which is locked to the literal
            # "queen" slug for local task-list path scoping. Falls back to
            # the local agent_id when queen_name is unset (e.g. legacy
            # sessions resumed before queen identity selection).
            usage_agent_id = getattr(session, "queen_name", None) or queen_agent_id
            # Human-readable label for browser tab groups / the bridge side
            # panel — "Alexandra · Head of Technology", with the colony name
            # prepended when this queen is bound to one ("colony · Alexandra ·
            # Head of Technology"), matching the worker's colony-first order.
            # profile stays the session id; this is purely cosmetic and best-effort.
            profile_display_name: str | None = None
            queen_name = getattr(session, "queen_name", None)
            if queen_name:
                try:
                    from framework.agents.queen.queen_profiles import load_queen_profile

                    qp = load_queen_profile(queen_name) or {}
                    label = qp.get("name") or queen_name
                    title = qp.get("title")
                    profile_display_name = f"{label} · {title}" if title else label
                except Exception:
                    profile_display_name = queen_name
            colony_id = getattr(session, "colony_id", None) or (binding.name if binding is not None else None)
            if profile_display_name and colony_id:
                from framework.utils.text import humanize_slug

                profile_display_name = f"{humanize_slug(colony_id)} · {profile_display_name}"
            exec_ctx_fields: dict[str, Any] = {
                "profile": session.id,
                "agent_id": queen_agent_id,
                "session_id": queen_session_id,
                "usage_agent_id": usage_agent_id,
                # Loose-optimistic default cwd for terminal tools (the queen's
                # session dir, which holds data/, conversations/, logs/).
                "session_cwd": str(queen_dir),
            }
            if profile_display_name:
                exec_ctx_fields["profile_display_name"] = profile_display_name
            if binding is not None:
                exec_ctx_fields["binding"] = binding
                # Flat colony_id so it can cross into MCP tools as a CONTEXT_PARAM
                # (the ColonyBinding object itself isn't JSON-serializable).
                exec_ctx_fields["colony_id"] = binding.name
            # Acting identity for the CRM: `dm:queen` in a DM session,
            # `colony:<name>:queen` once bound. The backend's capability model
            # keys off this — an unnamed caller resolves to the human and
            # inherits the user's own permissions. The CRM package is optional —
            # its absence or failure must NOT abort execution-context stamping,
            # which session tools depend on (without session_id on the
            # contextvar, task_create and friends can't resolve their store).
            try:
                from framework.crm.principal import for_agent as _principal_for

                principal = _principal_for(queen_agent_id, binding.name if binding is not None else None)
                if principal:
                    exec_ctx_fields["principal"] = principal
            except Exception:
                logger.debug("Queen: CRM principal lookup unavailable", exc_info=True)
            ToolRegistry.set_execution_context(**exec_ctx_fields)
        except Exception:
            logger.warning("Queen: failed to set execution context for session %s", session.id, exc_info=True)
        try:
            lc = _queen_loop_config
            # Bridge/roleplay: a queen is an unbounded autonomous task loop
            # (default max_iterations=999999, runs until the judge accepts /
            # output_keys are produced). A chat/paint persona never "completes a
            # task", so it loops — re-triggering painting and spamming QQ. Cap it
            # via env HIVE_MAX_ITER (e.g. 3) for single-reply chat deployments.
            import os as _os

            _iter_cap = _os.environ.get("HIVE_MAX_ITER")
            _default_max_iter = int(_iter_cap) if (_iter_cap and _iter_cap.isdigit()) else 999_999
            from framework.config import (
                get_max_context_tokens as _get_max_ctx,
                get_max_tool_result_chars as _get_max_trc,
            )

            queen_loop_config = LoopConfig(
                max_iterations=lc.get("max_iterations", _default_max_iter),
                tool_call_budget=lc.get("tool_call_budget", 30),
                tool_call_hard_multiple=lc.get("tool_call_hard_multiple", 5),
                # Config/catalog first (llm.max_context_tokens, model window),
                # then the queen profile's legacy literal — a 32k local model
                # must not run with a 180k compaction budget.
                max_context_tokens=_get_max_ctx(fallback=lc.get("max_context_tokens", 180_000)),
                max_tool_result_chars=_get_max_trc(fallback=lc.get("max_tool_result_chars", 30_000)),
                spillover_dir=str(queen_dir / "data"),
                hooks=lc.get("hooks", {}),
            )

            conversation_store = FileConversationStore(queen_dir / "conversations")

            agent_loop = AgentLoop(
                event_bus=session.event_bus,
                config=queen_loop_config,
                tool_executor=queen_tool_executor,
                conversation_store=conversation_store,
            )

            from framework.tracker.decision_tracker import DecisionTracker

            queen_spec = AgentSpec(
                id="queen",
                name="Queen",
                description="Queen agent — manages the colony and interacts with the user.",
                system_prompt="",
                tools=[t.name for t in queen_tools],
                tool_access_policy="all",
                # Queen is a forever-alive conversational agent: bypass
                # the implicit judge entirely. Without this, a text-only
                # turn (greeting, clarifying question, summary) falls
                # through to the default ACCEPT verdict in
                # judge_pipeline.py, which terminates the loop and
                # leaves session.queen_executor=None until the user
                # reloads. Mirrors the static queen_node NodeSpec in
                # framework.agents.queen.nodes which already sets this.
                skip_judge=True,
            )

            ctx = AgentContext(
                runtime=DecisionTracker(queen_dir),
                agent_id="queen",
                agent_spec=queen_spec,
                llm=session.llm,
                available_tools=queen_tools,
                goal_context=queen_goal.to_prompt_context(),
                # Honor configuration.json (llm.max_tokens) instead of
                # hard-defaulting to 8192. The legacy fallback ignored both
                # the user's saved ceiling AND the model's actual output
                # capacity (e.g. glm-5.1 / Kimi K2.x both support 32k out),
                # which silently truncated long tool-emitting turns.
                max_tokens=lc.get("max_tokens", _get_max_tokens()),
                stream_id="queen",
                execution_id=session.id,
                # The on-disk colony name (None for a DM/independent session).
                # AgentContext documents colony_id as "set on the queen of a
                # colony"; without it every colony-aware source keyed on
                # colony_id (Sentinel's escalation source, idle-nudge's
                # sentinel-autopilot defer) is blind and silently self-skips.
                colony_id=binding.name if binding is not None else None,
                # The queen's own session-scoped task list. Without this,
                # AgentContext.session_id is None and every task-aware
                # reminder source (TaskReminderSource, idle-nudge) is blind
                # to the queen's tasks.
                session_id=queen_session_id,
                dynamic_tools_provider=phase_state.get_current_tools,
                # No dynamic_prompt_suffix_provider: the queen's system
                # prompt is fully static now. Recall blocks — the last
                # per-turn tenant of the suffix — are injected into the
                # conversation instead (see _recall_on_user_input), so the
                # cached request prefix survives across turns.
                dynamic_prompt_provider=phase_state.get_static_prompt,
                # Searchable (load-on-demand) tools + skills catalog ride the
                # conversation as <system-reminder>s
                searchable_tools_provider=phase_state.get_searchable_tools,
                queen_skills_catalog_provider=phase_state.render_skills_catalog,
                loaded_tool_names_provider=lambda: list(phase_state.loaded_tool_names),
                iteration_metadata_provider=lambda: {"phase": phase_state.phase},
                # Snapshot of currently active colony workers. Read by the
                # active-workers reminder source on USER_PROMPT_SUBMIT so
                # the queen is reminded that workers are still in flight
                # whenever the user re-engages mid-batch. Returns []
                # when no colony runtime has been bound yet (independent
                # phase or pre-fork).
                active_workers_provider=lambda: session.colony.get_active_streams() if getattr(session, "colony", None) is not None else [],
                # Resolves the on-disk colony binding for tool-budget
                # checkpoint reminders (tracker + fleet snapshots).
                # Returns None for an independent-mode queen (no colony
                # forked yet) — the snapshot sources self-skip on None.
                colony_binding_provider=lambda: session.colony.binding if getattr(session, "colony", None) is not None else None,
                # Was this conversation opened to set up / configure the CRM?
                # Safe to snapshot: a resume restores the flag from meta.json
                # near the top of this same function, well before here.
                crm_setup=bool(getattr(session, "crm_setup", False)),
                # Active / total worker counts for the fleet snapshot
                # source. ``total`` is cumulative within the current
                # ``ColonyRuntime`` lifetime (active + finished + queued),
                # not a historical all-time count.
                colony_stats_provider=lambda: (
                    {
                        "active": session.colony.active_worker_count,
                        "total": session.colony.total_worker_count,
                    }
                    if getattr(session, "colony", None) is not None
                    else {"active": 0, "total": 0}
                ),
                # The queen's skills catalog is delivered as a <system-reminder>
                # (SkillsCatalogReminderSource via queen_skills_catalog_provider),
                # NOT baked into the static prompt — so leave this empty to avoid
                # double-injecting it through build_system_prompt_parts_for_context.
                # phase_state.skills_catalog_prompt / skills_manager still back the
                # reminder's render_skills_catalog().
                skills_catalog_prompt="",
                # Set by the task_create(new_colony=true) synthetic
                # intercept. Stashes the rich {goal, handoff, tasks}
                # payload on the live Session so the popup-accept route
                # (_create_sibling_colony_from_colony) can pick it up
                # when the user confirms. Bypasses the registered
                # task_create executor entirely — that path would have
                # been wrapped in tool_call_timeout_seconds (60s) and
                # cancelled long before the user clicked.
                #
                # Returns a non-empty string to veto (kickoff-pending
                # guard, concurrent-popup guard); the intercept surfaces
                # the string as an is_error tool result.
                pivot_payload_sink=_make_pivot_payload_sink(session),
                protocols_prompt=phase_state.protocols_prompt,
                skill_dirs=_queen_skill_dirs,
            )

            session.queen_executor = SimpleNamespace(
                node_registry={"queen": agent_loop},
            )

            async def _inject_phase_notification(content: str) -> None:
                await agent_loop.inject_event(content)

            phase_state.inject_notification = _inject_phase_notification

            async def _on_worker_report(event):
                """Inject a structured [WORKER_REPORT] block into the queen.

                Subscribes to SUBAGENT_REPORT events which carry the worker's
                real summary/data (preferring any explicit ``report_to_parent``
                call). Every spawned worker emits exactly one — success,
                partial, failed, timeout, or stopped. The queen sees the
                report as the next user turn and can react (reply to user,
                kick off follow-up work, etc.) without being blocked by the
                spawn call itself.

                Output format is structured XML-style block so the queen
                can identify which batch/slice each report came from and
                whether more reports are still pending in the same batch
                (batch_remaining > 0 ⇒ wait before validating the tracker;
                batch_remaining == 0 ⇒ the whole batch has reported).
                """
                if event.stream_id == "queen":
                    return
                data = event.data or {}
                worker_id = data.get("worker_id", event.node_id or "unknown")

                # ``stop_worker`` collects reports synchronously via
                # ``wait_for_worker_reports`` and returns them in its tool
                # result. Re-injecting them here would double-up the same
                # payload on the queen's next turn, so skip ids the tool
                # has claimed.
                colony_for_suppress = getattr(session, "colony", None)
                suppress = getattr(colony_for_suppress, "_suppress_report_inject_for", None)
                if suppress and worker_id in suppress:
                    return

                status = data.get("status", "unknown")
                summary = data.get("summary") or "(no summary)"
                err = data.get("error")
                payload_data = data.get("data") or {}
                duration = data.get("duration_seconds")
                original_task = data.get("task") or ""
                batch_id = data.get("batch_id") or ""
                batch_index = data.get("batch_index") or 0
                batch_size = data.get("batch_size") or 0
                output_file = data.get("output_file") or ""

                # Compute remaining-in-batch from the live colony worker
                # registry. ``is_active`` covers QUEUED, PENDING, and
                # RUNNING — so this counts both workers actively running
                # AND workers waiting in the colony's pending queue
                # (when the spawn exceeded max_concurrent_workers). The
                # reporting worker has just terminated, so it should
                # NOT count itself — but its status flip is racy with
                # this handler firing. Guard by also excluding the
                # current ``worker_id`` from the count.
                batch_remaining = 0
                if batch_id and batch_size > 0:
                    try:
                        colony_runtime = getattr(session, "colony", None)
                        workers_map = getattr(colony_runtime, "_workers", {}) or {}
                        for wid, w in workers_map.items():
                            if wid == worker_id:
                                continue
                            if getattr(w, "_batch_id", "") != batch_id:
                                continue
                            if getattr(w, "is_active", False):
                                batch_remaining += 1
                    except Exception:
                        # Best-effort — if anything explodes, fall back
                        # to leaving remaining as 0 (queen treats the
                        # current report as "the last one" and validates).
                        # Same end-state as the legacy unstructured format.
                        batch_remaining = 0

                # Build the structured block. Using XML-ish tags so a
                # reasoning model can parse fields cleanly without
                # confusing them with surrounding prose.
                lines: list[str] = ["[WORKER_REPORT]"]
                lines.append(f"<worker_id>{worker_id}</worker_id>")
                if batch_id:
                    lines.append(f"<batch_id>{batch_id}</batch_id>")
                    if batch_size > 0:
                        lines.append(f"<task_index>{batch_index}</task_index>")
                    lines.append(f"<task_count>{batch_size}</task_count>")
                    lines.append(f"<batch_remaining>{batch_remaining}</batch_remaining>")
                if original_task:
                    # Cap to keep the report compact; the full task is
                    # in the worker's own conversation if needed.
                    preview = original_task.strip().replace("\n", " ")
                    if len(preview) > 200:
                        preview = preview[:200] + "…"
                    lines.append(f"<original_task>{preview}</original_task>")
                if output_file:
                    lines.append(f"<output_file>{output_file}</output_file>")
                lines.append(f"<status>{status}</status>")
                if duration is not None:
                    try:
                        lines.append(f"<duration_seconds>{float(duration):.1f}</duration_seconds>")
                    except (TypeError, ValueError):
                        pass
                # Consumption vs the effective lifetime budget (which the
                # colony's adaptive norm may have shrunk mid-run). Lets the
                # queen judge whether a cut-off worker deserves a
                # resume_worker with a raised tool_call_lifetime_budget.
                _tc_used = data.get("tool_calls_used")
                _tc_budget = data.get("tool_call_lifetime_budget")
                if isinstance(_tc_used, int) and _tc_used > 0:
                    if isinstance(_tc_budget, int) and _tc_budget > 0:
                        lines.append(f"<tool_calls>{_tc_used}/{_tc_budget}</tool_calls>")
                    else:
                        lines.append(f"<tool_calls>{_tc_used}</tool_calls>")
                if data.get("budget_limited"):
                    lines.append(
                        "<budget_limited>true — the framework wound this worker down at its "
                        "tool-call budget (possibly shrunk by the colony's adaptive norm) "
                        "before it finished on its own; resume_worker with a raised "
                        "tool_call_lifetime_budget if the task warrants more effort</budget_limited>"
                    )
                lines.append(f"<summary>{summary}</summary>")
                if err:
                    lines.append(f"<error>{err}</error>")
                if payload_data:
                    try:
                        import json as _json

                        lines.append("<data>" + _json.dumps(payload_data, ensure_ascii=False, default=str) + "</data>")
                    except Exception:
                        lines.append(f"<data>{payload_data!r}</data>")
                notification = "\n".join(lines)

                await agent_loop.inject_event(notification)
                session.worker_configured = True

                # No follow-up phase transition needed: the unified colony
                # phase covers both live and finished states. The queen's
                # full colony-phase toolkit (run_worker,
                # inject_message, stop_worker, set_trigger, etc.) stays
                # available whether or not workers are still active.

            session.event_bus.subscribe(
                event_types=[EventType.SUBAGENT_REPORT],
                handler=_on_worker_report,
            )

            # ---- Colony-scoped worker escalation routing ----
            # Replaces the legacy unfiltered SessionManager subscription.
            # ``filter_colony`` (inside install_worker_escalation_routing)
            # ensures only escalations from workers in THIS queen's colony
            # reach THIS queen — cross-colony leakage is structurally
            # impossible because StreamEventBus stamps colony_id on every
            # published event before dispatch.
            session.worker_handoff_sub = install_worker_escalation_routing(session)

            from framework.agents.queen.reflection_agent import subscribe_reflection_triggers

            _reflection_subs = await subscribe_reflection_triggers(
                session.event_bus,
                queen_dir,
                session.llm,
                global_memory_dir=global_dir,
                queen_memory_dir=queen_mem_dir,
                queen_id=session.queen_name,
            )
            session.memory_reflection_subs = _reflection_subs

            # Set initial user message based on mode:
            # - RESTORE:              None -> AgentLoop restores from disk, waits for /chat
            # - FRESH + initial_prompt:     -> queen responds to the real prompt immediately
            # - FRESH + no initial_prompt:  -> None -> AgentLoop waits for the first /chat
            #
            # The third case matters for the classify→createNewSession→chat
            # bootstrap: if the frontend doesn't pass initial_prompt, we must
            # NOT invent a phantom "Hello" — that used to concatenate with the
            # real first chat message and confuse the model.
            ctx.input_data = {"user_request": None if _is_restore_mode else (initial_prompt or None)}

            # Publish the initial prompt as a CLIENT_INPUT_RECEIVED event so
            # it appears in the SSE stream and persists to events.jsonl for
            # session resume.  The /chat endpoint does the same for injected
            # messages; this covers the session-creation-with-prompt path.
            if initial_prompt and not _is_restore_mode:
                await session.event_bus.publish(
                    AgentEvent(
                        type=EventType.CLIENT_INPUT_RECEIVED,
                        stream_id="queen",
                        node_id="queen",
                        execution_id=session.id,
                        data={"content": initial_prompt},
                    )
                )

            logger.info(
                "Queen %s in %s phase with %d tools: %s",
                "restoring" if _is_restore_mode else "starting",
                phase_state.phase,
                len(phase_state.get_current_tools()),
                [t.name for t in phase_state.get_current_tools()],
            )

            # Run the queen -- forever-alive conversation loop.
            #
            # Wrap in queen_strict_account_mode so multi-account ambiguity
            # surfaces as an ``account_selection_required`` tool result the
            # LLM can recover from (ask the user, re-call with account=).
            # Queens have no worker.json profile to pin a default account,
            # so the alternative — silently picking the first-indexed
            # credential — leaves the user unable to predict which inbox
            # / workspace the queen is acting against.
            from aden_tools.credentials.store_adapter import (
                queen_strict_account_mode,
            )

            with queen_strict_account_mode():
                result = await agent_loop.execute(ctx)

            # AgentResult doesn't have stop_reason — check success/error.
            # The queen is expected to be forever-alive; a clean return
            # means the loop hit max_iterations or decided to exit.
            if result.success:
                logger.warning("Queen returned (should be forever-alive)")
            elif result.error:
                logger.error("Queen failed: %s", result.error)

        except asyncio.CancelledError:
            logger.info("[_queen_loop] Queen loop cancelled (normal shutdown)")
            raise
        except Exception as e:
            logger.exception("[_queen_loop] Queen conversation crashed: %s", e)
            raise
        finally:
            logger.warning(
                "[_queen_loop] Queen loop exiting — clearing queen_executor for session '%s'",
                session.id,
            )
            session.queen_executor = None

    return asyncio.create_task(_queen_loop())
