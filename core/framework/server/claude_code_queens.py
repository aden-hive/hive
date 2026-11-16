"""Queens run by Claude Code, taking part in queen mail.

Each is configured under ``queen_mail.claude_code.<id>`` (:class:`framework.config.ClaudeCodeQueenConfig`).
A letter to her runs a turn of Claude Code in a conversation of hers kept for its writer: started with
``--session-id`` and resumed with ``--resume`` from then on, so she remembers each correspondent. Input
that arrives while a turn runs waits, and goes in together as the next turn. What the turn ends with
goes back the way a Hive queen's words do (:meth:`QueenMail.deliver_reply`): to the session of the
newest letter it answers, or the writer's latest one.

She writes to other queens with the ``hive`` MCP server each run is given
(:mod:`framework.server.queen_mail_mcp`), which calls back into ``hive serve`` with a token good for
that conversation alone. A conversation is named ``claude_code:<queen id>:<Claude Code session id>``
in letters and in ``queens/mail.jsonl``; its writer and route are kept in
``HIVE_HOME/claude_code/<queen id>/conversations.json``.

She pays with an Anthropic API key (``api_key``). A Claude plan signed in in her config folder works
too, but only when chosen in so many words (``"auth": "subscription"``): running a plan unattended for
other agents may break its terms, and that is the user's own risk.

Her runs see only an allowlist of Hive's environment (paths, locale, proxies): none of Hive's own
secrets, keys or tokens. At most ``queen_mail.max_parallel_turns`` turns run at once, each in its own
process tree, which is killed when the turn runs out of time or the server stops.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.config import ClaudeCodeQueenConfig
    from framework.server.queen_mail import QueenMail

logger = logging.getLogger(__name__)

REF_PREFIX = "claude_code:"
#: The tools of the ``hive`` MCP server, as Claude Code names them.
MCP_TOOLS = ("mcp__hive__list_queens", "mcp__hive__message_queen")
# What her runs inherit from Hive's environment: what a program needs to run and reach the network,
# nothing that signs in (Hive's credential key, provider keys, cloud credentials, tokens).
_INHERITED = frozenset(
    {
        "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "OS",
        "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
        "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
        "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
        "USERNAME", "USERDOMAIN", "USER", "LOGNAME", "SHELL", "TERM", "LANG", "LANGUAGE", "TZ",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    }
)  # fmt: skip
_INHERITED_PREFIXES = ("LC_", "XDG_")
_WINDOWS = os.name == "nt"


def is_conversation_ref(ref: str) -> bool:
    return ref.startswith(REF_PREFIX)


def conversation_ref(queen_id: str, session_id: str) -> str:
    return f"{REF_PREFIX}{queen_id}:{session_id}"


@dataclass
class _Input:
    text: str
    hop: str
    depth: int
    #: For a letter: the writer's session it came from, where her answer goes.
    reply_to: str | None = None


@dataclass
class _Conversation:
    queen_id: str
    session_id: str
    #: The queen this conversation is with.
    peer: str
    #: Where what she says goes when no letter in the turn says otherwise: the writer's latest session.
    reply_to: str
    started: bool = False
    queue: list[_Input] = field(default_factory=list)
    #: The turn running now, or the last one: (the newest input's hop, the deepest input's depth).
    cause: tuple[str, int] | None = None
    worker: asyncio.Task[None] | None = None

    @property
    def ref(self) -> str:
        return conversation_ref(self.queen_id, self.session_id)


class ClaudeCodeQueens:
    """The Claude Code queens of one server, and their conversations. Lives on ``QueenMail.claude_code``."""

    def __init__(self, mail: QueenMail) -> None:
        self._mail = mail
        self._loaded: set[str] = set()
        self._conversations: dict[str, _Conversation] = {}
        # Queens on a subscription already warned about in this server's log.
        self._warned: set[str] = set()
        self._executor: ThreadPoolExecutor | None = None
        self._procs: set[subprocess.Popen[str]] = set()
        self._procs_lock = threading.Lock()
        self._closed = False

    def letter(self, queen_id: str, writer: str, reply_to: str, text: str, hop: str, depth: int) -> str:
        """Hand a letter from ``writer`` to ``queen_id``, in her conversation with ``writer``; returns its ref.

        Her answer goes to ``reply_to``.
        """
        self._load(queen_id)
        conversation = next((c for c in self._conversations.values() if c.queen_id == queen_id and c.peer == writer), None)
        if conversation is None:
            conversation = _Conversation(queen_id, str(uuid.uuid4()), writer, reply_to)
            self._conversations[conversation.ref] = conversation
        conversation.reply_to = reply_to
        self._save(queen_id)
        self._take(conversation, _Input(text, hop, depth, reply_to))
        return conversation.ref

    def reply(self, ref: str, text: str, hop: str, depth: int) -> bool:
        """Hand a reply to one of her letters into the conversation ``ref`` she wrote it from."""
        conversation = self._find(ref)
        if conversation is None:
            return False
        self._take(conversation, _Input(text, hop, depth))
        return True

    def queen_of(self, ref: str) -> str | None:
        """The queen whose conversation ``ref`` is, while she is configured."""
        conversation = self._find(ref)
        return conversation.queen_id if conversation is not None else None

    def cause_of(self, ref: str) -> tuple[str, int] | None:
        """What set off the turn now running in ``ref`` (what a letter she writes in it follows)."""
        conversation = self._find(ref)
        return conversation.cause if conversation is not None else None

    def close(self) -> None:
        """Stop: no more turns, and the running ones' process trees are killed."""
        self._closed = True
        for conversation in self._conversations.values():
            if conversation.worker is not None:
                conversation.worker.cancel()
        with self._procs_lock:
            running = list(self._procs)
        for proc in running:
            _kill_tree(proc)
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    async def conversations(self, queen_id: str) -> list[dict[str, Any]]:
        """Her conversations, newest activity first: who each is with, and how far it has come."""
        config = _config(queen_id)
        if config is None:
            return []
        self._load(queen_id)
        mine = [c for c in self._conversations.values() if c.queen_id == queen_id]
        files = {c.session_id: _session_file(config, c.session_id) for c in mine}
        read = await asyncio.to_thread(lambda: {sid: _read_transcript(path) if path else [] for sid, path in files.items()})
        found = [
            {
                "session_id": c.session_id,
                "peer": c.peer,
                "peer_name": self._mail.name_of(c.peer),
                "running": c.worker is not None and not c.worker.done(),
                "letters": sum(1 for e in read[c.session_id] if e["kind"] == "letter"),
                "last_at": read[c.session_id][-1]["at"] if read[c.session_id] else None,
            }
            for c in mine
        ]
        return sorted(found, key=lambda c: c["last_at"] or "", reverse=True)

    async def transcript(self, queen_id: str, session_id: str) -> list[dict[str, Any]] | None:
        """What was said and done in one conversation of hers, from Claude Code's session file; None if unknown."""
        config = _config(queen_id)
        if config is None:
            return None
        self._load(queen_id)
        if conversation_ref(queen_id, session_id) not in self._conversations:
            return None
        path = _session_file(config, session_id)
        return await asyncio.to_thread(_read_transcript, path) if path else []

    # ------------------------------------------------------------------

    def _find(self, ref: str) -> _Conversation | None:
        if not is_conversation_ref(ref):
            return None
        queen_id = ref[len(REF_PREFIX) :].rsplit(":", 1)[0]
        if _config(queen_id) is None:
            return None
        self._load(queen_id)
        return self._conversations.get(ref)

    def _take(self, conversation: _Conversation, item: _Input) -> None:
        conversation.queue.append(item)
        if not self._closed and (conversation.worker is None or conversation.worker.done()):
            conversation.worker = asyncio.create_task(self._work(conversation), name=f"claude-code-{conversation.ref}")

    async def _work(self, conversation: _Conversation) -> None:
        """Run her turns until nothing waits; what came in during a turn goes in together as the next."""
        while conversation.queue and not self._closed:
            batch, conversation.queue = conversation.queue, []
            conversation.cause = (batch[-1].hop, max(item.depth for item in batch))
            letters = [item for item in batch if item.reply_to]
            route = letters[-1].reply_to if letters else conversation.reply_to
            text = await self._turn(conversation, "\n\n".join(item.text for item in batch))
            if text:
                try:
                    await self._mail.deliver_reply(conversation.queen_id, conversation.peer, route, text, conversation.cause, conversation.ref)
                except Exception:
                    logger.exception("claude code queen: couldn't deliver what %s said", conversation.queen_id)

    async def _turn(self, conversation: _Conversation, prompt: str) -> str:
        """Run one turn of hers on ``prompt``; what she ended it with, or why it failed."""
        config = _config(conversation.queen_id)
        if config is None:
            logger.warning(
                "claude code queen %s is no longer in queen_mail.claude_code; what %s wrote to her waits unanswered",
                conversation.queen_id,
                conversation.peer,
            )
            return ""
        env = self._env(config)
        if env is None:
            return (
                f"(Her reply failed: she has no API key. Set queen_mail.claude_code.{conversation.queen_id}.api_key "
                'in configuration.json, or "auth": "subscription" to use a Claude plan signed in at your own risk.)'
            )
        home = _home(conversation.queen_id)
        cwd = Path(config.cwd) if config.cwd else home / "workspace"
        cwd.mkdir(parents=True, exist_ok=True)
        mcp_config = self._mcp_config(conversation, home)
        try:
            for attempt in (1, 2):
                try:
                    code, out, err = await asyncio.get_running_loop().run_in_executor(
                        self._pool(),
                        self._run,
                        self._args(config, conversation, mcp_config),
                        prompt,
                        cwd,
                        env,
                        config.timeout_minutes * 60,
                    )
                except subprocess.TimeoutExpired:
                    return f"(Her reply failed: her turn ran out of time after {config.timeout_minutes} min)"
                except OSError as e:
                    return f"(Her reply failed: Claude Code couldn't start: {e})"
                result = _parse_result(out)
                # Our record of whether the session exists can be wrong: its file was deleted (resuming
                # finds nothing), or Hive stopped mid-turn before noting it began (starting it collides).
                # Claude Code then exits with an error and no result; correct the record and try once more.
                if result is None and code != 0 and attempt == 1:
                    if conversation.started and "No conversation found" in err:
                        conversation.started = False
                        self._save(conversation.queen_id)
                        continue
                    if not conversation.started and "already in use" in err:
                        conversation.started = True
                        self._save(conversation.queen_id)
                        continue
                break
        finally:
            if mcp_config is not None:
                mcp_config.unlink(missing_ok=True)
        if result is None:
            tail = (err or out or "").strip()[-500:]
            return f"(Her reply failed: Claude Code ended with {code}: {tail})"
        if not result.get("is_error") or result.get("num_turns"):
            # The session exists now; from here on it is resumed.
            conversation.started = True
            self._save(conversation.queen_id)
        if result.get("is_error"):
            return f"(Her reply failed: {result.get('result') or result.get('subtype') or 'error'})"
        return str(result.get("result") or "").strip()

    def _pool(self) -> ThreadPoolExecutor:
        """Her turns' own threads (Hive's shared pool stays free), as many as may run at once."""
        if self._executor is None:
            from framework.config import get_queen_mail_config

            workers = get_queen_mail_config().max_parallel_turns
            self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="claude-code-turn")
        return self._executor

    def _run(self, args: list[str], prompt: str, cwd: Path, env: dict[str, str], timeout: float) -> tuple[int, str, str]:
        """Run Claude Code to the end (in a thread): its exit code, stdout and stderr."""
        if _WINDOWS:
            spawn: dict[str, Any] = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
        else:
            spawn = {"start_new_session": True}
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            env=env,
            **spawn,
        )
        with self._procs_lock:
            self._procs.add(proc)
        try:
            out, err = proc.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            try:
                proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            raise
        finally:
            with self._procs_lock:
                self._procs.discard(proc)
        return proc.returncode, out or "", err or ""

    def _env(self, config: ClaudeCodeQueenConfig) -> dict[str, str] | None:
        """The environment of her runs; None when she should pay with an API key and has none."""
        env = {k: v for k, v in os.environ.items() if k.upper() in _INHERITED or k.upper().startswith(_INHERITED_PREFIXES)}
        env["CLAUDE_CONFIG_DIR"] = config.config_dir or str(_home(config.queen_id) / "config")
        if config.auth == "subscription":
            if config.queen_id not in self._warned:
                self._warned.add(config.queen_id)
                logger.warning(
                    "claude code queen %s runs on the Claude subscription signed in at %s. Running a plan unattended "
                    "for other agents may break its terms; that is at your own risk. An API key is the supported way.",
                    config.queen_id,
                    env["CLAUDE_CONFIG_DIR"],
                )
        elif config.api_key:
            env["ANTHROPIC_API_KEY"] = config.api_key
            if config.api_base:
                env["ANTHROPIC_BASE_URL"] = config.api_base
        else:
            return None
        env.update(dict(config.env))
        return env

    def _args(self, config: ClaudeCodeQueenConfig, conversation: _Conversation, mcp_config: Path | None) -> list[str]:
        # On Windows a bare "claude" may be claude.cmd, which CreateProcess won't find by itself.
        program, *rest = config.command
        args = [shutil.which(program) or program, *rest, "-p", "--output-format", "json"]
        args += ["--resume", conversation.session_id] if conversation.started else ["--session-id", conversation.session_id]
        args += ["--permission-mode", config.permission_mode]
        allowed = list(config.allowed_tools)
        if mcp_config is not None:
            args += ["--mcp-config", str(mcp_config), "--strict-mcp-config"]
            if config.permission_mode != "bypassPermissions":
                allowed += [tool for tool in MCP_TOOLS if tool not in allowed]
        if allowed:
            args += ["--allowedTools", *allowed]
        if config.disallowed_tools:
            args += ["--disallowedTools", *config.disallowed_tools]
        if config.add_dirs:
            args += ["--add-dir", *config.add_dirs]
        if config.model:
            args += ["--model", config.model]
        note = _system_prompt(config.name)
        args += ["--append-system-prompt", f"{note}\n\n{config.system_prompt}" if config.system_prompt else note]
        return args

    def _mcp_config(self, conversation: _Conversation, home: Path) -> Path | None:
        """The MCP config that gives this run the ``hive`` server; None while Hive has no address.

        It holds a token good for this conversation alone, is readable by its owner only, and is
        deleted when the run ends.
        """
        if self._mail.base_url is None:
            logger.warning("claude code queen: no server address yet, so %s can't write letters this turn", conversation.queen_id)
            return None
        env = {
            "HIVE_QUEEN_MAIL_URL": self._mail.base_url,
            "HIVE_QUEEN_MAIL_TOKEN": self._mail.token_for(conversation.ref),
            "HIVE_QUEEN_MAIL_FROM": conversation.ref,
        }
        server = {"type": "stdio", "command": sys.executable, "args": ["-m", "framework.server.queen_mail_mcp"], "env": env}
        path = home / "mcp" / f"{conversation.session_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"mcpServers": {"hive": server}}, ensure_ascii=False, indent=2))
        return path

    def _load(self, queen_id: str) -> None:
        if queen_id in self._loaded:
            return
        self._loaded.add(queen_id)
        try:
            saved = json.loads((_home(queen_id) / "conversations.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for session_id, entry in (saved.get("conversations") or {}).items() if isinstance(saved, dict) else ():
            if isinstance(entry, dict) and isinstance(entry.get("peer"), str) and isinstance(entry.get("reply_to"), str):
                conversation = _Conversation(queen_id, session_id, entry["peer"], entry["reply_to"], started=entry.get("started") is True)
                self._conversations.setdefault(conversation.ref, conversation)

    def _save(self, queen_id: str) -> None:
        conversations = {
            c.session_id: {"peer": c.peer, "reply_to": c.reply_to, "started": c.started}
            for c in self._conversations.values()
            if c.queen_id == queen_id
        }
        path = _home(queen_id) / "conversations.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"conversations": conversations}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def _config(queen_id: str) -> ClaudeCodeQueenConfig | None:
    from framework.config import get_queen_mail_config

    return get_queen_mail_config().claude_code.get(queen_id)


def _home(queen_id: str) -> Path:
    from framework import config

    return config.HIVE_HOME / "claude_code" / queen_id


def _session_file(config: ClaudeCodeQueenConfig, session_id: str) -> Path | None:
    """Claude Code's file for one of her sessions, under the project folder of wherever it ran."""
    projects = Path(config.config_dir or _home(config.queen_id) / "config") / "projects"
    files = sorted(projects.glob(f"*/{session_id}.jsonl")) if projects.is_dir() else []
    return files[0] if files else None


def _kill_tree(proc: subprocess.Popen[str]) -> None:
    """Kill a run and everything it started (Claude Code's own children, the commands it ran)."""
    try:
        if _WINDOWS:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=30,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def _parse_result(stdout: str) -> dict[str, Any] | None:
    """The result object ``--output-format json`` prints (the last JSON line, should anything precede it)."""
    stdout = (stdout or "").strip()
    try:
        parsed = json.loads(stdout)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    for line in reversed(stdout.splitlines()):
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


#: How much of one tool call's input, and of one tool result, a transcript keeps.
_TOOL_INPUT_CHARS = 600
_TOOL_RESULT_CHARS = 2000


def _read_transcript(path: Path) -> list[dict[str, Any]]:
    """A Claude Code session file as entries the dashboard shows, in order.

    Each entry is ``{"at", "kind", "text"}``, ``kind`` being ``"letter"`` (what she was handed),
    ``"text"`` (what she said), ``"tool"`` (a tool she called, named in ``"tool"``) or ``"result"``
    (what it returned; ``"error"`` when it failed). Her thinking, her subagents' own turns and
    Claude Code's bookkeeping are left out.
    """
    entries: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict) or record.get("type") not in ("user", "assistant"):
                continue
            if record.get("isMeta") or record.get("isSidechain"):
                continue
            message = record.get("message") or {}
            at = str(record.get("timestamp") or "")
            content = message.get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            for part in content if isinstance(content, list) else ():
                if not isinstance(part, dict):
                    continue
                kind = part.get("type")
                if kind == "text" and str(part.get("text") or "").strip():
                    entries.append({"at": at, "kind": "letter" if record["type"] == "user" else "text", "text": part["text"]})
                elif kind == "tool_use":
                    shown = json.dumps(part.get("input"), ensure_ascii=False)
                    entries.append({"at": at, "kind": "tool", "tool": str(part.get("name") or ""), "text": _clip(shown, _TOOL_INPUT_CHARS)})
                elif kind == "tool_result":
                    entries.append(
                        {
                            "at": at,
                            "kind": "result",
                            "text": _clip(_result_text(part.get("content")), _TOOL_RESULT_CHARS),
                            "error": part.get("is_error") is True,
                        }
                    )
    return entries


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text") or "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _system_prompt(name: str) -> str:
    return (
        f"You are {name}, one of the queens of a Hive: agents who write to each other. Other queens write you "
        'letters; each arrives as "[Name(queen_id)]: text", and so does a reply to a letter of yours. What you end '
        "your turn with goes back to the queen this conversation is with, so just answer. To write to a queen "
        "yourself, use list_queens and message_queen (the hive MCP server); her answer comes back later as a new "
        "message in this conversation."
    )
