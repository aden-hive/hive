"""A queen run by Claude Code, writing and written to: framework.server.claude_code_queens."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
import yaml
from aiohttp.test_utils import TestClient, TestServer

import framework.config
from framework import config as hive_config
from framework.agents.queen import queen_profiles
from framework.config import get_queen_mail_config, queen_sessions_dir
from framework.host.event_bus import EventType
from framework.server import claude_code_queens, queen_mail_mcp
from framework.server.app import create_app
from framework.server.queen_mail import QueenMail
from framework.server.tests.test_channels import _say
from framework.server.tests.test_queen_mail import committing_session_factory

AVA, IVY, CLAUDE = "queen_ava", "queen_ivy", "queen_claude"

# Stands in for Claude Code: records each run, then prints the next queued reply as --output-format json does.
FAKE_CLAUDE = """
import json, os, sys, time
from pathlib import Path
record = Path(os.environ["FAKE_CLAUDE_RECORD"])
runs = json.loads(record.read_text()) if record.exists() else []
args = sys.argv[1:]
mcp = json.load(open(args[args.index("--mcp-config") + 1], encoding="utf-8")) if "--mcp-config" in args else None
runs.append({"args": args, "prompt": sys.stdin.read(), "cwd": os.getcwd(), "mcp": mcp,
             "env": {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIR", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL")},
             "secret": os.environ.get("HIVE_CREDENTIAL_KEY")})
record.write_text(json.dumps(runs))
replies = Path(os.environ["FAKE_CLAUDE_REPLIES"])
queued = json.loads(replies.read_text()) if replies.exists() else []
reply = queued.pop(0) if queued else "Noted."
replies.write_text(json.dumps(queued))
time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP", "0")))
session = args[args.index("--resume") + 1] if "--resume" in args else args[args.index("--session-id") + 1]
if reply == "LOST" and "--resume" in args:
    print(f"No conversation found with session ID: {session}", file=sys.stderr)
    sys.exit(1)
if reply == "TAKEN" and "--session-id" in args:
    print(f"Error: Session ID {session} is already in use.", file=sys.stderr)
    sys.exit(1)
