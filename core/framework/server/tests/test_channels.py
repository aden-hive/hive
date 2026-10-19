"""Channels: chat apps that reach queens from inside ``hive serve``."""

from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from framework.config import queen_sessions_dir
from framework.host.event_bus import AgentEvent, EventType
from framework.server import channels
from framework.server.app import create_app
from framework.server.channels import ChannelHost, QueenOutput

QUEEN = "queen_growth"


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (4, 3), "red").save(out, format="PNG")
    return out.getvalue()


def _live_session_factory(manager):
    """Make ``manager.create_session`` start a real session (event bus and all) whose queen is
    a stand-in that records what she is sent."""

    async def create_session(*, queen_name, queen_resume_from=None, **_):
        session = await manager._create_session_core(session_id=queen_resume_from)
        session.queen_name = queen_name
        session.queen_dir = queen_sessions_dir(queen_name) / session.id
        session.queen_dir.mkdir(parents=True, exist_ok=True)
        if not (session.queen_dir / "meta.json").exists():
            (session.queen_dir / "meta.json").write_text(json.dumps({"queen_id": queen_name}))
        node = MagicMock()
        node.inject_event = AsyncMock()
        session.queen_executor = SimpleNamespace(node_registry={"queen": node})
        return session

    return AsyncMock(side_effect=create_session)


@pytest.fixture
def manager():
    app = create_app()
    mgr = app["manager"]
    mgr.create_session = _live_session_factory(mgr)
    return mgr


async def _say(bus, *events: tuple[EventType, dict]) -> None:
    for type_, data in events:
        await bus.publish(AgentEvent(type=type_, stream_id="queen", data=data))
    for _ in range(20):
        await asyncio.sleep(0)


def _heard(host: ChannelHost, session_id: str) -> list[QueenOutput]:
    heard: list[QueenOutput] = []

    async def on_output(output: QueenOutput) -> None:
        heard.append(output)

    host.subscribe(session_id, on_output)
    return heard


@pytest.mark.asyncio
async def test_a_new_conversation_is_a_titled_channel_session(manager):
    host = ChannelHost("onebot", manager, {})

    sid = await host.open_session(QUEEN, title="QQ group: Night owls")

    meta = json.loads((queen_sessions_dir(QUEEN) / sid / "meta.json").read_text(encoding="utf-8"))
    assert meta["channel"] == "onebot"
    assert meta["title"] == "QQ group: Night owls"
    assert manager.get_session(sid).channel == "onebot"


@pytest.mark.asyncio
async def test_send_hands_text_and_images_to_the_queen_like_the_dashboard(manager):
    host = ChannelHost("onebot", manager, {})
    sid = await host.open_session(QUEEN)

    assert await host.send(sid, "[Ann(42)]: look at this", images=[_png(), b"not an image"], display_text="look at this") == sid

    session = manager.get_session(sid)
    node = session.queen_executor.node_registry["queen"]
    message = node.inject_event.await_args.args[0]
    blocks = node.inject_event.await_args.kwargs["image_content"]
    assert message.startswith("[Ann(42)]: look at this")
    assert [b["image_url"]["url"][:22] for b in blocks] == ["data:image/png;base64,"]
    assert len(list((session.queen_dir / "data" / "attachments").iterdir())) == 1


@pytest.mark.asyncio
async def test_the_queen_is_heard_turn_by_turn_in_order(manager):
    host = ChannelHost("onebot", manager, {})
    sid = await host.open_session(QUEEN)
    heard = _heard(host, sid)

    await _say(
        manager.get_session(sid).event_bus,
        (EventType.CLIENT_OUTPUT_DELTA, {"snapshot": "Let me look."}),
        (EventType.LLM_TURN_COMPLETE, {"stop_reason": "tool_calls"}),
        (EventType.CLIENT_OUTPUT_DELTA, {"snapshot": "Found"}),
        (EventType.CLIENT_OUTPUT_DELTA, {"snapshot": "Found it."}),
        (EventType.LLM_TURN_COMPLETE, {"stop_reason": "stop"}),
        (EventType.CLIENT_INPUT_REQUESTED, {"park_reason": "turn_done"}),
    )

    assert heard == [
        QueenOutput(session_id=sid, kind="message", text="Let me look."),
        QueenOutput(session_id=sid, kind="message", text="Found it."),
    ]


