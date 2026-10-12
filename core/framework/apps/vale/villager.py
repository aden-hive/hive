"""Each villager is a Hive agent: one short AgentLoop per stirring, acting through game tools.

The physics decide *who* stirs; the villager's own agent decides *what* to do. Its identity
is the villager's persona and the world's rules, its first message is the moment (where
they are, who is there, what stirred them, their own notes), and its hands are tools: say,
look, give, attempt, propose, travel, pray... Each tool answers at once, so a villager learns
in the same turn that a person was not there to hear them. The turn ends with Hive's
``report_to_parent``: the villager's rewritten private notes, mood and thought.

Tools run on the event loop's thread (the executor is async), so the villagers of one wave
can act concurrently without racing on the world.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from framework.agent_loop.agent_loop import AgentLoop, LoopConfig
from framework.agent_loop.types import AgentContext, AgentSpec
from framework.llm.provider import LLMProvider, Tool, ToolResult, ToolUse

from . import act, mind, physics
from .world import Agent, World

logger = logging.getLogger(__name__)

MAX_ACTIONS = 3
TURN_TIMEOUT = 240.0  # a backstop: each model request has its own timeout and retries

# One turn is short: up to three actions and a report, with a little grace if the model dawdles.
CONFIG = {"max_iterations": 3, "grace_iterations": 1, "tool_call_budget": MAX_ACTIONS + 3, "tool_call_hard_multiple": 1, "background_tools": set()}


def _s(description: str) -> dict:
    return {"type": "string", "description": description}


def report_schema(world: World) -> dict:
    t = world.t
    return {
        "type": "object",
        "properties": {
            "memory": _s(t("villager.report_memory")),
            "mood": _s(t("villager.report_mood")),
            "thought": _s(t("villager.report_thought")),
        },
        "required": ["memory", "mood", "thought"],
    }


def tools_for(world: World, a: Agent) -> list[Tool]:
    """The villager's hands. A painter can paint; everyone can pray to whichever gods they know of."""
    t = world.t

    def tool(name: str, params: dict, required: list[str], **slots: str) -> Tool:
        props = {k: (v if isinstance(v, dict) else _s(t(f"villager.{v}"))) for k, v in params.items()}
        return Tool(name, t(f"villager.{name}", **slots), {"type": "object", "properties": props, "required": required})

    hint = world.story.get("professions", {}).get(a.profession, {}).get("hint", "")
    out = [
        tool("say", {"to": "say_to", "text": "say_text"}, ["text"]),
        tool("look", {"at": "look_at"}, ["at"]),
        tool("post", {"text": "post_text"}, ["text"]),
        tool(
            "give",
            {"to": "give_to", "item": "give_item", "qty": {"type": "integer", "description": t("villager.give_qty"), "minimum": 1}},
            ["to", "item"],
        ),
        tool("work", {}, [], work=hint),
        tool("tend", {}, []),
        tool("attempt", {"what": "attempt_what", "with": "attempt_with"}, ["what"]),
        tool(
            "propose",
            {
                "title": "propose_title",
                "goal": "propose_goal",
                "needs": "propose_needs",
                "at": "propose_at",
                "when": {"type": "string", "enum": list(t.get("time.waves")), "description": t("villager.propose_when")},
            },
            ["title", "goal"],
        ),
        tool("join", {"project": "join_project", "offer": "join_offer"}, ["project"]),
        tool("oppose", {"project": "join_project", "why": "oppose_why"}, ["project"]),
        tool("travel", {"to": "travel_to"}, ["to"]),
    ]
    gods = [t("villager.pray_god")]
    if world.params.get("ullr_agent", 0) > 0:
        gods.append(t("villager.pray_ullr"))
    if a.id == world.story.get("gods", {}).get("follower") and world.params.get("outer_god", 0) > 0:
        gods.append(t("villager.pray_master"))
    if a.id in world.hidden.get("overgod", {}).get("known_by", []):
        gods.append(t("villager.pray_above"))
    out.append(
        tool(
            "pray",
            {"to": {"type": "string", "description": t("villager.pray_to", gods=t("names.list_sep").join(gods))}, "text": "pray_text"},
            ["text"],
        )
    )
    if a.profession == "painter":
        out.append(tool("paint", {"text": "paint_text"}, ["text"]))
    return out


class _Report:
    """Where report_to_parent lands: AgentLoop hands it to its owning worker, and this stands in for one."""

    def __init__(self) -> None:
        self.data: dict[str, Any] | None = None
        self.status = ""

    def record_explicit_report(self, status: str, summary: str, data: dict | None = None) -> None:
        self.status = status
        self.data = {"summary": summary, **(data or {})}


