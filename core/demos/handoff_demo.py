#!/usr/bin/env python3
"""
Two-Node ContextHandoff Demo

Demonstrates ContextHandoff between two EventLoopNode instances:
  Node A (Researcher) → ContextHandoff → Node B (Analyst)

Real LLM, real FileConversationStore, real EventBus.
Streams both nodes to a browser via WebSocket.

Usage:
    cd /home/timothy/oss/hive/core
    python demos/handoff_demo.py

    Then open http://localhost:8766 in your browser.
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
sys.path.insert(0, str(_CORE_DIR))  # framework.*
sys.path.insert(0, str(_HIVE_DIR / "tools" / "src"))  # aden_tools.*
sys.path.insert(0, str(_HIVE_DIR))  # core.framework.* (for aden_tools imports)

from aden_tools.credentials import CREDENTIAL_SPECS, CredentialStoreAdapter  # noqa: E402
from core.framework.credentials import CredentialStore  # noqa: E402

from framework.credentials.storage import (  # noqa: E402
    CompositeStorage,
    EncryptedFileStorage,
    EnvVarStorage,
)
from framework.graph.context_handoff import ContextHandoff  # noqa: E402
from framework.graph.conversation import NodeConversation  # noqa: E402
from framework.graph.event_loop_node import EventLoopNode, LoopConfig  # noqa: E402
from framework.graph.node import NodeContext, NodeSpec, SharedMemory  # noqa: E402
from framework.llm.litellm import LiteLLMProvider  # noqa: E402
from framework.llm.provider import Tool  # noqa: E402
from framework.runner.tool_registry import ToolRegistry  # noqa: E402
from framework.runtime.core import Runtime  # noqa: E402
from framework.runtime.event_bus import EventBus, EventType  # noqa: E402
from framework.storage.conversation_store import FileConversationStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("handoff_demo")

# -------------------------------------------------------------------------
# Persistent state
# -------------------------------------------------------------------------

STORE_DIR = Path(tempfile.mkdtemp(prefix="hive_handoff_"))
RUNTIME = Runtime(STORE_DIR / "runtime")
LLM = LiteLLMProvider(model="claude-sonnet-4-5-20250929")

# -------------------------------------------------------------------------
# Credentials
# -------------------------------------------------------------------------

# Composite credential store: encrypted files (primary) + env vars (fallback)
_env_mapping = {name: spec.env_var for name, spec in CREDENTIAL_SPECS.items()}
_composite = CompositeStorage(
    primary=EncryptedFileStorage(),
    fallbacks=[EnvVarStorage(env_mapping=_env_mapping)],
)
CREDENTIALS = CredentialStoreAdapter(CredentialStore(storage=_composite))

for _name in ["brave_search", "hubspot"]:
    _val = CREDENTIALS.get(_name)
    if _val:
        logger.debug("credential %s: OK (len=%d)", _name, len(_val))
    else:
        logger.debug("credential %s: not found", _name)

# -------------------------------------------------------------------------
# Tool Registry — web_search + web_scrape for Node A (Researcher)
# -------------------------------------------------------------------------

TOOL_REGISTRY = ToolRegistry()


def _exec_web_search(inputs: dict) -> dict:
    api_key = CREDENTIALS.get("brave_search")
    if not api_key:
        return {"error": "brave_search credential not configured"}
    query = inputs.get("query", "")
    num_results = min(inputs.get("num_results", 10), 20)
    resp = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": num_results},
        headers={
            "X-Subscription-Token": api_key,
            "Accept": "application/json",
        },
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
        description=(
            "Search the web for current information. "
            "Returns titles, URLs, and snippets from search results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query (1-500 characters)",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results (1-20, default 10)",
                },
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
        resp = httpx.get(
            url,
            timeout=30.0,
            follow_redirects=True,
            headers=_SCRAPE_HEADERS,
        )
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
        return {
            "url": url,
            "title": title,
            "content": text,
            "length": len(text),
        }
    except httpx.TimeoutException:
        return {"error": "Request timed out"}
    except Exception as e:
        return {"error": f"Scrape failed: {e}"}


TOOL_REGISTRY.register(
    name="web_scrape",
    tool=Tool(
        name="web_scrape",
        description=(
            "Scrape and extract text content from a webpage URL. "
            "Returns the page title and main text content."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL of the webpage to scrape",
                },
                "max_length": {
                    "type": "integer",
                    "description": "Maximum text length (default 50000)",
                },
            },
            "required": ["url"],
        },
    ),
    executor=lambda inputs: _exec_web_scrape(inputs),
)

logger.info(
    "ToolRegistry loaded: %s",
    ", ".join(TOOL_REGISTRY.get_registered_names()),
)

# -------------------------------------------------------------------------
# Node Specs
# -------------------------------------------------------------------------

RESEARCHER_SPEC = NodeSpec(
    id="researcher",
    name="Researcher",
    description="Researches a topic using web search and scraping tools",
    node_type="event_loop",
    input_keys=["topic"],
    output_keys=["research_summary"],
    system_prompt=(
        "You are a thorough research assistant. Your job is to research "
        "the given topic using the web_search and web_scrape tools.\n\n"
        "1. Search for relevant information on the topic\n"
        "2. Scrape 1-2 of the most promising URLs for details\n"
        "3. Synthesize your findings into a comprehensive summary\n"
        "4. Use set_output with key='research_summary' to save your "
        "findings\n\n"
        "Be thorough but efficient. Aim for 2-4 search/scrape calls, "
        "then summarize and set_output."
    ),
)

ANALYST_SPEC = NodeSpec(
    id="analyst",
    name="Analyst",
    description="Analyzes research findings and provides insights",
    node_type="event_loop",
    input_keys=["context"],
    output_keys=["analysis"],
    system_prompt=(
        "You are a strategic analyst. You receive research findings from "
        "a previous researcher and must:\n\n"
        "1. Identify key themes and patterns\n"
        "2. Assess the reliability and significance of the findings\n"
        "3. Provide actionable insights and recommendations\n"
        "4. Use set_output with key='analysis' to save your analysis\n\n"
        "Be concise but insightful. Focus on what matters most."
    ),
)


# -------------------------------------------------------------------------
# HTML page
# -------------------------------------------------------------------------

HTML_PAGE = (  # noqa: E501
    """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ContextHandoff Demo</title>
