"""Live harness for the LLM-context-bloat optimization plan.

Every test in this module makes REAL LLM API calls against the model
resolved by the ``live_model`` fixture (default
``anthropic/claude-haiku-4-5-20251001``). The harness wires up real
``AgentLoop`` / ``NodeContext`` / ``NodeConversation`` / ``LiteLLMProvider``
/ ``EventBus`` / ``FileConversationStore`` — the same classes the desktop
app constructs. No mock LLMs, no test-only subclasses of any context-
handling component.

Why no mocks: the optimization being verified (prompt-cache breakpoints,
narrative split, microcompaction) is observable ONLY in the
``cache_creation_tokens`` / ``cached_tokens`` fields that real providers
report. A mocked LLM cannot validate the optimization because the
provider's caching is the thing under test.

Run manually:

    ANTHROPIC_API_KEY=sk-... uv run pytest -m live core/tests/live -s

Override the model with ``HIVE_LIVE_MODEL=anthropic/<other>``.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from framework.agent_loop.agent_loop import AgentLoop
from framework.agent_loop.internals.types import LoopConfig
from framework.host.event_bus import EventBus
from framework.llm.litellm import LiteLLMProvider
from framework.llm.provider import Tool, ToolResult, ToolUse
from framework.orchestrator.node import DataBuffer, NodeContext, NodeSpec
from framework.storage.conversation_store import FileConversationStore
from framework.tracker.decision_tracker import DecisionTracker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Real-tool builders. These are minimal tool surfaces, NOT stubs of the
# desktop app's tool registry — each tool here actually performs its
# action against the real filesystem so the model gets genuine
# variable-sized tool results and the conversation history grows
# naturally.
# ---------------------------------------------------------------------------


def _build_read_file_tool() -> Tool:
    return Tool(
        name="read_file",
        description=("Read the contents of a file at the given absolute path. Returns the file contents as text."),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file to read.",
                },
            },
            "required": ["path"],
        },
    )


def _make_read_file_executor(allowed_root: Path) -> Callable[[ToolUse], Awaitable[ToolResult]]:
    """Return a real read_file executor scoped to ``allowed_root``.

    The scoping is a safety guard so a misbehaving model in the live test
    can't read arbitrary files on disk. The tool itself behaves the same
    as production: takes a path, returns the contents.
    """

    allowed_root = allowed_root.resolve()

    async def execute(tool_use: ToolUse) -> ToolResult:
        if tool_use.name != "read_file":
            return ToolResult(
                tool_use_id=tool_use.id,
                content=f"Unknown tool: {tool_use.name}",
                is_error=True,
            )
        raw_path = (tool_use.arguments or {}).get("path", "")
        if not raw_path:
            return ToolResult(
                tool_use_id=tool_use.id,
                content="Error: path argument is required.",
                is_error=True,
            )
        target = Path(raw_path).resolve()
        try:
            target.relative_to(allowed_root)
        except ValueError:
            return ToolResult(
                tool_use_id=tool_use.id,
                content=f"Error: path {target} is outside the allowed sandbox {allowed_root}.",
                is_error=True,
            )
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult(
                tool_use_id=tool_use.id,
                content=f"Error reading {target}: {exc}",
                is_error=True,
            )
        return ToolResult(tool_use_id=tool_use.id, content=text)

    return execute


# ---------------------------------------------------------------------------
# Session driver
# ---------------------------------------------------------------------------


async def run_live_session(
    *,
    llm_config,  # LiveLLMConfig from conftest
    system_prompt: str,
    initial_goal: str,
    tools: list[Tool],
    tool_executor: Callable[[ToolUse], Awaitable[ToolResult]],
    tmp_path: Path,
    max_iterations: int = 25,
    max_context_tokens: int = 200_000,
) -> Path:
    """Run a real single-execute() session and return the events.jsonl path.

    A single ``AgentLoop.execute()`` call internally produces many LLM
    turns when the model uses tools — the production session at
    ``queen_finance_fundraising/.../session_20260508_102516_c8fd6fa7``
    runs 17 LLM turns inside one logical user request, which is what
    makes per-turn cache behavior observable.
    """
    events_path = tmp_path / "events.jsonl"
    bus = EventBus()
    bus.set_session_log(events_path)

    llm = LiteLLMProvider(
        model=llm_config.model,
        api_key=llm_config.api_key,
        api_base=llm_config.api_base,
        **llm_config.extra_kwargs,
    )

    spec = NodeSpec(
        id="live_cache_test",
        name="Live Cache Test",
        description="Live verification harness for context-bloat optimizations.",
        node_type="event_loop",
        output_keys=[],
        system_prompt=system_prompt,
        skip_judge=True,
    )

    buffer = DataBuffer()
    runtime = DecisionTracker(storage_path=tmp_path / "tracker")

    ctx = NodeContext(
        runtime=runtime,
        node_id=spec.id,
        node_spec=spec,
        buffer=buffer,
        input_data={},
        llm=llm,
        available_tools=tools,
        goal_context=initial_goal,
        stream_id="judge",  # opt out of worker auto-escalation (no queen in harness)
    )

    store = FileConversationStore(tmp_path / "conv")
    loop = AgentLoop(
        event_bus=bus,
        config=LoopConfig(
            max_iterations=max_iterations,
            max_context_tokens=max_context_tokens,
        ),
        tool_executor=tool_executor,
        conversation_store=store,
    )

    try:
        result = await loop.execute(ctx)
    finally:
        bus.close_session_log()

    logger.info(
        "Live session finished: success=%s exit_reason=%s events=%s",
        result.success,
        result.exit_reason,
        events_path,
    )
    return events_path


# ---------------------------------------------------------------------------
# Metrics extraction from events.jsonl (same jq queries the plan documents)
# ---------------------------------------------------------------------------


def _read_events(events_path: Path) -> list[dict]:
    if not events_path.exists():
        return []
    out: list[dict] = []
    with events_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def cache_metrics(events_path: Path) -> dict:
    """Extract per-turn and aggregate cache metrics."""
    turns = [e for e in _read_events(events_path) if e.get("type") == "llm_turn_complete"]
    per_turn = []
    total_input = 0
    total_cached = 0
    total_created = 0
    total_output = 0
    total_cost = 0.0
    for e in turns:
        d = e.get("data", {}) or {}
        inp = int(d.get("input_tokens", 0) or 0)
        cached = int(d.get("cached_tokens", 0) or 0)
        created = int(d.get("cache_creation_tokens", 0) or 0)
        out_tok = int(d.get("output_tokens", 0) or 0)
        cost = float(d.get("cost_usd", 0) or 0.0)
        total_input += inp
        total_cached += cached
        total_created += created
        total_output += out_tok
        total_cost += cost
        per_turn.append(
            {
                "iteration": d.get("iteration"),
                "input": inp,
                "cached": cached,
                "create": created,
                "output": out_tok,
                "cost_usd": cost,
                "uncached": inp - cached,
            }
        )
    uncached = total_input - total_cached
    hit_ratio = (total_cached / total_input) if total_input else 0.0
    return {
        "turns": len(per_turn),
        "total_input_tokens": total_input,
        "total_cached_tokens": total_cached,
        "total_cache_creation_tokens": total_created,
        "total_uncached_tokens": uncached,
        "total_output_tokens": total_output,
        "total_cost_usd": round(total_cost, 6),
        "cache_hit_ratio": round(hit_ratio, 4),
        "per_turn": per_turn,
    }


def usage_trajectory(events_path: Path) -> list[dict]:
    return [e.get("data", {}) for e in _read_events(events_path) if e.get("type") == "context_usage_updated"]


def compaction_events(events_path: Path) -> list[dict]:
    return [e.get("data", {}) for e in _read_events(events_path) if e.get("type") in ("context_compacted", "microcompact_fired")]


# ---------------------------------------------------------------------------
# Smoke test: verify the harness wires up correctly against a real provider
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_harness_smoke(
    tmp_path: Path,
    live_llm_config,
) -> None:
    """Construct every real component and run a 1-turn session.

    Validates the harness itself before any optimization-specific
    assertions. Any failure here means the harness, not the
    optimization, is broken — fix it before running the larger
    scenarios.
    """
    events_path = await run_live_session(
        llm_config=live_llm_config,
        system_prompt="You are a terse test assistant. Reply with one word.",
        initial_goal="Say HARNESS_OK and nothing else.",
        tools=[],
        tool_executor=_make_read_file_executor(tmp_path),
        tmp_path=tmp_path,
        max_iterations=3,
    )
    metrics = cache_metrics(events_path)
    assert metrics["turns"] >= 1, f"No LLM turns observed in {events_path}"
    assert metrics["total_input_tokens"] > 0
    assert metrics["total_output_tokens"] > 0
    logger.info("Harness smoke metrics: %s", json.dumps(metrics, indent=2))


# ---------------------------------------------------------------------------
# Scenario fixtures
# ---------------------------------------------------------------------------


def _seed_real_files(root: Path, count: int = 15, target_bytes: int = 12_000) -> list[Path]:
    """Copy the bundled SKILL.md files into ``root`` so read_file calls
    return real, varied content of roughly the right size.
    """
    root.mkdir(parents=True, exist_ok=True)
    skills_dir = Path(__file__).parents[3] / "core" / "framework" / "skills" / "_default_skills"
    if not skills_dir.exists():
        # Fallback: fabricate files. Still real content, just synthetic.
        out: list[Path] = []
        filler = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 200)[:target_bytes]
        for i in range(count):
            p = root / f"file_{i:02d}.txt"
            p.write_text(f"# File {i}\n{filler}\n", encoding="utf-8")
            out.append(p)
        return out

    sources = sorted(skills_dir.glob("*/SKILL.md"))
    if not sources:
        return _seed_real_files(root, count, target_bytes)  # fallback path
    out: list[Path] = []
    for i in range(count):
        src = sources[i % len(sources)]
        dst = root / f"file_{i:02d}.md"
        body = src.read_text(encoding="utf-8")
        # Pad or truncate to approximately the target size so each
        # tool result is comparable across scenarios.
        if len(body) < target_bytes:
            body = body + "\n\n" + body * ((target_bytes // max(1, len(body))) + 1)
        dst.write_text(body[:target_bytes], encoding="utf-8")
        out.append(dst)
    return out


@pytest.mark.live
@pytest.mark.asyncio
async def test_baseline_short(
    tmp_path: Path,
    live_llm_config,
) -> None:
    """5-turn no-tools scenario — establishes cache-hit floor.

    Records baseline metrics to ``core/tests/live/baseline/`` so per-
    change runs can compare against unchanged code.
    """
    events_path = await run_live_session(
        llm_config=live_llm_config,
        system_prompt=("You are a helpful assistant testing prompt-cache behavior. Answer concisely. Do not call any tools."),
        initial_goal=(
            "Count from 1 to 5, one number per response, and after each number wait for the next user turn before continuing. Output only the number."
        ),
        tools=[],
        tool_executor=_make_read_file_executor(tmp_path),
        tmp_path=tmp_path,
        max_iterations=6,
    )
    metrics = cache_metrics(events_path)
    logger.info("baseline_short: %s", json.dumps(metrics, indent=2))
    _archive_baseline(events_path, name="baseline_short")
    assert metrics["turns"] >= 1


@pytest.mark.live
@pytest.mark.asyncio
async def test_baseline_tool_heavy(
    tmp_path: Path,
    live_llm_config,
) -> None:
    """15 read_file calls — establishes tool-result-bloat baseline."""
    sandbox = tmp_path / "sandbox"
    files = _seed_real_files(sandbox, count=15, target_bytes=12_000)
    file_list = "\n".join(f"- {p}" for p in files)
    events_path = await run_live_session(
        llm_config=live_llm_config,
        system_prompt=(
            "You are a careful file reader. For each path in the user's list, "
            "call read_file exactly once. After reading all files, respond with "
            "the single line: DONE."
        ),
        initial_goal=(
            "Read each of the following files in order, one read_file call per turn, and after the last one reply with DONE.\n\n" + file_list
        ),
        tools=[_build_read_file_tool()],
        tool_executor=_make_read_file_executor(sandbox),
        tmp_path=tmp_path,
        max_iterations=30,
    )
    metrics = cache_metrics(events_path)
    logger.info("baseline_tool_heavy: %s", json.dumps(metrics, indent=2))
    _archive_baseline(events_path, name="baseline_tool_heavy")
    assert metrics["turns"] >= 3  # at minimum a few turns of tool use


def _archive_baseline(events_path: Path, *, name: str) -> None:
    """Copy events.jsonl into the repo's baseline archive when explicitly
    requested via HIVE_LIVE_ARCHIVE_BASELINES=1. Off by default so
    routine pytest runs don't overwrite committed baselines.
    """
    if os.getenv("HIVE_LIVE_ARCHIVE_BASELINES") != "1":
        return
    dest_dir = Path(__file__).parent / "baseline"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{name}.jsonl"
    dest.write_text(events_path.read_text(), encoding="utf-8")
    logger.info("Archived baseline to %s", dest)