class Turn:
    """One villager's hands for one stirring: applies their tool calls to the world and remembers what was done."""

    def __init__(self, world: World, agent: Agent, act_id: str, loudness: float, emit: Callable[[dict], None] | None = None) -> None:
        self.world, self.agent, self.act_id, self.loudness = world, agent, act_id, loudness
        self.emit = emit or (lambda _event: None)
        self.done: list[str] = []
        self.failures: list[str] = []
        self.emitted: list[str] = []
        self.actions: list[dict] = []

    async def execute(self, tu: ToolUse) -> ToolResult:
        w, a = self.world, self.agent
        if tu.name not in act.HANDLERS:
            return ToolResult(tool_use_id=tu.id, content=w.t("villager.not_a_thing", name=tu.name), is_error=True)
        if a.loc is None:
            return ToolResult(tool_use_id=tu.id, content=w.t("villager.on_road"), is_error=True)
        if len(self.done) >= MAX_ACTIONS:
            return ToolResult(tool_use_id=tu.id, content=w.t("villager.enough"), is_error=True)
        x = {"do": tu.name, **(tu.input or {})}
        where = a.loc
        try:
            if tu.name == "say":
                ids = act.say(w, a, x, self.act_id, self.loudness)
            else:
                ids = act.HANDLERS[tu.name](w, a, x, self.act_id)
        except act.ActionError as exc:
            self.failures.append(str(exc))
            return ToolResult(tool_use_id=tu.id, content=w.t("villager.failed", why=exc), is_error=True)
        summary = act.summarize(w, x)
        self.emitted.extend(ids)
        self.done.append(summary)
        self.actions.append(x)
        self.emit(
            {
                "type": "action",
                "agent": a.id,
                "place": where,
                "do": tu.name,
                "summary": summary,
                "texts": [w.signals[i].text for i in ids if i in w.signals],
            }
        )
        return ToolResult(tool_use_id=tu.id, content=self._answer(tu.name, ids))

    def _answer(self, name: str, ids: list[str]) -> str:
        """What the villager learns at once from what they just did."""
        t = self.world.t
        sigs = [self.world.signals[i] for i in ids if i in self.world.signals]
        if name == "look":
            return t("villager.looked", text=" ".join(s.text for s in sigs if s.kind == "clue"))
        if name == "attempt":
            return t("villager.attempting")
        if name == "travel":
            return t("villager.travelling")
        notes = [n for n in self.agent.failures if n]
        return t("villager.done_notes", notes=t("names.clause_sep").join(notes)) if notes else t("villager.done")


async def run_turn(
    world: World, firing: physics.Firing, llm: LLMProvider, *, bus=None, emit: Callable[[dict], None] | None = None, timeout: float = TURN_TIMEOUT
) -> dict:
    """Run one stirred villager's agent for one part of the day; log it like any stirring and return the record."""
    a = world.agents[firing.agent]
    act_id = world.new_id("a")
    where = a.loc
    a.failures = []
    turn = Turn(world, a, act_id, physics.arousal(firing.stimulus), emit)
    spec = AgentSpec(
        id=f"villager_{a.id}", name=a.name, description=a.role, system_prompt=world.t("villager.rules"), report_schema=report_schema(world)
    )
    ctx = AgentContext(
        runtime=None,  # AgentLoop never reads it
        agent_id=f"villager_{a.id}",
        agent_spec=spec,
        llm=llm,
        available_tools=tools_for(world, a),
        identity_prompt=mind.system_prompt(world, a),
        input_data={"situation": mind.moment(world, a, firing)},
        stream_id=f"worker:{a.id}",  # a worker stream: report_to_parent ends the turn, and nobody escalates
        execution_id=act_id,
        max_tokens=1500,
    )
    loop = AgentLoop(
        event_bus=bus,
        tool_executor=turn.execute,
        conversation_store=None,
        config=LoopConfig(**CONFIG, replay_exempt_tools=LoopConfig().replay_exempt_tools | {"look"}),
    )
    report = _Report()
    loop._owner_worker = report  # the hook a Worker uses to receive report_to_parent; we need the report, not a Worker
    error = None
    tokens = 0
    try:
        result = await asyncio.wait_for(loop.execute(ctx), timeout)
        tokens = result.tokens_used or 0
        if not result.success and report.data is None:
            error = result.error or result.exit_reason
    except TimeoutError:
        loop.signal_shutdown()
        error = f"no report within {timeout:.0f}s"
    except Exception as exc:  # a villager's failed turn must not stop the vale
        logger.exception("villager turn failed: %s", a.id)
        error = str(exc)
    data = report.data or {}
    memory = data.get("memory")
    if isinstance(memory, str) and memory.strip():
        world.write_memory(a.id, memory)
    a.mood = str(data.get("mood") or a.mood)[:24]
    a.failures = turn.failures + a.failures
    when = world.t("time.day_wave", day=world.day, wave=world.wave_name(world.wave))
    if turn.done:
        a.recent = (a.recent + [f"({when}) " + world.t("names.clause_sep").join(turn.done)])[-3:]
    world.today["activations"] = world.today.get("activations", 0) + 1
    if error:
        world.today["llm_errors"] = world.today.get("llm_errors", 0) + 1
    contribs = []
    for sid, c in firing.contribs:
        sig = world.signals.get(sid)
        contribs.append({"signal": sid, "c": c, "cause": sig.cause if sig else None, "kind": sig.kind if sig else None})
    record = {
        "id": act_id,
        "agent": a.id,
        "place": where,
        "stimulus": firing.stimulus,
        "p": firing.p,
        "parent": firing.parent,
        "contribs": contribs,
        "tags": firing.tags,
        "thought": str(data.get("thought") or "")[:600],
        "actions": turn.actions,
        "done": turn.done,
        "failures": a.failures,
        "emitted": turn.emitted,
        "mood": a.mood,
        "memory": memory if isinstance(memory, str) else None,
        "error": error,
        "reserve": a.reserve,
        "tokens": tokens,
    }
    world.log("activation", **record)
    return record