<style>
  * {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }
  body {
    font-family: 'SF Mono', 'Fira Code', monospace;
    background: #0d1117;
    color: #c9d1d9;
    height: 100vh;
    display: flex;
    flex-direction: column;
  }
  header {
    background: #161b22;
    padding: 12px 20px;
    border-bottom: 1px solid #30363d;
    display: flex;
    align-items: center;
    gap: 16px;
  }
  header h1 {
    font-size: 16px;
    color: #58a6ff;
    font-weight: 600;
  }
  .badge {
    font-size: 12px;
    padding: 3px 10px;
    border-radius: 12px;
    background: #21262d;
    color: #8b949e;
  }
  .badge.researcher {
    background: #1a3a5c;
    color: #58a6ff;
  }
  .badge.analyst {
    background: #1a4b2e;
    color: #3fb950;
  }
  .badge.handoff {
    background: #3d1f00;
    color: #d29922;
  }
  .badge.done {
    background: #21262d;
    color: #8b949e;
  }
  .badge.error {
    background: #4b1a1a;
    color: #f85149;
  }
  .chat {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
  }
  .msg {
    margin: 8px 0;
    padding: 10px 14px;
    border-radius: 8px;
    line-height: 1.6;
    white-space: pre-wrap;
    word-wrap: break-word;
  }
  .msg.user {
    background: #1a3a5c;
    color: #58a6ff;
  }
  .msg.assistant {
    background: #161b22;
    color: #c9d1d9;
  }
  .msg.assistant.analyst-msg {
    border-left: 3px solid #3fb950;
  }
  .msg.event {
    background: transparent;
    color: #8b949e;
    font-size: 11px;
    padding: 4px 14px;
    border-left: 3px solid #30363d;
  }
  .msg.event.loop {
    border-left-color: #58a6ff;
  }
  .msg.event.tool {
    border-left-color: #d29922;
  }
  .msg.event.stall {
    border-left-color: #f85149;
  }
  .handoff-banner {
    margin: 16px 0;
    padding: 16px;
    background: #1c1200;
    border: 1px solid #d29922;
    border-radius: 8px;
    text-align: center;
  }
  .handoff-banner h3 {
    color: #d29922;
    font-size: 14px;
    margin-bottom: 8px;
  }
  .handoff-banner p, .result-banner p {
    color: #8b949e;
    font-size: 12px;
    line-height: 1.5;
    max-height: 200px;
    overflow-y: auto;
    white-space: pre-wrap;
    text-align: left;
  }
  .result-banner {
    margin: 16px 0;
    padding: 16px;
    background: #0a2614;
    border: 1px solid #3fb950;
    border-radius: 8px;
  }
  .result-banner h3 {
    color: #3fb950;
    font-size: 14px;
    margin-bottom: 8px;
    text-align: center;
  }
  .result-banner .label {
    color: #58a6ff;
    font-size: 11px;
    font-weight: 600;
    margin-top: 10px;
    margin-bottom: 2px;
  }
  .result-banner .tokens {
    color: #484f58;
    font-size: 11px;
    text-align: center;
    margin-top: 10px;
  }
  .input-bar {
    padding: 12px 16px;
    background: #161b22;
    border-top: 1px solid #30363d;
    display: flex;
    gap: 8px;
  }
  .input-bar input {
    flex: 1;
    background: #0d1117;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 8px 12px;
    border-radius: 6px;
    font-family: inherit;
    font-size: 14px;
    outline: none;
  }
  .input-bar input:focus {
    border-color: #58a6ff;
  }
  .input-bar button {
    background: #238636;
    color: #fff;
    border: none;
    padding: 8px 20px;
    border-radius: 6px;
    cursor: pointer;
    font-family: inherit;
    font-weight: 600;
  }
  .input-bar button:hover {
    background: #2ea043;
  }
  .input-bar button:disabled {
    background: #21262d;
    color: #484f58;
    cursor: not-allowed;
  }