@pytest.mark.asyncio
async def test_a_question_is_heard_once_as_a_question(manager):
    host = ChannelHost("onebot", manager, {})
    sid = await host.open_session(QUEEN)
    heard = _heard(host, sid)
    question = {"id": "q1", "prompt": "Which city?"}

    await _say(
        manager.get_session(sid).event_bus,
        (EventType.LLM_TURN_COMPLETE, {"stop_reason": "tool_calls"}),
        (EventType.CLIENT_OUTPUT_DELTA, {"snapshot": "Which city?"}),
        (EventType.CLIENT_INPUT_REQUESTED, {"park_reason": "ask_user", "questions": [question]}),
    )

    assert heard == [QueenOutput(session_id=sid, kind="question", questions=[question])]


@pytest.mark.asyncio
async def test_a_failed_model_call_is_heard_as_an_error(manager):
    host = ChannelHost("onebot", manager, {})
    sid = await host.open_session(QUEEN)
    heard = _heard(host, sid)

    await _say(
        manager.get_session(sid).event_bus,
        (EventType.CLIENT_OUTPUT_DELTA, {"snapshot": "[Error: LLM call failed: 502. Please try again.]"}),
        (EventType.CLIENT_INPUT_REQUESTED, {"park_reason": "llm_error"}),
    )

    assert [(o.kind, o.text) for o in heard] == [("error", "[Error: LLM call failed: 502. Please try again.]")]


@pytest.mark.asyncio
async def test_a_failed_call_a_gateway_returned_as_a_reply_is_heard_as_an_error(manager):
    host = ChannelHost("onebot", manager, {})
    sid = await host.open_session(QUEEN)
    heard = _heard(host, sid)
    error = "[Error: LLM call failed: Stream error: Authentication Fails, Your api key: ****abcd is invalid. Please try again.]"

    await _say(
        manager.get_session(sid).event_bus,
        (EventType.CLIENT_OUTPUT_DELTA, {"snapshot": error}),
        (EventType.LLM_TURN_COMPLETE, {"stop_reason": "stop"}),
        (EventType.CLIENT_INPUT_REQUESTED, {"park_reason": "turn_done"}),
    )

    assert [(o.kind, o.text) for o in heard] == [("error", error)]


@pytest.mark.asyncio
async def test_a_stopped_session_is_resumed_and_still_heard(manager):
    host = ChannelHost("onebot", manager, {})
    sid = await host.open_session(QUEEN)
    heard = _heard(host, sid)
    await manager.stop_session(sid)

    assert await host.send(sid, "still there?") == sid

    await _say(
        manager.get_session(sid).event_bus,
        (EventType.CLIENT_OUTPUT_DELTA, {"snapshot": "Yes."}),
        (EventType.LLM_TURN_COMPLETE, {"stop_reason": "stop"}),
    )
    assert [o.text for o in heard] == ["Yes."]
    assert manager.create_session.await_args.kwargs["queen_resume_from"] == sid


@pytest.mark.asyncio
async def test_a_handler_that_raises_does_not_silence_the_next_output(manager):
    host = ChannelHost("onebot", manager, {})
    sid = await host.open_session(QUEEN)
    heard: list[str] = []

    async def flaky(output: QueenOutput) -> None:
        heard.append(output.text)
        if len(heard) == 1:
            raise ConnectionError("chat app went away")

    host.subscribe(sid, flaky)
    bus = manager.get_session(sid).event_bus
    for text in ("one", "two"):
        await _say(bus, (EventType.CLIENT_OUTPUT_DELTA, {"snapshot": text}), (EventType.LLM_TURN_COMPLETE, {}))

    assert heard == ["one", "two"]