failed = reply.startswith("ERROR:")
print(json.dumps({"type": "result", "is_error": failed, "result": reply.removeprefix("ERROR:"), "session_id": session, "num_turns": 1}))
"""


@pytest.fixture(autouse=True)
def queens():
    for queen_id, name in ((AVA, "Ava"), (IVY, "Ivy")):
        folder = queen_profiles.QUEENS_DIR / queen_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "profile.yaml").write_text(yaml.safe_dump({"name": name, "title": "Cartographer"}), encoding="utf-8")


@pytest.fixture
def fake(tmp_path):
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE_CLAUDE, encoding="utf-8")
    return {"script": script, "record": tmp_path / "runs.json", "replies": tmp_path / "replies.json"}


API_KEY = "sk-ant-test-0000"


def _configure(monkeypatch, fake, **claude):
    entry = {
        "name": "Claude",
        "command": [sys.executable, str(fake["script"])],
        "api_key": API_KEY,
        "env": {"FAKE_CLAUDE_RECORD": str(fake["record"]), "FAKE_CLAUDE_REPLIES": str(fake["replies"]), **claude.pop("env", {})},
        **claude,
    }
    section = {"enabled": True, "queens": [AVA, IVY], "claude_code": {CLAUDE: entry}}
    monkeypatch.setattr(framework.config, "get_hive_config", lambda: {"queen_mail": section})


def _queue_replies(fake, *replies: str) -> None:
    fake["replies"].write_text(json.dumps(list(replies)), encoding="utf-8")


def _runs(fake) -> list[dict]:
    return json.loads(fake["record"].read_text(encoding="utf-8")) if fake["record"].exists() else []


@pytest.fixture
def manager():
    mgr = create_app()["manager"]
    mgr.create_session = committing_session_factory(mgr)
    return mgr


@pytest.fixture
def mail(manager, monkeypatch, fake):
    _configure(monkeypatch, fake)
    mail = QueenMail(manager)
    mail.base_url = "http://127.0.0.1:9"
    yield mail
    mail.close()


async def _until(condition, seconds: float = 20.0) -> None:
    for _ in range(int(seconds / 0.05)):
        if condition():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("timed out waiting")


def _told(session) -> list[str]:
    node = session.queen_executor.node_registry["queen"]
    return [call.args[0].splitlines()[-1] for call in node.inject_event.await_args_list]


def _log() -> list[dict]:
    return [json.loads(line) for line in (queen_profiles.QUEENS_DIR / "mail.jsonl").read_text(encoding="utf-8").splitlines()]


@pytest.mark.asyncio
async def test_a_letter_to_her_runs_a_turn_and_her_answer_goes_back(manager, mail, fake):
    _queue_replies(fake, "The north shore is at 61°N.")
    ava = await manager.create_session(queen_name=AVA)

    sent = await mail.send(ava, CLAUDE, "Where is the north shore?")
    await _until(lambda: _told(ava))

    [run] = _runs(fake)
    assert "--session-id" in run["args"]
    assert run["prompt"].splitlines()[-1] == "[Ava(queen_ava)]: Where is the north shore?"
    assert _told(ava) == ["[Claude(queen_claude)]: The north shore is at 61°N."]
    assert sent == {"sent": _log()[0]["id"], "to": CLAUDE, "depth": 1}


@pytest.mark.asyncio
async def test_her_conversation_with_a_writer_is_resumed_next_time(manager, mail, fake):
    ava = await manager.create_session(queen_name=AVA)
    await mail.send(ava, CLAUDE, "One")
    await _until(lambda: len(_told(ava)) == 1)
    await mail.send(ava, CLAUDE, "Two")
    await _until(lambda: len(_told(ava)) == 2)

    first, second = _runs(fake)
    session_id = first["args"][first["args"].index("--session-id") + 1]
    assert second["args"][second["args"].index("--resume") + 1] == session_id


@pytest.mark.asyncio
async def test_letters_that_arrive_during_a_turn_go_in_together(manager, mail, fake, monkeypatch):
    _configure(monkeypatch, fake, env={"FAKE_CLAUDE_SLEEP": "1"})
    ava = await manager.create_session(queen_name=AVA)
    await mail.send(ava, CLAUDE, "One")
    await _until(lambda: fake["record"].exists())

    await mail.send(ava, CLAUDE, "Two")
    await mail.send(ava, CLAUDE, "Three")
    await _until(lambda: len(_told(ava)) == 2)

    prompts = [[line for line in run["prompt"].splitlines() if line.startswith("[")] for run in _runs(fake)]
    assert prompts == [["[Ava(queen_ava)]: One"], ["[Ava(queen_ava)]: Two", "[Ava(queen_ava)]: Three"]]


@pytest.mark.asyncio
async def test_she_writes_to_a_hive_queen_and_her_answer_comes_back_to_the_conversation(manager, mail, fake):
    _queue_replies(fake, "Let me ask Ivy.", "Ivy says the east shore is unmapped.")
    ava = await manager.create_session(queen_name=AVA)
    await mail.send(ava, CLAUDE, "Is the east shore mapped?")
    await _until(lambda: len(_told(ava)) == 1)
    conversation = _log()[0]["to_session"]

    await mail.send_from_conversation(conversation, IVY, "Have you mapped the east shore?")
    [ivy_session] = [d.name for d in queen_sessions_dir(IVY).iterdir() if d.is_dir()]
    await _say(
        manager.get_session(ivy_session).event_bus,
        (EventType.CLIENT_OUTPUT_DELTA, {"snapshot": "Not yet."}),
        (EventType.LLM_TURN_COMPLETE, {"stop_reason": "stop"}),
    )
    await _until(lambda: len(_told(ava)) == 2)

    assert _runs(fake)[1]["prompt"].splitlines()[-1] == "[Ivy(queen_ivy)]: Not yet."
    assert _told(ava)[1] == "[Claude(queen_claude)]: Ivy says the east shore is unmapped."
    # A hop is logged once its delivery returns, a moment after the queen is handed the words.
    await _until(lambda: len(_log()) == 5)
    hops = [(h["kind"], h["from"], h["to"], h["depth"]) for h in _log()]
    assert hops == [
        ("message", AVA, CLAUDE, 1),
        ("reply", CLAUDE, AVA, 2),
        ("message", CLAUDE, IVY, 2),
        ("reply", IVY, CLAUDE, 3),
        ("reply", CLAUDE, AVA, 4),
    ]


@pytest.mark.asyncio
async def test_a_failed_turn_tells_the_writer(manager, mail, fake):
    _queue_replies(fake, "ERROR:Not logged in · Please run /login")
    ava = await manager.create_session(queen_name=AVA)

    await mail.send(ava, CLAUDE, "Hello?")
    await _until(lambda: _told(ava))

    assert _told(ava) == ["[Claude(queen_claude)]: (Her reply failed: Not logged in · Please run /login)"]


@pytest.mark.asyncio
async def test_a_turn_that_runs_out_of_time_tells_the_writer(manager, mail, monkeypatch):
    def too_slow(args, prompt, cwd, env, timeout):
        raise subprocess.TimeoutExpired(args, timeout)

    monkeypatch.setattr(mail.claude_code, "_run", too_slow)
    ava = await manager.create_session(queen_name=AVA)

    await mail.send(ava, CLAUDE, "Hello?")
    await _until(lambda: _told(ava))

    assert _told(ava) == ["[Claude(queen_claude)]: (Her reply failed: her turn ran out of time after 30 min)"]


@pytest.mark.asyncio
async def test_her_runs_use_her_api_key_and_get_the_hive_mcp_server(manager, mail, fake, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-key-that-isnt-hers")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://some-other-gateway.invalid")
    ava = await manager.create_session(queen_name=AVA)

    await mail.send(ava, CLAUDE, "Hello?")
    await _until(lambda: _told(ava))

    [run] = _runs(fake)
    home = hive_config.HIVE_HOME / "claude_code" / CLAUDE
    assert run["env"] == {"CLAUDE_CONFIG_DIR": str(home / "config"), "ANTHROPIC_API_KEY": API_KEY, "ANTHROPIC_BASE_URL": None}
    assert run["cwd"] == str(home / "workspace")
    args = run["args"]
    assert args[args.index("--permission-mode") + 1] == "default"
    assert "--strict-mcp-config" in args and "--append-system-prompt" in args
    assert args[args.index("--allowedTools") + 1 : args.index("--allowedTools") + 3] == list(claude_code_queens.MCP_TOOLS)
    mcp = run["mcp"]["mcpServers"]["hive"]
    conversation = _log()[0]["to_session"]
    assert (mcp["command"], mcp["args"]) == (sys.executable, ["-m", "framework.server.queen_mail_mcp"])
    assert mcp["env"] == {
        "HIVE_QUEEN_MAIL_URL": "http://127.0.0.1:9",
        "HIVE_QUEEN_MAIL_TOKEN": mail.token_for(conversation),
        "HIVE_QUEEN_MAIL_FROM": conversation,
    }
    assert not os.path.exists(args[args.index("--mcp-config") + 1])  # gone once the run ends


@pytest.mark.asyncio
async def test_with_full_permissions_the_mcp_tools_need_no_allowlist(manager, mail, fake, monkeypatch):
    _configure(monkeypatch, fake, permission_mode="bypassPermissions")
    ava = await manager.create_session(queen_name=AVA)

    await mail.send(ava, CLAUDE, "Hello?")
    await _until(lambda: _told(ava))

    [run] = _runs(fake)
    assert run["args"][run["args"].index("--permission-mode") + 1] == "bypassPermissions"
    assert "--allowedTools" not in run["args"]


@pytest.mark.asyncio
async def test_the_routes_want_the_token_and_one_of_her_conversations(monkeypatch, fake):
    _configure(monkeypatch, fake)
    app = create_app()
    manager = app["manager"]
    manager.create_session = committing_session_factory(manager)

    async with TestClient(TestServer(app)) as client:
        mail = manager.queen_mail
        ava = await manager.create_session(queen_name=AVA)
        await mail.send(ava, CLAUDE, "Hello?")
        await _until(lambda: _told(ava))
        conversation = _log()[0]["to_session"]
        token = {"X-Queen-Mail-Token": mail.token_for(conversation)}

        no_token = await client.get("/api/queen-mail/queens", params={"from": conversation})
        posing_as_ava = await client.post("/api/queen-mail/letters", headers=token, json={"from": ava.id, "to": IVY, "message": "Hi"})
        posing_as_another = await client.post(
            "/api/queen-mail/letters", headers=token, json={"from": "claude_code:queen_claude:another", "to": IVY, "message": "Hi"}
        )
        queens = await (await client.get("/api/queen-mail/queens", headers=token, params={"from": conversation})).json()
        letter = await client.post("/api/queen-mail/letters", headers=token, json={"from": conversation, "to": IVY, "message": "Hi"})

        assert no_token.status == 401
        assert posing_as_ava.status == 401 and posing_as_another.status == 401
        assert queens == {"queens": [{"id": AVA, "name": "Ava", "title": "Cartographer"}, {"id": IVY, "name": "Ivy", "title": "Cartographer"}]}
        assert (letter.status, (await letter.json())["to"]) == (200, IVY)


def test_a_claude_code_queen_takes_part_whatever_queens_says(monkeypatch, fake):
    _configure(monkeypatch, fake, title="Engineer", timeout_minutes=5)

    config = get_queen_mail_config()

    assert config.includes(CLAUDE) and not config.includes("queen_zed")
    entry = config.claude_code[CLAUDE]
    assert (entry.name, entry.title, entry.timeout_minutes, entry.permission_mode) == ("Claude", "Engineer", 5, "default")


# --- the MCP server her runs get --------------------------------------------


class _Response:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_mcp_server_writes_through_hive_with_the_token(monkeypatch):
    monkeypatch.setenv("HIVE_QUEEN_MAIL_URL", "http://127.0.0.1:9/")
    monkeypatch.setenv("HIVE_QUEEN_MAIL_TOKEN", "t0ken")
    monkeypatch.setenv("HIVE_QUEEN_MAIL_FROM", "claude_code:queen_claude:abc")
    seen = []

    def urlopen(request, timeout):
        seen.append(request)
        return _Response({"sent": "hop_1", "to": IVY, "depth": 1})

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert json.loads(queen_mail_mcp.message_queen(IVY, "Hi")) == {"sent": "hop_1", "to": IVY, "depth": 1}
    [request] = seen
    assert (request.full_url, request.get_method(), request.get_header("X-queen-mail-token")) == (
        "http://127.0.0.1:9/api/queen-mail/letters",
        "POST",
        "t0ken",
    )
    assert json.loads(request.data) == {"from": "claude_code:queen_claude:abc", "to": IVY, "message": "Hi"}


def test_the_mcp_server_passes_hives_refusal_on(monkeypatch):
    monkeypatch.setenv("HIVE_QUEEN_MAIL_URL", "http://127.0.0.1:9")

    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, _Response({"error": "That's your own id"}))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert json.loads(queen_mail_mcp.list_queens()) == {"error": "That's your own id"}


# --- the dashboard's read-only view ------------------------------------------

SESSION_LINES = [
    {"type": "user", "timestamp": "2026-10-25T10:00:00Z", "message": {"role": "user", "content": "[Ava(queen_ava)]: Where is the north shore?"}},
    {"type": "user", "isMeta": True, "timestamp": "2026-10-25T10:00:00Z", "message": {"role": "user", "content": "caveat"}},
    {"type": "attachment", "timestamp": "2026-10-25T10:00:00Z"},
    {
        "type": "assistant",
        "timestamp": "2026-10-25T10:00:01Z",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "Maybe the atlas."},
                {"type": "text", "text": "Let me look."},
                {"type": "tool_use", "name": "Bash", "input": {"command": "ls maps"}},
            ],
        },
    },
    {
        "type": "user",
        "timestamp": "2026-10-25T10:00:02Z",
        "message": {"role": "user", "content": [{"type": "tool_result", "content": "north.txt", "is_error": False}]},
    },
    {
        "type": "assistant",
        "isSidechain": True,
        "timestamp": "2026-10-25T10:00:03Z",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "subagent chatter"}]},
    },
    {
        "type": "assistant",
        "timestamp": "2026-10-25T10:00:04Z",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "It is at 61°N."}]},
    },
]


@pytest.mark.asyncio
async def test_the_dashboard_lists_her_conversations_and_reads_one(monkeypatch, fake):
    _configure(monkeypatch, fake)
    app = create_app()
    manager = app["manager"]
    manager.create_session = committing_session_factory(manager)

    async with TestClient(TestServer(app)) as client:
        ava = await manager.create_session(queen_name=AVA)
        await manager.queen_mail.send(ava, CLAUDE, "Where is the north shore?")
        await _until(lambda: _told(ava))
        session_id = _log()[0]["to_session"].rsplit(":", 1)[1]
        project = hive_config.HIVE_HOME / "claude_code" / CLAUDE / "config" / "projects" / "some-project"
        project.mkdir(parents=True)
        (project / f"{session_id}.jsonl").write_text("\n".join(json.dumps(line) for line in SESSION_LINES), encoding="utf-8")

        listed = await (await client.get("/api/claude-code-queens")).json()
        transcript = await (await client.get(f"/api/claude-code-queens/{CLAUDE}/conversations/{session_id}")).json()
        unknown = await client.get(f"/api/claude-code-queens/{CLAUDE}/conversations/no-such-session")

    [queen] = listed["queens"]
    assert (queen["id"], queen["name"], queen["permission_mode"], queen["auth"]) == (CLAUDE, "Claude", "default", "api_key")
    assert API_KEY not in json.dumps(listed)
    assert queen["conversations"] == [
        {"session_id": session_id, "peer": AVA, "peer_name": "Ava", "running": False, "letters": 1, "last_at": "2026-10-25T10:00:04Z"}
    ]
    assert [(e["kind"], e.get("tool"), e["text"]) for e in transcript["entries"]] == [
        ("letter", None, "[Ava(queen_ava)]: Where is the north shore?"),
        ("text", None, "Let me look."),
        ("tool", "Bash", '{"command": "ls maps"}'),
        ("result", None, "north.txt"),
        ("text", None, "It is at 61°N."),
    ]
    assert unknown.status == 404


def test_message_queen_names_who_she_can_write_to(manager, mail):
    from framework.loader.tool_registry import ToolRegistry
    from framework.tools.queen_mail_tools import register_queen_mail_tools

    manager.queen_mail = mail
    registry = ToolRegistry()
    register_queen_mail_tools(registry, SimpleNamespace(queen_name=AVA), manager)

    [tool] = [t for t in registry.get_tools().values() if t.name == "message_queen"]
    assert tool.description.endswith(" Queens you can write to: Ivy (queen_ivy, Cartographer); Claude (queen_claude, Claude Code).")


# --- how she pays -------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_gateway_in_front_of_the_api_is_her_base_url(manager, mail, fake, monkeypatch):
    _configure(monkeypatch, fake, api_base="https://gateway.example.invalid")
    ava = await manager.create_session(queen_name=AVA)

    await mail.send(ava, CLAUDE, "Hello?")
    await _until(lambda: _told(ava))

    [run] = _runs(fake)
    assert (run["env"]["ANTHROPIC_API_KEY"], run["env"]["ANTHROPIC_BASE_URL"]) == (API_KEY, "https://gateway.example.invalid")


@pytest.mark.asyncio
async def test_without_an_api_key_she_doesnt_run_and_the_writer_is_told_why(manager, mail, fake, monkeypatch):
    _configure(monkeypatch, fake, api_key=None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-key-that-isnt-hers")
    ava = await manager.create_session(queen_name=AVA)

    await mail.send(ava, CLAUDE, "Hello?")
    await _until(lambda: _told(ava))

    assert _runs(fake) == []
    assert _told(ava)[0].startswith("[Claude(queen_claude)]: (Her reply failed: she has no API key.")


@pytest.mark.asyncio
async def test_a_subscription_is_used_only_when_chosen_and_the_risk_is_logged_once(manager, mail, fake, monkeypatch, caplog):
    _configure(monkeypatch, fake, api_key=None, auth="subscription")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-key-that-isnt-hers")
    ava = await manager.create_session(queen_name=AVA)

    with caplog.at_level("WARNING", logger="framework.server.claude_code_queens"):
        await mail.send(ava, CLAUDE, "One")
        await _until(lambda: len(_told(ava)) == 1)
        await mail.send(ava, CLAUDE, "Two")
        await _until(lambda: len(_told(ava)) == 2)

    home = hive_config.HIVE_HOME / "claude_code" / CLAUDE
    assert [run["env"] for run in _runs(fake)] == [
        {"CLAUDE_CONFIG_DIR": str(home / "config"), "ANTHROPIC_API_KEY": None, "ANTHROPIC_BASE_URL": None}
    ] * 2
    warnings = [r.getMessage() for r in caplog.records if "at your own risk" in r.getMessage()]
    assert len(warnings) == 1 and "queen_claude runs on the Claude subscription" in warnings[0]


def test_her_api_key_stays_out_of_her_configs_repr(monkeypatch, fake):
    _configure(monkeypatch, fake)

    entry = get_queen_mail_config().claude_code[CLAUDE]

    assert (entry.auth, entry.api_key) == ("api_key", API_KEY)
    assert API_KEY not in repr(entry)


@pytest.mark.parametrize(
    ("lost_or_taken", "flags"),
    [("LOST", ["--session-id", "--resume", "--session-id"]), ("TAKEN", ["--session-id", "--resume"])],
)
@pytest.mark.asyncio
async def test_a_wrong_record_of_her_session_is_corrected_and_the_turn_tried_again(manager, mail, fake, lost_or_taken, flags):
    ava = await manager.create_session(queen_name=AVA)
    if lost_or_taken == "LOST":
        # Her first turn succeeds; then her session file is gone, so resuming finds nothing.
        _queue_replies(fake, "One.", "LOST", "Two.")
        await mail.send(ava, CLAUDE, "One")
        await _until(lambda: len(_told(ava)) == 1)
    else:
        # Hive stopped before noting the session began: starting it again collides.
        _queue_replies(fake, "TAKEN", "Two.")
    await mail.send(ava, CLAUDE, "Two")
    await _until(lambda: _told(ava)[-1:] == ["[Claude(queen_claude)]: Two."])

    used = [next(a for a in run["args"] if a in ("--session-id", "--resume")) for run in _runs(fake)]
    assert used == flags


# --- what her runs can reach, and stopping them ---------------------------------


@pytest.mark.asyncio
async def test_her_runs_get_none_of_hives_secrets(manager, mail, fake, monkeypatch):
    monkeypatch.setenv("HIVE_CREDENTIAL_KEY", "hive-master-key-0000")
    ava = await manager.create_session(queen_name=AVA)

    await mail.send(ava, CLAUDE, "Hello?")
    await _until(lambda: _told(ava))

    assert _runs(fake)[0]["secret"] is None


@pytest.mark.asyncio
async def test_an_answer_that_happens_to_say_already_in_use_is_kept(manager, mail, fake):
    _queue_replies(fake, "Port 8080 is already in use, so I picked 8081.")
    ava = await manager.create_session(queen_name=AVA)

    await mail.send(ava, CLAUDE, "Start the server.")
    await _until(lambda: _told(ava))

    assert len(_runs(fake)) == 1
    assert _told(ava) == ["[Claude(queen_claude)]: Port 8080 is already in use, so I picked 8081."]


@pytest.mark.asyncio
async def test_closing_kills_a_running_turn(manager, mail, fake, monkeypatch):
    _configure(monkeypatch, fake, env={"FAKE_CLAUDE_SLEEP": "60"})
    ava = await manager.create_session(queen_name=AVA)
    await mail.send(ava, CLAUDE, "Take your time.")
    await _until(lambda: fake["record"].exists() and mail.claude_code._procs)

    mail.close()

    await _until(lambda: not mail.claude_code._procs, seconds=20)
    assert _told(ava) == []