</style>
</head>
<body>
  <header>
    <h1>ContextHandoff Demo</h1>
    <span id="phase" class="badge">Idle</span>
    <span id="iter" class="badge" style="display:none">Step 0</span>
  </header>
  <div id="chat" class="chat"></div>
  <div class="input-bar">
    <input id="input" type="text"
           placeholder="Enter a research topic..." autofocus />
    <button id="go" onclick="run()">Research</button>
  </div>

<script>
let ws = null;
let currentAssistantEl = null;
let iterCount = 0;
let currentPhase = 'idle';
const chat = document.getElementById('chat');
const phase = document.getElementById('phase');
const iterEl = document.getElementById('iter');
const goBtn = document.getElementById('go');
const inputEl = document.getElementById('input');

inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter') run();
});

function setPhase(text, cls) {
  phase.textContent = text;
  phase.className = 'badge ' + cls;
  currentPhase = cls;
}

function addMsg(text, cls) {
  const el = document.createElement('div');
  el.className = 'msg ' + cls;
  el.textContent = text;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

function addHandoffBanner(summary) {
  const banner = document.createElement('div');
  banner.className = 'handoff-banner';
  const h3 = document.createElement('h3');
  h3.textContent = 'Context Handoff: Researcher -> Analyst';
  const p = document.createElement('p');
  p.textContent = summary || 'Passing research context...';
  banner.appendChild(h3);
  banner.appendChild(p);
  chat.appendChild(banner);
  chat.scrollTop = chat.scrollHeight;
}

function addResultBanner(researcher, analyst, tokens) {
  const banner = document.createElement('div');
  banner.className = 'result-banner';
  const h3 = document.createElement('h3');
  h3.textContent = 'Pipeline Complete';
  banner.appendChild(h3);

  if (researcher && researcher.research_summary) {
    const lbl = document.createElement('div');
    lbl.className = 'label';
    lbl.textContent = 'RESEARCH SUMMARY';
    banner.appendChild(lbl);
    const p = document.createElement('p');
    p.textContent = researcher.research_summary;
    banner.appendChild(p);
  }

  if (analyst && analyst.analysis) {
    const lbl = document.createElement('div');
    lbl.className = 'label';
    lbl.textContent = 'ANALYSIS';
    lbl.style.color = '#3fb950';
    banner.appendChild(lbl);
    const p = document.createElement('p');
    p.textContent = analyst.analysis;
    banner.appendChild(p);
  }

  if (tokens) {
    const t = document.createElement('div');
    t.className = 'tokens';
    t.textContent = 'Total tokens: ' + tokens.toLocaleString();
    banner.appendChild(t);
  }

  chat.appendChild(banner);
  chat.scrollTop = chat.scrollHeight;
}

function connect() {
  ws = new WebSocket('ws://' + location.host + '/ws');
  ws.onopen = () => {
    setPhase('Ready', 'done');
    goBtn.disabled = false;
  };
  ws.onmessage = handleEvent;
  ws.onerror = () => { setPhase('Error', 'error'); };
  ws.onclose = () => {
    setPhase('Reconnecting...', '');
    goBtn.disabled = true;
    setTimeout(connect, 2000);
  };
}

function handleEvent(msg) {
  const evt = JSON.parse(msg.data);

  if (evt.type === 'phase') {
    if (evt.phase === 'researcher') {
      setPhase('Researcher', 'researcher');
    } else if (evt.phase === 'handoff') {
      setPhase('Handoff', 'handoff');
    } else if (evt.phase === 'analyst') {
      setPhase('Analyst', 'analyst');
    }
    iterCount = 0;
    iterEl.style.display = 'none';
  }
  else if (evt.type === 'llm_text_delta') {
    if (currentAssistantEl) {
      currentAssistantEl.textContent += evt.content;
      chat.scrollTop = chat.scrollHeight;
    }
  }
  else if (evt.type === 'node_loop_iteration') {
    iterCount = evt.iteration || (iterCount + 1);
    iterEl.textContent = 'Step ' + iterCount;
    iterEl.style.display = '';
  }
  else if (evt.type === 'tool_call_started') {
    var info = evt.tool_name + '('
      + JSON.stringify(evt.tool_input).slice(0, 120) + ')';
    addMsg('TOOL  ' + info, 'event tool');
  }
  else if (evt.type === 'tool_call_completed') {
    var preview = (evt.result || '').slice(0, 200);
    var cls = evt.is_error ? 'stall' : 'tool';
    addMsg(
      'RESULT  ' + evt.tool_name + ': ' + preview,
      'event ' + cls
    );
    var assistCls = currentPhase === 'analyst'
      ? 'assistant analyst-msg' : 'assistant';
    currentAssistantEl = addMsg('', assistCls);
  }
  else if (evt.type === 'handoff_context') {
    addHandoffBanner(evt.summary);
    var assistCls = 'assistant analyst-msg';
    currentAssistantEl = addMsg('', assistCls);
  }
  else if (evt.type === 'node_result') {
    if (evt.node_id === 'researcher') {
      if (currentAssistantEl
          && !currentAssistantEl.textContent) {
        currentAssistantEl.remove();
      }
    }
  }
  else if (evt.type === 'done') {
    setPhase('Done', 'done');
    iterEl.style.display = 'none';
    if (currentAssistantEl
        && !currentAssistantEl.textContent) {
      currentAssistantEl.remove();
    }
    currentAssistantEl = null;
    addResultBanner(
      evt.researcher, evt.analyst, evt.total_tokens
    );
    goBtn.disabled = false;
    inputEl.placeholder = 'Enter another topic...';
  }
  else if (evt.type === 'error') {
    setPhase('Error', 'error');
    addMsg('ERROR  ' + evt.message, 'event stall');
    goBtn.disabled = false;
  }
  else if (evt.type === 'node_stalled') {
    addMsg('STALLED  ' + evt.reason, 'event stall');
  }
}

function run() {
  const text = inputEl.value.trim();
  if (!text || !ws || ws.readyState !== 1) return;
  chat.innerHTML = '';
  addMsg(text, 'user');
  currentAssistantEl = addMsg('', 'assistant');
  inputEl.value = '';
  goBtn.disabled = true;
  ws.send(JSON.stringify({ topic: text }));
}

connect();
</script>
</body>
</html>"""
)


# -------------------------------------------------------------------------
# WebSocket handler — sequential Node A → Handoff → Node B
# -------------------------------------------------------------------------


async def handle_ws(websocket):
    """Run the two-node handoff pipeline per user message."""
    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            topic = msg.get("topic", "")
            if not topic:
                continue

            logger.info(f"Starting handoff pipeline for: {topic}")

            try:
                await _run_pipeline(websocket, topic)
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


async def _run_pipeline(websocket, topic: str):
    """Execute: Node A (research) → ContextHandoff → Node B (analysis)."""
    import shutil

    # Fresh stores for each run
    run_dir = Path(tempfile.mkdtemp(prefix="hive_run_", dir=STORE_DIR))
    store_a = FileConversationStore(run_dir / "node_a")
    store_b = FileConversationStore(run_dir / "node_b")

    # Shared event bus
    bus = EventBus()

    async def forward_event(event):
        try:
            payload = {"type": event.type.value, **event.data}
            if event.node_id:
                payload["node_id"] = event.node_id
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
        ],
        handler=forward_event,
    )

    tools = list(TOOL_REGISTRY.get_tools().values())
    tool_executor = TOOL_REGISTRY.get_executor()

    # ---- Phase 1: Researcher ------------------------------------------------
    await websocket.send(json.dumps({"type": "phase", "phase": "researcher"}))

    node_a = EventLoopNode(
        event_bus=bus,
        judge=None,  # implicit judge: accept when output_keys filled
        config=LoopConfig(
            max_iterations=20,
            max_tool_calls_per_turn=30,
            max_history_tokens=32_000,
        ),
        conversation_store=store_a,
        tool_executor=tool_executor,
    )

    ctx_a = NodeContext(
        runtime=RUNTIME,
        node_id="researcher",
        node_spec=RESEARCHER_SPEC,
        memory=SharedMemory(),
        input_data={"topic": topic},
        llm=LLM,
        available_tools=tools,
    )

    result_a = await node_a.execute(ctx_a)
    logger.info(
        "Researcher done: success=%s, tokens=%s",
        result_a.success,
        result_a.tokens_used,
    )

    await websocket.send(
        json.dumps(
            {
                "type": "node_result",
                "node_id": "researcher",
                "success": result_a.success,
                "output": result_a.output,
            }
        )
    )

    if not result_a.success:
        await websocket.send(
            json.dumps(
                {
                    "type": "error",
                    "message": f"Researcher failed: {result_a.error}",
                }
            )
        )
        return

    # ---- Phase 2: Context Handoff -------------------------------------------
    await websocket.send(json.dumps({"type": "phase", "phase": "handoff"}))

    # Restore the researcher's conversation from store
    conversation_a = await NodeConversation.restore(store_a)
    if conversation_a is None:
        await websocket.send(
            json.dumps(
                {
                    "type": "error",
                    "message": "Failed to restore researcher conversation",
                }
            )
        )
        return

    handoff_engine = ContextHandoff(llm=LLM)
    handoff_context = handoff_engine.summarize_conversation(
        conversation=conversation_a,
        node_id="researcher",
        output_keys=["research_summary"],
    )

    formatted_handoff = ContextHandoff.format_as_input(handoff_context)
    logger.info(
        "Handoff: %d turns, ~%d tokens, keys=%s",
        handoff_context.turn_count,
        handoff_context.total_tokens_used,
        list(handoff_context.key_outputs.keys()),
    )

    # Send handoff context to browser
    await websocket.send(
        json.dumps(
            {
                "type": "handoff_context",
                "summary": handoff_context.summary[:500],
                "turn_count": handoff_context.turn_count,
                "tokens": handoff_context.total_tokens_used,
                "key_outputs": handoff_context.key_outputs,
            }
        )
    )

    # ---- Phase 3: Analyst ---------------------------------------------------
    await websocket.send(json.dumps({"type": "phase", "phase": "analyst"}))

    node_b = EventLoopNode(
        event_bus=bus,
        judge=None,  # implicit judge
        config=LoopConfig(
            max_iterations=10,
            max_tool_calls_per_turn=30,
            max_history_tokens=32_000,
        ),
        conversation_store=store_b,
    )

    ctx_b = NodeContext(
        runtime=RUNTIME,
        node_id="analyst",
        node_spec=ANALYST_SPEC,
        memory=SharedMemory(),
        input_data={"context": formatted_handoff},
        llm=LLM,
        available_tools=[],
    )

    result_b = await node_b.execute(ctx_b)
    logger.info(
        "Analyst done: success=%s, tokens=%s",
        result_b.success,
        result_b.tokens_used,
    )

    # ---- Done ---------------------------------------------------------------
    await websocket.send(
        json.dumps(
            {
                "type": "done",
                "researcher": result_a.output,
                "analyst": result_b.output,
                "total_tokens": ((result_a.tokens_used or 0) + (result_b.tokens_used or 0)),
            }
        )
    )

    # Clean up temp stores
    try:
        shutil.rmtree(run_dir)
    except Exception:
        pass


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
    port = 8766
    async with websockets.serve(
        handle_ws,
        "0.0.0.0",
        port,
        process_request=process_request,
    ):
        logger.info(f"Handoff demo at http://localhost:{port}")
        logger.info("Enter a research topic to start the pipeline.")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