@pytest.mark.asyncio
async def test_the_dashboard_leaves_channel_sessions_alone():
    app = create_app()
    manager = app["manager"]
    manager.create_session = _live_session_factory(manager)
    host = ChannelHost("onebot", manager, {})
    dm = (await manager.create_session(queen_name=QUEEN)).id
    group = await host.open_session(QUEEN)  # the newest: what the dashboard would pick

    # (Checked inside: shutting the test server down stops every session.)
    async with TestClient(TestServer(app)) as client:
        opened = await (await client.post(f"/api/queen/{QUEEN}/session")).json()
        await client.post(f"/api/queen/{QUEEN}/session/new")

        assert opened["session_id"] == dm
        assert manager.get_session(group) is not None
        assert manager.get_session(dm) is None


class _FakeChannel:
    def __init__(self, host: ChannelHost, *, fail: bool = False) -> None:
        self.host, self.fail, self.stopped = host, fail, False

    async def start(self) -> None:
        if self.fail:
            raise RuntimeError("no QQ client connected")

    async def stop(self) -> None:
        self.stopped = True


def _entry_point(factory):
    return SimpleNamespace(load=lambda: factory)


@pytest.mark.asyncio
async def test_the_server_starts_enabled_channels_and_reports_the_rest(monkeypatch):
    started: list[_FakeChannel] = []

    def good(host):
        started.append(_FakeChannel(host))
        return started[-1]

    monkeypatch.setattr(
        channels,
        "_installed",
        lambda: {"good": _entry_point(good), "bad": _entry_point(lambda h: _FakeChannel(h, fail=True)), "idle": _entry_point(good)},
    )
    settings = {"good": {"enabled": True, "port": 6199}, "bad": {"enabled": True}}
    monkeypatch.setattr("framework.config.get_hive_config", lambda: {"channels": settings})

    async with TestClient(TestServer(create_app())) as client:
        listed = await (await client.get("/api/channels")).json()

    assert listed["channels"] == [
        {"name": "bad", "state": "failed", "error": "RuntimeError: no QQ client connected"},
        {"name": "good", "state": "running"},
        {"name": "idle", "state": "off"},
    ]
    assert [c.host.config for c in started] == [{"enabled": True, "port": 6199}]
    assert started[0].stopped


@pytest.mark.asyncio
async def test_a_message_waits_for_a_queen_who_is_still_starting(manager):
    host = ChannelHost("onebot", manager, {})
    sid = await host.open_session(QUEEN)
    session = manager.get_session(sid)
    executor, session.queen_executor = session.queen_executor, None

    async def starting() -> None:
        await asyncio.sleep(0.3)
        session.queen_executor = executor

    session.queen_task = asyncio.create_task(starting())
    manager.revive_queen = AsyncMock()

    await host.send(sid, "hello")

    executor.node_registry["queen"].inject_event.assert_awaited_once()
    manager.revive_queen.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_big_photo_reaches_the_queen_scaled_down(manager):
    host = ChannelHost("onebot", manager, {})
    sid = await host.open_session(QUEEN)
    photo = io.BytesIO()
    Image.new("RGB", (4000, 3000), "blue").save(photo, format="PNG")

    await host.send(sid, "look", images=[photo.getvalue()])

    (block,) = manager.get_session(sid).queen_executor.node_registry["queen"].inject_event.await_args.kwargs["image_content"]
    import base64

    url = block["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    assert Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size == (2048, 1536)


@pytest.mark.asyncio
async def test_files_she_attaches_are_heard(manager):
    host = ChannelHost("onebot", manager, {})
    sid = await host.open_session(QUEEN)
    heard = _heard(host, sid)
    session = manager.get_session(sid)
    picture = session.queen_dir / "data" / "attachments" / "fox.png"
    picture.parent.mkdir(parents=True, exist_ok=True)
    picture.write_bytes(_png())
    summary = {"attached": [{"path": "fox.png", "resolved": str(picture)}], "errors": []}

    await _say(
        session.event_bus,
        (EventType.TOOL_CALL_COMPLETED, {"tool_name": "attach_file", "is_error": False, "result": json.dumps(summary) + "\n(text body)"}),
        (EventType.TOOL_CALL_COMPLETED, {"tool_name": "attach_file", "is_error": True, "result": json.dumps(summary)}),
        (EventType.TOOL_CALL_COMPLETED, {"tool_name": "terminal_exec", "is_error": False, "result": json.dumps(summary)}),
    )

    assert heard == [QueenOutput(session_id=sid, kind="files", files=[picture])]
