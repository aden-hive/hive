"""End-to-end queen harness: a real queen, real tools, a real model.

Boots a queen through ``create_queen``'s normal path (the same tool loading
the server does), drives it turn by turn the way ``/chat`` does, and
records what it did from the event bus. Unlike ``tests/live`` this keeps the
per-test ``HIVE_HOME`` isolation from ``tests/conftest.py``: a booted queen
writes sessions and memories, and must not touch your real ``~/.hive`` or
start the MCP servers installed there.

Model endpoint (any OpenAI-compatible server):

    HIVE_LIVE_API_BASE   default http://127.0.0.1:8790/v1
    HIVE_LIVE_MODEL      default gpt-6.1-sol
    HIVE_LIVE_API_KEY    default "local"
    HIVE_LIVE_TIMEOUT    seconds per turn, default 420

Run:  cd core && uv run pytest tests/e2e -m live -v
Tests skip when the endpoint is unreachable; ``-m live`` keeps them out of
the default run and CI. Each run's transcript is written to
``<tmp_path>/transcript.json`` for post-mortems.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

API_BASE = os.environ.get("HIVE_LIVE_API_BASE", "http://127.0.0.1:8790/v1")
MODEL = os.environ.get("HIVE_LIVE_MODEL", "gpt-6.1-sol")
API_KEY = os.environ.get("HIVE_LIVE_API_KEY", "local")
TURN_TIMEOUT_S = float(os.environ.get("HIVE_LIVE_TIMEOUT", "420"))


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    result: Any = None
    is_error: bool = False


@dataclass
class Turn:
    """One user message and everything the queen did before parking again."""

    message: str
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    seconds: float = 0.0


@dataclass
class QueenRun:
    turns: list[Turn]
    workdir: Path
    hive_home: Path
    registry: Any

    @property
    def text(self) -> str:
        """The queen's reply to the last message."""
        return self.turns[-1].text if self.turns else ""

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [c for t in self.turns for c in t.tool_calls]

    def called(self, name: str) -> list[ToolCall]:
        return [c for c in self.tool_calls if c.name == name]

    def summary(self) -> str:
        """Compact what-happened line for assertion messages."""
        return " | ".join(f"turn{i + 1}: {[c.name for c in t.tool_calls]} -> {t.text[:200]!r}" for i, t in enumerate(self.turns))


@pytest.fixture(scope="session")
def live_endpoint() -> str:
    try:
        httpx.get(f"{API_BASE}/models", headers={"Authorization": f"Bearer {API_KEY}"}, timeout=3).raise_for_status()
    except Exception as exc:
        pytest.skip(f"live model endpoint {API_BASE} unreachable: {exc}")
    return API_BASE


@pytest.fixture
def hive_home(_isolate_hive_home_autouse, monkeypatch) -> Path:
    """The isolated ``~/.hive``, also exported as ``HIVE_HOME``.

    Tools that resolve the home from the environment (memory search) would
    otherwise follow a developer's real ``HIVE_HOME`` out of the sandbox.
    """
    monkeypatch.setenv("HIVE_HOME", str(_isolate_hive_home_autouse))
    return _isolate_hive_home_autouse


