#!/usr/bin/env python3
"""
Multi-Agent Organization Demo

Demonstrates multiple EventLoopNode agents communicating in arbitrary
directions, simulating a research consultancy organization.

Four agents (Director, Researcher, Analyst, Writer) collaborate via
a send_message tool backed by EventBus + inject_event(). A split-panel
UI shows the chat stream alongside a real-time SVG graph with
active-node glow and message-edge animation.

Usage:
    cd /home/timothy/oss/hive/core
    python demos/org_demo.py

    Then open http://localhost:8767 in your browser.
"""

import asyncio
import json
import logging
import sys
import tempfile
from http import HTTPStatus
from pathlib import Path

import httpx
import websockets
from bs4 import BeautifulSoup
from websockets.http11 import Request, Response

# Add core, tools, and hive root to path
_CORE_DIR = Path(__file__).resolve().parent.parent
_HIVE_DIR = _CORE_DIR.parent
sys.path.insert(0, str(_CORE_DIR))
sys.path.insert(0, str(_HIVE_DIR / "tools" / "src"))
sys.path.insert(0, str(_HIVE_DIR))

import os  # noqa: E402

from aden_tools.credentials import CREDENTIAL_SPECS, CredentialStoreAdapter  # noqa: E402
from core.framework.credentials import CredentialStore  # noqa: E402

from framework.credentials.storage import (  # noqa: E402
    CompositeStorage,
    EncryptedFileStorage,
    EnvVarStorage,
)
from framework.graph.event_loop_node import (  # noqa: E402
    EventLoopNode,
    JudgeVerdict,
    LoopConfig,
)
from framework.graph.node import NodeContext, NodeSpec, SharedMemory  # noqa: E402
from framework.llm.litellm import LiteLLMProvider  # noqa: E402
from framework.llm.provider import Tool, ToolResult, ToolUse  # noqa: E402
from framework.runner.tool_registry import ToolRegistry  # noqa: E402
from framework.runtime.core import Runtime  # noqa: E402
from framework.runtime.event_bus import (  # noqa: E402
    AgentEvent,
    EventBus,
    EventType,
)
from framework.storage.conversation_store import FileConversationStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("org_demo")

# -------------------------------------------------------------------------
# Persistent state
# -------------------------------------------------------------------------

STORE_DIR = Path(tempfile.mkdtemp(prefix="hive_org_"))
RUNTIME = Runtime(STORE_DIR / "runtime")
LLM = LiteLLMProvider(model="claude-haiku-4-5-20251001")

# -------------------------------------------------------------------------
# Credentials
# -------------------------------------------------------------------------

_env_mapping = {name: spec.env_var for name, spec in CREDENTIAL_SPECS.items()}
_local_storage = CompositeStorage(
    primary=EncryptedFileStorage(),
    fallbacks=[EnvVarStorage(env_mapping=_env_mapping)],
)

if os.environ.get("ADEN_API_KEY"):
    try:
        from framework.credentials.aden import (  # noqa: E402
            AdenCachedStorage,
            AdenClientConfig,
            AdenCredentialClient,
            AdenSyncProvider,
        )

        _client = AdenCredentialClient(AdenClientConfig(base_url="https://api.adenhq.com"))
        _provider = AdenSyncProvider(client=_client)
        _storage = AdenCachedStorage(
            local_storage=_local_storage,
            aden_provider=_provider,
        )
        _cred_store = CredentialStore(storage=_storage, providers=[_provider], auto_refresh=True)
        _synced = _provider.sync_all(_cred_store)
        logger.info("Synced %d credentials from Aden", _synced)
    except Exception as e:
        logger.warning("Aden sync unavailable: %s", e)
        _cred_store = CredentialStore(storage=_local_storage)
else:
    logger.info("ADEN_API_KEY not set, using local credential storage")
    _cred_store = CredentialStore(storage=_local_storage)

CREDENTIALS = CredentialStoreAdapter(_cred_store)

# -------------------------------------------------------------------------
# Tool Registry — web_search + web_scrape (for Researcher)
# -------------------------------------------------------------------------

TOOL_REGISTRY = ToolRegistry()


def _exec_web_search(inputs: dict) -> dict:
    api_key = CREDENTIALS.get("brave_search")
    if not api_key:
        return {"error": "brave_search credential not configured"}
    query = inputs.get("query", "")
    num_results = min(inputs.get("num_results", 5), 20)
    resp = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": num_results},
        headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        timeout=30.0,
    )
    if resp.status_code != 200:
        return {"error": f"Brave API HTTP {resp.status_code}"}
    data = resp.json()
    results = [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("description", ""),
        }
        for item in data.get("web", {}).get("results", [])[:num_results]
    ]
    return {"query": query, "results": results, "total": len(results)}


TOOL_REGISTRY.register(
    name="web_search",
    tool=Tool(
        name="web_search",
        description="Search the web for current information. Returns titles, URLs, and snippets.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {"type": "integer", "description": "Results (1-20, default 5)"},
            },
            "required": ["query"],
        },
    ),
    executor=lambda inputs: _exec_web_search(inputs),
)

_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


def _exec_web_scrape(inputs: dict) -> dict:
    url = inputs.get("url", "")
    max_length = max(1000, min(inputs.get("max_length", 50000), 500000))
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        resp = httpx.get(url, timeout=30.0, follow_redirects=True, headers=_SCRAPE_HEADERS)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}"}
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()
        title = soup.title.get_text(strip=True) if soup.title else ""
        main = (
            soup.find("article")
            or soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.find("body")
        )
        text = main.get_text(separator=" ", strip=True) if main else ""
        text = " ".join(text.split())
        if len(text) > max_length:
            text = text[:max_length] + "..."
        return {"url": url, "title": title, "content": text, "length": len(text)}
    except httpx.TimeoutException:
        return {"error": "Request timed out"}
    except Exception as e:
        return {"error": f"Scrape failed: {e}"}