class _QueenDriver:
    """Boots one queen session and feeds it user turns like ``/chat`` does."""

    def __init__(self, endpoint: str, workdir: Path, queen_id: str) -> None:
        from framework.host.event_bus import EventBus, EventType
        from framework.llm.litellm import LiteLLMProvider
        from framework.server.session_manager import Session

        self._types = EventType
        self.workdir = workdir
        self.queen_id = queen_id
        self.session = Session(
            id=f"session_e2e_{uuid.uuid4().hex[:8]}",
            event_bus=EventBus(),
            llm=LiteLLMProvider(model=f"openai/{MODEL}", api_key=API_KEY, api_base=endpoint),
            loaded_at=time.time(),
            queen_name=queen_id,
        )
        self.events: list[Any] = []
        self._parked = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.turns: list[Turn] = []

    async def _on_event(self, event: Any) -> None:
        self.events.append(event)
        if event.type == self._types.CLIENT_INPUT_REQUESTED:
            self._parked.set()

    async def start(self, *, first_message: str | None, resume: bool, colony: str | None = None) -> None:
        from framework.agents.queen.queen_profiles import DEFAULT_QUEENS
        from framework.host.colony_binding import ColonyBinding
        from framework.server.queen_orchestrator import create_queen
        from framework.server.session_manager import _ensure_minimal_colony

        T = self._types
        self.session.event_bus.subscribe(
            [T.TOOL_CALL_STARTED, T.TOOL_CALL_COMPLETED, T.CLIENT_OUTPUT_DELTA, T.CLIENT_INPUT_REQUESTED],
            self._on_event,
        )
        if resume:
            self.session.queen_resume_from = self.session.id
        if colony:
            # The server's own fresh-colony bootstrap (session_manager.create_session).
            self.session.worker_path = _ensure_minimal_colony(colony, queen_name=self.queen_id)
            self.session.colony_id = colony
            self.session.binding = ColonyBinding.for_name(colony)
            self.session.mode = "colony"
        manager = MagicMock()
        manager._subscribe_worker_handoffs = MagicMock()
        mark = len(self.events)
        started = time.monotonic()
        self._task = await create_queen(
            session=self.session,
            session_manager=manager,
            worker_identity=None,
            queen_dir=self.workdir,
            queen_profile=DEFAULT_QUEENS[self.queen_id],
            initial_prompt=first_message,
            # A colony-bound session derives its phase from the binding.
            initial_phase=None if colony else "independent",
        )
        if first_message is not None:
            await self._wait_turn(first_message, mark, started)

    async def send(self, message: str) -> Turn:
        from framework.host.event_bus import AgentEvent

        node = None
        deadline = time.monotonic() + 60
        while node is None and time.monotonic() < deadline:
            executor = getattr(self.session, "queen_executor", None)
            node = executor.node_registry.get("queen") if executor is not None else None
            if node is None:
                await asyncio.sleep(0.2)
        assert node is not None, "queen loop never came up"

        mark = len(self.events)
        started = time.monotonic()
        self._parked.clear()
        await self.session.event_bus.publish(
            AgentEvent(
                type=self._types.CLIENT_INPUT_RECEIVED,
                stream_id="queen",
                node_id="queen",
                execution_id=self.session.id,
                data={"content": message, "image_count": 0},
            )
        )
        await node.inject_event(message, is_client_input=True)
        return await self._wait_turn(message, mark, started)

    async def _wait_turn(self, message: str, mark: int, started: float) -> Turn:
        T = self._types
        deadline = started + TURN_TIMEOUT_S
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                pytest.fail(f"queen did not finish within {TURN_TIMEOUT_S:.0f}s on: {message[:80]!r}")
            self._parked.clear()
            with suppress(TimeoutError):
                await asyncio.wait_for(self._parked.wait(), timeout=remaining)
            # A park only ends this turn once the queen did something after
            # the message; a stale park from boot/restore doesn't count.
            if any(e.type in (T.CLIENT_OUTPUT_DELTA, T.TOOL_CALL_STARTED) for e in self.events[mark:]):
                break

        turn = Turn(message=message, seconds=round(time.monotonic() - started, 1))
        for event in self.events[mark:]:
            data = event.data or {}
            if event.type == T.TOOL_CALL_STARTED:
                turn.tool_calls.append(ToolCall(name=data.get("tool_name", ""), input=data.get("tool_input") or {}))
            elif event.type == T.TOOL_CALL_COMPLETED:
                for call in reversed(turn.tool_calls):
                    if call.name == data.get("tool_name") and call.result is None:
                        call.result, call.is_error = data.get("result"), bool(data.get("is_error"))
                        break
            elif event.type == T.CLIENT_OUTPUT_DELTA:
                turn.text = data.get("snapshot") or turn.text
        self.turns.append(turn)
        return turn

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._task


@pytest.fixture
def run_queen(live_endpoint, hive_home, tmp_path, monkeypatch):
    """``await run_queen(turns, ...)`` → :class:`QueenRun`.

    * *turns*: user messages, sent one after another in a single session.
    * *seed(workdir, hive_home)*: plants files and synthetic past sessions
      before boot; whatever it returns is handed back as ``run.truth``.
    * *resume(workdir)*: async; writes an in-progress conversation into the
      queen's session dir, which the queen then restores instead of
      starting fresh.
    * *colony*: boot the session bound to this colony (created minimal,
      as the server does for a fresh colony).
    """
    from framework.agents.queen import queen_memory_v2

    monkeypatch.setattr(queen_memory_v2, "MEMORIES_DIR", hive_home / "memories")

    async def _run(turns: list[str], *, queen_id: str = "queen_technology", seed=None, resume=None, colony=None) -> QueenRun:
        workdir = tmp_path / "queen"
        workdir.mkdir(parents=True, exist_ok=True)
        truth = seed(workdir, hive_home) if seed is not None else None
        if resume is not None:
            await resume(workdir)

        driver = _QueenDriver(live_endpoint, workdir, queen_id)
        try:
            if resume is not None:
                await driver.start(first_message=None, resume=True, colony=colony)
                pending = list(turns)
            else:
                await driver.start(first_message=turns[0], resume=False, colony=colony)
                pending = list(turns[1:])
            for message in pending:
                await driver.send(message)
        finally:
            await driver.stop()
            (tmp_path / "transcript.json").write_text(
                json.dumps([asdict(t) for t in driver.turns], indent=2, default=str),
                encoding="utf-8",
            )

        run = QueenRun(
            turns=driver.turns,
            workdir=workdir,
            hive_home=hive_home,
            registry=getattr(driver.session, "_queen_tool_registry", None),
        )
        run.truth = truth  # type: ignore[attr-defined]
        return run

    return _run


# ---------------------------------------------------------------------------
# LongMemEval run directory + report (test_longmemeval.py)
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    # Fixed once in the controller, before xdist spawns workers, so every
    # worker appends to the same results file.
    if not os.environ.get("HIVE_LME_RUN_DIR"):
        from tests.e2e import longmemeval

        os.environ["HIVE_LME_RUN_DIR"] = str(longmemeval.DATA_DIR / "runs" / time.strftime("%Y%m%d-%H%M%S"))


def pytest_terminal_summary(terminalreporter: Any, config: pytest.Config) -> None:
    if hasattr(config, "workerinput"):
        return  # xdist worker; the controller reports
    results = Path(os.environ.get("HIVE_LME_RUN_DIR", "")) / "results.jsonl"
    if not results.is_file():
        return
    from tests.e2e import longmemeval

    report = longmemeval.summarize(results)
    (results.parent / "summary.txt").write_text(f"{report}\n", encoding="utf-8")
    terminalreporter.write_sep("=", "LongMemEval-S")
    terminalreporter.write_line(report)
    terminalreporter.write_line(f"results: {results.parent}")