TOOL_REGISTRY.register(
    name="web_scrape",
    tool=Tool(
        name="web_scrape",
        description="Scrape text content from a webpage URL.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to scrape"},
                "max_length": {"type": "integer", "description": "Max text length (default 50000)"},
            },
            "required": ["url"],
        },
    ),
    executor=lambda inputs: _exec_web_scrape(inputs),
)

logger.info("Tools loaded: %s", ", ".join(TOOL_REGISTRY.get_registered_names()))

# -------------------------------------------------------------------------
# Node Specs
# -------------------------------------------------------------------------

ROLES = ["director", "researcher", "analyst", "writer"]

ROLE_SPECS = {
    "director": NodeSpec(
        id="director",
        name="Director",
        description="Coordinates the team and synthesizes the final report",
        node_type="event_loop",
        input_keys=["topic"],
        output_keys=["final_report"],
        system_prompt=(
            "You are the Director of a research consultancy team. "
            "You receive research topics and coordinate your team.\n\n"
            "Your team:\n"
            "- researcher: Web research specialist (has web_search/web_scrape)\n"
            "- analyst: Data analysis and pattern recognition\n"
            "- writer: Technical writer for polished deliverables\n\n"
            "Workflow:\n"
            "1. Break the topic into specific research tasks\n"
            "2. Send tasks to researcher AND analyst via send_message\n"
            "3. Wait for their responses (they will message you back)\n"
            "4. Send all material to writer for drafting\n"
            "5. When writer returns the draft, review it\n"
            "6. Call set_output(key='final_report', value=<the report>)\n\n"
            "IMPORTANT: Delegate, don't do research or writing yourself."
        ),
    ),
    "researcher": NodeSpec(
        id="researcher",
        name="Researcher",
        description="Researches topics using web tools",
        node_type="event_loop",
        system_prompt=(
            "You are a Research Specialist. You receive tasks from the "
            "team and use web_search and web_scrape to gather info.\n\n"
            "When you receive a task:\n"
            "1. Search for relevant information (2-3 searches)\n"
            "2. Scrape 1-2 promising URLs for detail\n"
            "3. Synthesize findings into a clear summary\n"
            "4. Send findings back to whoever asked via send_message\n\n"
            "Be thorough but efficient. Focus on facts and data."
        ),
    ),
    "analyst": NodeSpec(
        id="analyst",
        name="Analyst",
        description="Analyzes data and identifies patterns",
        node_type="event_loop",
        system_prompt=(
            "You are a Data Analyst. You receive data and context from "
            "team members and provide analytical insights.\n\n"
            "When you receive a request:\n"
            "1. Analyze the provided information\n"
            "2. Identify key themes, patterns, and trends\n"
            "3. Assess reliability and significance\n"
            "4. Send analysis back via send_message\n\n"
            "Be concise but insightful."
        ),
    ),
    "writer": NodeSpec(
        id="writer",
        name="Writer",
        description="Drafts polished deliverables",
        node_type="event_loop",
        system_prompt=(
            "You are a Technical Writer. You receive research findings "
            "and analysis from team members and draft polished reports.\n\n"
            "When you receive material:\n"
            "1. Organize information into a logical structure\n"
            "2. Write a clear, professional report with sections\n"
            "3. Include findings, analysis, and recommendations\n"
            "4. Send the draft back to director via send_message\n\n"
            "Write professionally but accessibly."
        ),
    ),
}


def _build_send_tool(role: str) -> Tool:
    """Build a send_message tool with 'to' enum excluding the node itself."""
    targets = [r for r in ROLES if r != role]
    return Tool(
        name="send_message",
        description=(
            "Send a message to another team member. "
            "Use this to delegate tasks, share findings, or return work."
        ),
        parameters={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "enum": targets,
                    "description": f"Team member: {', '.join(targets)}",
                },
                "message": {
                    "type": "string",
                    "description": "The message content",
                },
            },
            "required": ["to", "message"],
        },
    )


# Per-role tool lists
_web_tools = list(TOOL_REGISTRY.get_tools().values())
ROLE_TOOLS: dict[str, list[Tool]] = {}
for _role in ROLES:
    _tools = [_build_send_tool(_role)]
    if _role == "researcher":
        _tools = _web_tools + _tools
    ROLE_TOOLS[_role] = _tools


# -------------------------------------------------------------------------
# OrgJudge — blocks between messages, manages node lifecycle
# -------------------------------------------------------------------------


class OrgJudge:
    """Judge for org demo nodes.

    - Director: blocks until message arrives, ACCEPTs when output_keys filled
    - Specialists: block until message arrives, ACCEPT on done signal
    """

    # Director gets a longer window (waiting for multiple specialist
    # replies); specialists only need to wait for follow-ups.
    _DIRECTOR_TIMEOUT = 120
    _SPECIALIST_TIMEOUT = 30

    def __init__(
        self,
        is_director: bool = False,
        bus: EventBus | None = None,
        node_id: str = "",
    ):
        self._is_director = is_director
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._done = asyncio.Event()
        self._bus = bus
        self._node_id = node_id
        self._timeout = self._DIRECTOR_TIMEOUT if is_director else self._SPECIALIST_TIMEOUT

    async def evaluate(self, context: dict) -> JudgeVerdict:
        if self._done.is_set():
            return JudgeVerdict(action="ACCEPT")

        # Director: accept when final_report is set
        if self._is_director:
            missing = context.get("missing_keys", [])
            if not missing:
                return JudgeVerdict(action="ACCEPT")

        # Signal UI that this node is waiting for a message
        if self._bus:
            await self._bus.publish(
                AgentEvent(
                    type=EventType.CUSTOM,
                    stream_id="org",
                    node_id=self._node_id,
                    data={"custom_type": "node_waiting", "node_id": self._node_id},
                )
            )

        # Block until next message or done
        try:
            await asyncio.wait_for(self._wait_signal(), timeout=self._timeout)
        except TimeoutError:
            logger.info("OrgJudge %s idle timeout (%ds)", self._node_id, self._timeout)
            return JudgeVerdict(action="ACCEPT")

        if self._done.is_set():
            return JudgeVerdict(action="ACCEPT")

        return JudgeVerdict(action="RETRY")

    async def _wait_signal(self):
        """Wait for either a message or done signal."""
        msg_task = asyncio.create_task(self._message_queue.get())
        done_task = asyncio.create_task(self._done.wait())
        try:
            _done, pending = await asyncio.wait(
                {msg_task, done_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
        except Exception:
            msg_task.cancel()
            done_task.cancel()

    def signal_message(self):
        """Signal that a new message has been injected."""
        self._message_queue.put_nowait(True)

    def signal_done(self):
        """Signal global shutdown."""
        self._done.set()
        try:
            self._message_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass


# -------------------------------------------------------------------------
# MessageRouter — routes inter-node messages with lazy start
# -------------------------------------------------------------------------


class MessageRouter:
    """Routes messages between nodes via inject_event + judge signaling."""

    def __init__(self, bus: EventBus):
        self._bus = bus
        self._nodes: dict[str, EventLoopNode] = {}
        self._judges: dict[str, OrgJudge] = {}
        self._contexts: dict[str, NodeContext] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def register(
        self,
        role: str,
        node: EventLoopNode,
        judge: OrgJudge,
        context: NodeContext,
    ):
        self._nodes[role] = node
        self._judges[role] = judge
        self._contexts[role] = context

    def start(self, role: str):
        """Start a node's event loop as a background task."""
        if role not in self._tasks:
            self._tasks[role] = asyncio.create_task(self._nodes[role].execute(self._contexts[role]))
            logger.info(f"Started node: {role}")

    async def send(self, from_id: str, to_id: str, message: str):
        """Send a message from one node to another (lazy start)."""
        if to_id not in self._nodes:
            raise ValueError(f"Unknown target node: {to_id}")

        # Lazy start the target node if not running
        first_start = to_id not in self._tasks
        if first_start:
            self.start(to_id)
            await self._bus.publish(
                AgentEvent(
                    type=EventType.CUSTOM,
                    stream_id="org",
                    node_id=to_id,
                    data={"custom_type": "node_started", "node_id": to_id},
                )
            )

        # Inject message into target's queue
        formatted = f"[Message from {from_id}]: {message}"
        await self._nodes[to_id].inject_event(formatted)
        # Only signal existing nodes — newly started nodes will drain the
        # injection queue on their first iteration, so the signal would be
        # stale by the time the judge sees it (causing a spurious RETRY
        # that leads to an LLM call with no new content → empty stream).
        if not first_start:
            self._judges[to_id].signal_message()

        logger.info(f"Message: {from_id} -> {to_id} ({len(message)} chars)")

        # Emit event for UI edge animation
        await self._bus.publish(
            AgentEvent(
                type=EventType.CUSTOM,
                stream_id="org",
                data={
                    "custom_type": "message_sent",
                    "from": from_id,
                    "to": to_id,
                    "preview": message[:150],
                },
            )
        )

    def shutdown_all(self):
        """Signal all judges to accept and shut down."""
        for judge in self._judges.values():
            judge.signal_done()

    async def wait_all(self, exclude: str = "", timeout: float = 10.0):
        """Wait for all running tasks (except exclude) to finish."""
        remaining = [t for r, t in self._tasks.items() if r != exclude and not t.done()]
        if remaining:
            _done, pending = await asyncio.wait(remaining, timeout=timeout)
            for t in pending:
                t.cancel()

    def total_tokens(self) -> int:
        """Sum tokens across all completed tasks."""
        total = 0
        for t in self._tasks.values():
            if t.done() and not t.cancelled():
                try:
                    total += t.result().tokens_used or 0
                except Exception:
                    pass
        return total


# -------------------------------------------------------------------------
# Tool executor factory
# -------------------------------------------------------------------------


def _recover_send_args(raw: str) -> tuple[str, str]:
    """Try to extract 'to' and 'message' from a malformed JSON string.

    When the LLM produces a very long message value with unescaped
    characters, json.loads fails and we get {"_raw": "..."}.  Regex
    extraction is a best-effort fallback.
    """
    import re

    to = ""
    message = ""
    to_match = re.search(r'"to"\s*:\s*"(\w+)"', raw)
    if to_match:
        to = to_match.group(1)
    # message is typically the longest field; grab everything after the key
    msg_match = re.search(r'"message"\s*:\s*"', raw)
    if msg_match:
        # Take from after the opening quote to the end, strip trailing "}
        start = msg_match.end()
        message = raw[start:].rstrip()
        # Strip trailing close-quote + brace(s) if present
        for suffix in ('"}\n', '"}', '"'):
            if message.endswith(suffix):
                message = message[: -len(suffix)]
                break
    return to, message


def make_executor(role: str, router: MessageRouter, base_executor):
    """Build a tool executor that handles send_message + delegates rest."""

    async def _send_message(tool_use: ToolUse) -> ToolResult:
        to = tool_use.input.get("to", "")
        message = tool_use.input.get("message", "")

        # Recover from malformed JSON (long messages break json.loads)
        if not to and "_raw" in tool_use.input:
            raw = tool_use.input["_raw"]
            to, message = _recover_send_args(raw)
            if to:
                logger.info("Recovered send_message args from raw string: to=%s", to)

        if to == role:
            return ToolResult(
                tool_use_id=tool_use.id,
                content="Cannot send message to yourself.",
                is_error=True,
            )
        if to not in router._nodes:
            valid = [r for r in ROLES if r != role]
            return ToolResult(
                tool_use_id=tool_use.id,
                content=(
                    f"Unknown team member: '{to}'. "
                    f"Valid targets: {', '.join(valid)}. "
                    f"Use send_message with {{'to': '<name>', 'message': '<text>'}}."
                ),
                is_error=True,
            )
        await router.send(role, to, message)
        return ToolResult(
            tool_use_id=tool_use.id,
            content=f"Message delivered to {to}.",
        )

    def executor(tool_use: ToolUse):
        if tool_use.name == "send_message":
            return _send_message(tool_use)  # coroutine, awaited by EventLoopNode
        return base_executor(tool_use)

    return executor


# -------------------------------------------------------------------------
# HTML page (embedded)
# -------------------------------------------------------------------------

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Multi-Agent Org Demo</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'SF Mono', 'Fira Code', monospace;
    background: #0d1117; color: #c9d1d9;
    height: 100vh; display: flex; flex-direction: column;
  }
  header {
    background: #161b22; padding: 10px 20px;
    border-bottom: 1px solid #30363d;
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  }
  header h1 { font-size: 15px; color: #58a6ff; font-weight: 600; }
  .badge {
    font-size: 11px; padding: 2px 8px; border-radius: 10px;
    background: #21262d; color: #484f58;
  }
  .badge.active { font-weight: 600; }
  .badge.director.active { background: #1a3a5c; color: #58a6ff; }
  .badge.researcher.active { background: #3d2b00; color: #d29922; }
  .badge.analyst.active { background: #1a4b2e; color: #3fb950; }
  .badge.writer.active { background: #2d1a4b; color: #bc8cff; }
  .badge.done { background: #1a4b2e; color: #3fb950; }
  .badge.waiting { background: #1c1c1c; color: #6e7681; }
  .main {
    flex: 1; display: flex; overflow: hidden;
  }
  .chat {
    flex: 65; overflow-y: auto; padding: 12px; min-width: 0;
    border-right: 1px solid #30363d;
  }
  .graph-panel {
    flex: 35; display: flex; flex-direction: column;
    padding: 12px; min-width: 280px; background: #0d1117;
  }
  .graph-title {
    font-size: 12px; color: #8b949e; font-weight: 600;
    margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px;
  }
  .graph-svg { flex: 1; width: 100%; }
  .graph-legend {
    font-size: 10px; color: #484f58; margin-top: 8px;
    line-height: 1.6;
  }
  .legend-dot {
    display: inline-block; width: 8px; height: 8px;
    border-radius: 50%; margin-right: 4px; vertical-align: middle;
  }
  .msg {
    margin: 4px 0; padding: 8px 12px; border-radius: 6px;
    line-height: 1.5; white-space: pre-wrap; word-wrap: break-word;
    font-size: 13px; border-left: 3px solid transparent;
  }
  .msg.user { background: #1a3a5c; color: #58a6ff; border-left-color: #58a6ff; }
  .msg.assistant { background: #161b22; color: #c9d1d9; }
  .msg.event {
    background: transparent; color: #8b949e; font-size: 11px;
    padding: 3px 12px;
  }
  .msg.event.tool { border-left-color: #d29922; }
  .msg.event.stall { border-left-color: #f85149; }
  .msg.event.msg-sent { border-left-color: #58a6ff; color: #58a6ff; }
  .msg.event.lifecycle { color: #6e7681; font-style: italic; }
  .msg.event.done { color: #3fb950; }
  .msg.msg-output {
    background: #131820; font-size: 12px; color: #8b949e;
    max-height: 220px; overflow-y: auto; border-left-width: 2px;
  }
  .msg .node-tag {
    font-size: 10px; font-weight: 700; margin-right: 6px;
    text-transform: uppercase; letter-spacing: 0.5px;
  }
  .node-director { border-left-color: #58a6ff; }
  .node-director .node-tag { color: #58a6ff; }
  .node-researcher { border-left-color: #d29922; }
  .node-researcher .node-tag { color: #d29922; }
  .node-analyst { border-left-color: #3fb950; }
  .node-analyst .node-tag { color: #3fb950; }
  .node-writer { border-left-color: #bc8cff; }
  .node-writer .node-tag { color: #bc8cff; }
  .result-banner {
    margin: 12px 0; padding: 14px; border-radius: 8px;
    background: #0a2614; border: 1px solid #3fb950;
  }
  .result-banner h3 {
    color: #3fb950; font-size: 13px; margin-bottom: 8px; text-align: center;
  }
  .result-banner .report {
    color: #c9d1d9; font-size: 12px; line-height: 1.6;
    max-height: 400px; overflow-y: auto; white-space: pre-wrap;
  }
  .result-banner .tokens {
    color: #484f58; font-size: 10px; text-align: center; margin-top: 8px;
  }
  .input-bar {
    padding: 10px 16px; background: #161b22;
    border-top: 1px solid #30363d; display: flex; gap: 8px;
  }
  .input-bar input {
    flex: 1; background: #0d1117; border: 1px solid #30363d;
    color: #c9d1d9; padding: 8px 12px; border-radius: 6px;
    font-family: inherit; font-size: 13px; outline: none;
  }
  .input-bar input:focus { border-color: #58a6ff; }
  .input-bar button {
    background: #238636; color: #fff; border: none;
    padding: 8px 18px; border-radius: 6px; cursor: pointer;
    font-family: inherit; font-weight: 600; font-size: 13px;
  }
  .input-bar button:hover { background: #2ea043; }
  .input-bar button:disabled {
    background: #21262d; color: #484f58; cursor: not-allowed;
  }
  /* SVG graph styles */
  .graph-node rect {
    transition: stroke-width 0.2s, stroke 0.2s;
  }
  .graph-node.active rect { stroke-width: 3; }
  #gnode-director.active rect { stroke: #58a6ff; }
  #gnode-researcher.active rect { stroke: #d29922; }
  #gnode-analyst.active rect { stroke: #3fb950; }
  #gnode-writer.active rect { stroke: #bc8cff; }
  #gnode-director.done rect { stroke: #58a6ff; stroke-width: 2; }
  #gnode-researcher.done rect { stroke: #d29922; stroke-width: 2; }
  #gnode-analyst.done rect { stroke: #3fb950; stroke-width: 2; }
  #gnode-writer.done rect { stroke: #bc8cff; stroke-width: 2; }
  @keyframes edgePulse {
    0% { stroke-opacity: 1; stroke-width: 3; }
    100% { stroke-opacity: 0.3; stroke-width: 1.5; }
  }
  svg line.flash, svg path.flash {
    stroke: #58a6ff !important;
    animation: edgePulse 0.8s ease-out forwards;
  }
  /* Waiting state — marching-ants dashed border */
  .graph-node.waiting rect {
    stroke: #484f58; stroke-width: 2;
    stroke-dasharray: 8 4;
    animation: waitingDash 1.2s linear infinite;
  }
  @keyframes waitingDash {
    to { stroke-dashoffset: -24; }
  }
  /* Badge spinner */
  .badge.waiting::before {
    content: ''; display: inline-block;
    width: 8px; height: 8px;
    border: 1.5px solid #30363d; border-top-color: #6e7681;
    border-radius: 50%; vertical-align: middle; margin-right: 4px;
    animation: badgeSpin 0.7s linear infinite;
  }
  @keyframes badgeSpin {
    to { transform: rotate(360deg); }
  }
  @keyframes nodeGlow {
    0%, 100% { opacity: 0.4; }
    50% { opacity: 0; }
  }
</style>
</head>
<body>
  <header>
    <h1>Multi-Agent Org</h1>
    <span id="badge-director" class="badge director">Director</span>
    <span id="badge-researcher" class="badge researcher">Researcher</span>
    <span id="badge-analyst" class="badge analyst">Analyst</span>
    <span id="badge-writer" class="badge writer">Writer</span>
    <span id="badge-status" class="badge">Idle</span>
  </header>

  <div class="main">
    <div id="chat" class="chat"></div>
    <div class="graph-panel">
      <div class="graph-title">Organization Graph</div>
      <svg class="graph-svg" viewBox="0 0 440 240" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="6"
                  refX="7" refY="3" orient="auto">
            <polygon points="0 0, 8 3, 0 6" fill="#484f58"/>
          </marker>
        </defs>

        <!-- Edges -->
        <line id="edge-director-researcher"
              x1="220" y1="64" x2="75" y2="148"
              stroke="#21262d" stroke-width="1.5" marker-end="url(#arrow)"/>
        <line id="edge-director-analyst"
              x1="220" y1="64" x2="220" y2="148"
              stroke="#21262d" stroke-width="1.5" marker-end="url(#arrow)"/>
        <line id="edge-director-writer"
              x1="220" y1="64" x2="365" y2="148"
              stroke="#21262d" stroke-width="1.5" marker-end="url(#arrow)"/>
        <path id="edge-analyst-researcher"
              d="M 130 172 Q 147 200 165 172"
              stroke="#21262d" stroke-width="1" fill="none"
              stroke-dasharray="4"/>

        <!-- Director -->
        <g id="gnode-director" class="graph-node">
          <rect x="160" y="20" width="120" height="44" rx="8"
                fill="#161b22" stroke="#30363d" stroke-width="2"/>
          <text x="220" y="47" fill="#c9d1d9" text-anchor="middle"
                font-size="12" font-weight="600"
                font-family="SF Mono, Fira Code, monospace">Director</text>
        </g>
        <text id="status-director" x="220" y="80" fill="#484f58"
              text-anchor="middle" font-size="9"
              font-family="SF Mono, Fira Code, monospace">idle</text>

        <!-- Researcher -->
        <g id="gnode-researcher" class="graph-node">
          <rect x="12" y="150" width="116" height="44" rx="8"
                fill="#161b22" stroke="#30363d" stroke-width="2"/>
          <text x="70" y="177" fill="#c9d1d9" text-anchor="middle"
                font-size="11" font-weight="600"
                font-family="SF Mono, Fira Code, monospace">Researcher</text>
        </g>
        <text id="status-researcher" x="70" y="210" fill="#484f58"
              text-anchor="middle" font-size="9"
              font-family="SF Mono, Fira Code, monospace">idle</text>

        <!-- Analyst -->
        <g id="gnode-analyst" class="graph-node">
          <rect x="162" y="150" width="116" height="44" rx="8"
                fill="#161b22" stroke="#30363d" stroke-width="2"/>
          <text x="220" y="177" fill="#c9d1d9" text-anchor="middle"
                font-size="12" font-weight="600"
                font-family="SF Mono, Fira Code, monospace">Analyst</text>
        </g>
        <text id="status-analyst" x="220" y="210" fill="#484f58"
              text-anchor="middle" font-size="9"
              font-family="SF Mono, Fira Code, monospace">idle</text>

        <!-- Writer -->
        <g id="gnode-writer" class="graph-node">
          <rect x="312" y="150" width="116" height="44" rx="8"
                fill="#161b22" stroke="#30363d" stroke-width="2"/>
          <text x="370" y="177" fill="#c9d1d9" text-anchor="middle"
                font-size="12" font-weight="600"
                font-family="SF Mono, Fira Code, monospace">Writer</text>
        </g>
        <text id="status-writer" x="370" y="210" fill="#484f58"
              text-anchor="middle" font-size="9"
              font-family="SF Mono, Fira Code, monospace">idle</text>
      </svg>
      <div class="graph-legend">
        <span class="legend-dot" style="background:#58a6ff"></span>Director
        <span class="legend-dot" style="background:#d29922;margin-left:8px"></span>Researcher
        <span class="legend-dot" style="background:#3fb950;margin-left:8px"></span>Analyst
        <span class="legend-dot" style="background:#bc8cff;margin-left:8px"></span>Writer
      </div>
    </div>
  </div>

  <div class="input-bar">
    <input id="input" type="text"
           placeholder="Enter a research topic..." autofocus />
    <button id="go" onclick="run()">Start</button>
  </div>

<script>
const chat = document.getElementById('chat');
const goBtn = document.getElementById('go');
const inputEl = document.getElementById('input');
const statusBadge = document.getElementById('badge-status');

const nodeColors = {
  director: '#58a6ff', researcher: '#d29922',
  analyst: '#3fb950', writer: '#bc8cff'
};
const nodeLabels = {
  director: 'Director', researcher: 'Researcher',
  analyst: 'Analyst', writer: 'Writer'
};

let ws = null;
const assistantEls = {};
const nodeTimers = {};

inputEl.addEventListener('keydown', e => { if (e.key === 'Enter') run(); });

function setStatus(text, cls) {
  statusBadge.textContent = text;
  statusBadge.className = 'badge ' + (cls || '');
}

function setNodeActive(nodeId, active) {
  const g = document.getElementById('gnode-' + nodeId);
  if (g) {
    if (active) { g.classList.add('active'); g.classList.remove('done','waiting'); }
    else g.classList.remove('active');
  }
  const b = document.getElementById('badge-' + nodeId);
  if (b) {
    b.classList.toggle('active', active);
    if (active) b.classList.remove('waiting', 'done');
  }
}

function setNodeDone(nodeId) {
  const g = document.getElementById('gnode-' + nodeId);
  if (g) { g.classList.remove('active','waiting'); g.classList.add('done'); }
  setNodeStatus(nodeId, 'done');
  const b = document.getElementById('badge-' + nodeId);
  if (b) { b.classList.remove('active','waiting'); b.classList.add('done'); }
}

const spinChars = ['\u280b','\u2819','\u2839','\u2838','\u283c',
  '\u2834','\u2826','\u2827','\u2807','\u280f'];
const spinTimers = {};

function setNodeStatus(nodeId, text) {
  const s = document.getElementById('status-' + nodeId);
  if (!s) return;
  // Clear any running spinner
  if (spinTimers[nodeId]) { clearInterval(spinTimers[nodeId]); delete spinTimers[nodeId]; }
  if (text === 'waiting') {
    let f = 0;
    s.textContent = spinChars[0] + ' waiting';
    spinTimers[nodeId] = setInterval(() => {
      f = (f + 1) % spinChars.length;
      s.textContent = spinChars[f] + ' waiting';
    }, 80);
  } else {
    s.textContent = text;
  }
}

function flashEdge(from, to) {
  const id = 'edge-' + [from, to].sort().join('-');
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('flash');
  void el.offsetWidth;
  el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 900);
}

function activateNode(nodeId, status) {
  setNodeActive(nodeId, true);
  setNodeStatus(nodeId, status || 'thinking');
  // Clear any idle timer — the node is explicitly active
  clearTimeout(nodeTimers[nodeId]);
}

function addMsg(html, cls) {
  const el = document.createElement('div');
  el.className = 'msg ' + cls;
  el.innerHTML = html;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

function addNodeMsg(nodeId, text, cls) {
  const tag = '<span class="node-tag">' + (nodeLabels[nodeId]||nodeId) + '</span>';
  const el = addMsg(tag, 'assistant node-' + nodeId + ' ' + (cls||''));
  const span = document.createElement('span');
  span.className = 'text-content';
  span.textContent = text;
  el.appendChild(span);
  return el;
}

function addEventMsg(nodeId, text, cls) {
  const prefix = nodeId ? ('[' + (nodeLabels[nodeId]||nodeId) + '] ') : '';
  return addMsg(prefix + text, 'event node-' + (nodeId||'system') + ' ' + (cls||''));
}

function connect() {
  ws = new WebSocket('ws://' + location.host + '/ws');
  ws.onopen = () => { setStatus('Ready', 'done'); goBtn.disabled = false; };
  ws.onmessage = handleEvent;
  ws.onerror = () => setStatus('Error', 'error');
  ws.onclose = () => {
    setStatus('Reconnecting...', '');
    goBtn.disabled = true;
    setTimeout(connect, 2000);
  };
}

function handleEvent(msg) {
  const evt = JSON.parse(msg.data);
  const nid = evt.node_id || '';

  // --- Node lifecycle ---
  if (evt.type === 'node_loop_started') {
    activateNode(nid, 'starting');
    addEventMsg(nid, 'joined the team', 'lifecycle');
  }
  else if (evt.type === 'node_loop_iteration') {
    activateNode(nid, 'thinking');
  }
  else if (evt.type === 'node_loop_completed') {
    // Clean up any empty trailing assistant bubble
    if (assistantEls[nid]) {
      var tc = assistantEls[nid].querySelector('.text-content');
      if (tc && !tc.textContent) assistantEls[nid].remove();
      assistantEls[nid] = null;
    }
    setNodeDone(nid);
    var iters = evt.iterations || '?';
    addEventMsg(nid, 'finished (' + iters + ' iterations)', 'lifecycle done');
  }
  else if (evt.type === 'node_started') {
    // Custom event from lazy start
    activateNode(evt.node_id, 'starting');
  }
  else if (evt.type === 'node_waiting') {
    setNodeActive(nid, false);
    setNodeStatus(nid, 'waiting');
    var g = document.getElementById('gnode-' + nid);
    if (g) { g.classList.add('waiting'); }
    var b = document.getElementById('badge-' + nid);
    if (b) { b.classList.remove('active','done'); b.classList.add('waiting'); }
  }
  else if (evt.type === 'node_compaction') {
    var pct = (evt.usage_before || '?') + '% \u2192 ' + (evt.usage_after || '?') + '%';
    addEventMsg(nid, 'context compacted (' + evt.level + ', ' + pct + ')', 'lifecycle');
  }

  // --- LLM streaming ---
  else if (evt.type === 'llm_text_delta') {
    activateNode(nid, 'streaming');
    if (!assistantEls[nid]) {
      assistantEls[nid] = addNodeMsg(nid, '');
    }
    const tc = assistantEls[nid].querySelector('.text-content');
    if (tc) tc.textContent += evt.content;
    chat.scrollTop = chat.scrollHeight;
  }

  // --- Tool calls ---
  else if (evt.type === 'tool_call_started') {
    activateNode(nid, evt.tool_name);
    if (assistantEls[nid]) {
      const tc = assistantEls[nid].querySelector('.text-content');
      if (tc && !tc.textContent) assistantEls[nid].remove();
      assistantEls[nid] = null;
    }
    if (evt.tool_name === 'send_message') {
      var target = '';
      var msgBody = '';
      try { target = evt.tool_input.to || ''; } catch(e) {}
      try { msgBody = evt.tool_input.message || ''; } catch(e) {}
      addEventMsg(nid, '\u2192 ' + (nodeLabels[target] || target), 'msg-sent');
      if (msgBody) {
        var preview = msgBody.length > 600 ? msgBody.slice(0, 600) + '\u2026' : msgBody;
        addNodeMsg(nid, preview, 'msg-output');
      }
    } else {
      var info = evt.tool_name + '(' + JSON.stringify(evt.tool_input).slice(0,100) + ')';
      addEventMsg(nid, 'TOOL ' + info, 'tool');
    }
  }
  else if (evt.type === 'tool_call_completed') {
    if (evt.tool_name !== 'send_message') {
      var preview = (evt.result || '').slice(0, 200);
      var cls = evt.is_error ? 'stall' : 'tool';
      addEventMsg(nid, 'RESULT ' + evt.tool_name + ': ' + preview, cls);
    }
    activateNode(nid, 'thinking');
    assistantEls[nid] = addNodeMsg(nid, '');
  }

  // --- Inter-node messages ---
  else if (evt.type === 'message_sent') {
    flashEdge(evt.from, evt.to);
  }

  // --- Errors & stalls ---
  else if (evt.type === 'node_stalled') {
    addEventMsg(nid, 'STALLED: ' + (evt.reason || ''), 'stall');
  }

  // --- Pipeline done ---
  else if (evt.type === 'org_done') {
    setStatus('Done', 'done');
    for (var r in nodeLabels) {
      setNodeDone(r);
      clearTimeout(nodeTimers[r]);
    }
    // Clean up empty assistant els
    for (var k in assistantEls) {
      if (assistantEls[k]) {
        var tc = assistantEls[k].querySelector('.text-content');
        if (tc && !tc.textContent) assistantEls[k].remove();
        assistantEls[k] = null;
      }
    }
    // Result banner
    var banner = document.createElement('div');
    banner.className = 'result-banner';
    var h3 = document.createElement('h3');
    h3.textContent = 'Pipeline Complete';
    banner.appendChild(h3);
    if (evt.final_report) {
      var report = document.createElement('div');
      report.className = 'report';
      report.textContent = typeof evt.final_report === 'string'
        ? evt.final_report
        : JSON.stringify(evt.final_report, null, 2);
      banner.appendChild(report);
    }
    if (evt.total_tokens) {
      var tok = document.createElement('div');
      tok.className = 'tokens';
      tok.textContent = 'Total tokens: ' + evt.total_tokens.toLocaleString();
      banner.appendChild(tok);
    }
    chat.appendChild(banner);
    chat.scrollTop = chat.scrollHeight;
    goBtn.disabled = false;
    inputEl.placeholder = 'Enter another topic...';
  }
  else if (evt.type === 'error') {
    setStatus('Error', 'error');
    addMsg('ERROR: ' + (evt.message || ''), 'event stall');
    goBtn.disabled = false;
  }
}

function run() {
  const text = inputEl.value.trim();
  if (!text || !ws || ws.readyState !== 1) return;
  chat.innerHTML = '';
  // Reset graph
  for (var r in nodeLabels) {
    var g = document.getElementById('gnode-' + r);
    if (g) { g.classList.remove('active','done'); }
    var s = document.getElementById('status-' + r);
    if (s) s.textContent = 'idle';
    var b = document.getElementById('badge-' + r);
    if (b) { b.classList.remove('active','done','waiting'); }
    assistantEls[r] = null;
  }
  addMsg(text, 'user');
  setStatus('Running', 'active');
  goBtn.disabled = true;
  inputEl.value = '';
  ws.send(JSON.stringify({ topic: text }));
}

connect();
</script>
</body>
</html>"""


# -------------------------------------------------------------------------
# WebSocket handler — org pipeline
# -------------------------------------------------------------------------


async def handle_ws(websocket):
    """Handle WebSocket connections for the org demo."""
    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            topic = msg.get("topic", "")
            if not topic:
                continue

            logger.info(f"Starting org pipeline for: {topic}")

            try:
                await _run_org_pipeline(websocket, topic)
            except websockets.exceptions.ConnectionClosed:
                logger.info("WebSocket closed during pipeline")
                return
            except Exception as e:
                logger.exception("Pipeline error")
                try:
                    await websocket.send(json.dumps({"type": "error", "message": str(e)}))
                except Exception:
                    pass

    except websockets.exceptions.ConnectionClosed:
        pass


async def _run_org_pipeline(websocket, topic: str):
    """Execute the multi-agent org pipeline."""
    import shutil

    run_dir = Path(tempfile.mkdtemp(prefix="hive_run_", dir=STORE_DIR))
    bus = EventBus()

    # Forward bus events to WebSocket
    async def forward_event(event):
        try:
            payload = {"type": event.type.value, **event.data}
            if event.node_id:
                payload["node_id"] = event.node_id
            # Remap CUSTOM events to their custom_type
            if event.type == EventType.CUSTOM and "custom_type" in event.data:
                payload["type"] = event.data["custom_type"]
            await websocket.send(json.dumps(payload))
        except Exception:
            pass

    bus.subscribe(
        event_types=[
            EventType.NODE_LOOP_STARTED,
            EventType.NODE_LOOP_ITERATION,
            EventType.NODE_LOOP_COMPLETED,
            EventType.LLM_TEXT_DELTA,
            EventType.TOOL_CALL_STARTED,
            EventType.TOOL_CALL_COMPLETED,
            EventType.NODE_STALLED,
            EventType.CUSTOM,
        ],
        handler=forward_event,
    )

    # Build router with all nodes
    router = MessageRouter(bus=bus)
    base_executor = TOOL_REGISTRY.get_executor()

    for role in ROLES:
        store = FileConversationStore(run_dir / role)
        judge = OrgJudge(
            is_director=(role == "director"),
            bus=bus,
            node_id=role,
        )
        executor = make_executor(role, router, base_executor)

        node = EventLoopNode(
            event_bus=bus,
            judge=judge,
            config=LoopConfig(
                max_iterations=30,
                max_tool_calls_per_turn=30,
                max_history_tokens=32_000,
            ),
            conversation_store=store,
            tool_executor=executor,
        )

        input_data = {"topic": topic} if role == "director" else {}
        ctx = NodeContext(
            runtime=RUNTIME,
            node_id=role,
            node_spec=ROLE_SPECS[role],
            memory=SharedMemory(),
            input_data=input_data,
            llm=LLM,
            available_tools=ROLE_TOOLS[role],
            max_tokens=64000,
        )

        router.register(role, node, judge, ctx)

    # Start director (specialists start lazily via MessageRouter.send)
    router.start("director")

    # Wait for director to complete (with global timeout)
    try:
        director_result = await asyncio.wait_for(
            router._tasks["director"],
            timeout=600,
        )
    except TimeoutError:
        router.shutdown_all()
        await router.wait_all(timeout=5.0)
        msg = {"type": "error", "message": "Pipeline timed out (10 min)"}
        await websocket.send(json.dumps(msg))
        shutil.rmtree(run_dir, ignore_errors=True)
        return

    logger.info(
        "Director done: success=%s, tokens=%s",
        director_result.success,
        director_result.tokens_used,
    )

    # Shut down all specialist nodes
    router.shutdown_all()
    await router.wait_all(exclude="director", timeout=10.0)

    total_tokens = router.total_tokens()

    # Extract final report
    final_report = director_result.output.get("final_report", "")
    if not final_report and director_result.output:
        final_report = json.dumps(director_result.output, indent=2)

    # Send result to browser
    if director_result.success:
        await websocket.send(
            json.dumps(
                {
                    "type": "org_done",
                    "final_report": final_report,
                    "total_tokens": total_tokens,
                }
            )
        )
    else:
        await websocket.send(
            json.dumps(
                {
                    "type": "error",
                    "message": f"Director failed: {director_result.error}",
                }
            )
        )

    # Clean up
    shutil.rmtree(run_dir, ignore_errors=True)


# -------------------------------------------------------------------------
# HTTP handler
# -------------------------------------------------------------------------


async def process_request(connection, request: Request):
    """Serve HTML on GET /, upgrade to WebSocket on /ws."""
    if request.path == "/ws":
        return None
    return Response(
        HTTPStatus.OK,
        "OK",
        websockets.Headers({"Content-Type": "text/html; charset=utf-8"}),
        HTML_PAGE.encode(),
    )


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------


async def main():
    port = 8767
    async with websockets.serve(
        handle_ws,
        "0.0.0.0",
        port,
        process_request=process_request,
    ):
        logger.info(f"Org demo running at http://localhost:{port}")
        logger.info("Open in your browser and enter a research topic.")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
