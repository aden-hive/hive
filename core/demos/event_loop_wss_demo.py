#!/usr/bin/env python3
"""
EventLoopNode WebSocket Demo

Real LLM, real FileConversationStore, real EventBus.
Streams EventLoopNode execution to a browser via WebSocket.

Usage:
    cd /home/timothy/oss/hive/core
    python demos/event_loop_wss_demo.py

    Then open http://localhost:8765 in your browser.
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

import os  # noqa: E402

from aden_tools.credentials import CREDENTIAL_SPECS, CredentialStoreAdapter  # noqa: E402
from core.framework.credentials import CredentialStore  # noqa: E402

from framework.credentials.storage import (  # noqa: E402
    CompositeStorage,
    EncryptedFileStorage,
    EnvVarStorage,
)
from framework.graph.event_loop_node import EventLoopNode, LoopConfig  # noqa: E402
from framework.graph.node import NodeContext, NodeSpec, SharedMemory  # noqa: E402
from framework.llm.litellm import LiteLLMProvider  # noqa: E402
from framework.llm.provider import Tool  # noqa: E402
from framework.runner.tool_registry import ToolRegistry  # noqa: E402
from framework.runtime.core import Runtime  # noqa: E402
from framework.runtime.event_bus import EventBus, EventType  # noqa: E402
from framework.storage.conversation_store import FileConversationStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("demo")

# -------------------------------------------------------------------------
# Persistent state (shared across WebSocket connections)
# -------------------------------------------------------------------------

STORE_DIR = Path(tempfile.mkdtemp(prefix="hive_demo_"))
STORE = FileConversationStore(STORE_DIR / "conversation")
RUNTIME = Runtime(STORE_DIR / "runtime")
LLM = LiteLLMProvider(model="claude-sonnet-4-5-20250929")

# -------------------------------------------------------------------------
# Tool Registry — real tools via ToolRegistry (same pattern as GraphExecutor)
# -------------------------------------------------------------------------

TOOL_REGISTRY = ToolRegistry()

# Credential store: Aden sync (OAuth2 tokens) + encrypted files + env var fallback
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

# Debug: log which credentials resolved
for _name in ["brave_search", "hubspot", "anthropic"]:
    _val = CREDENTIALS.get(_name)
    if _val:
        logger.debug("credential %s: OK (len=%d)", _name, len(_val))
    else:
        logger.debug("credential %s: not found", _name)

# --- web_search (Brave Search API) ---

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
                    "description": "Number of results to return (1-20, default 10)",
                },
            },
            "required": ["query"],
        },
    ),
    executor=lambda inputs: _exec_web_search(inputs),
)


def _exec_web_search(inputs: dict) -> dict:
    api_key = CREDENTIALS.get("brave_search")
    if not api_key:
        return {"error": "brave_search credential not configured"}
    query = inputs.get("query", "")
    num_results = min(inputs.get("num_results", 10), 20)
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


# --- web_scrape (httpx + BeautifulSoup, no playwright for sync compat) ---

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


# --- HubSpot CRM tools (optional, requires HUBSPOT_ACCESS_TOKEN) ---

_HUBSPOT_API = "https://api.hubapi.com"


def _hubspot_headers() -> dict | None:
    token = CREDENTIALS.get("hubspot")
    if token:
        logger.debug("HubSpot token: %s...%s (len=%d)", token[:8], token[-4:], len(token))
    else:
        logger.debug("HubSpot token: not found")
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _exec_hubspot_search(inputs: dict) -> dict:
    headers = _hubspot_headers()
    if not headers:
        return {"error": "HUBSPOT_ACCESS_TOKEN not set"}
    object_type = inputs.get("object_type", "contacts")
    query = inputs.get("query", "")
    limit = min(inputs.get("limit", 10), 100)
    body: dict = {"limit": limit}
    if query:
        body["query"] = query
    try:
        resp = httpx.post(
            f"{_HUBSPOT_API}/crm/v3/objects/{object_type}/search",
            headers=headers,
            json=body,
            timeout=30.0,
        )
        if resp.status_code != 200:
            return {"error": f"HubSpot API HTTP {resp.status_code}: {resp.text[:200]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request timed out"}
    except Exception as e:
        return {"error": f"HubSpot error: {e}"}


TOOL_REGISTRY.register(
    name="hubspot_search",
    tool=Tool(
        name="hubspot_search",
        description=(
            "Search HubSpot CRM objects (contacts, companies, or deals). "
            "Returns matching records with their properties."
        ),
        parameters={
            "type": "object",
            "properties": {
                "object_type": {
                    "type": "string",
                    "description": "CRM object type: 'contacts', 'companies', or 'deals'",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (name, email, domain, etc.)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (1-100, default 10)",
                },
            },
            "required": ["object_type"],
        },
    ),
    executor=lambda inputs: _exec_hubspot_search(inputs),
)

logger.info(
    "ToolRegistry loaded: %s",
    ", ".join(TOOL_REGISTRY.get_registered_names()),
)


# -------------------------------------------------------------------------
# HTML page (embedded)
# -------------------------------------------------------------------------

HTML_PAGE = (  # noqa: E501
    """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EventLoopNode Live Demo</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'SF Mono', 'Fira Code', monospace;
    background: #0d1117; color: #c9d1d9;
    height: 100vh; display: flex; flex-direction: column;
  }
  header {
    background: #161b22; padding: 12px 20px;
    border-bottom: 1px solid #30363d;
    display: flex; align-items: center; gap: 16px;
  }
  header h1 { font-size: 16px; color: #58a6ff; font-weight: 600; }
  .status {
    font-size: 12px; padding: 3px 10px; border-radius: 12px;
    background: #21262d; color: #8b949e;
  }
  .status.running { background: #1a4b2e; color: #3fb950; }
  .status.done { background: #1a3a5c; color: #58a6ff; }
  .status.error { background: #4b1a1a; color: #f85149; }
  .chat { flex: 1; overflow-y: auto; padding: 16px; }
  .msg {
    margin: 8px 0; padding: 10px 14px; border-radius: 8px;
    line-height: 1.6; white-space: pre-wrap; word-wrap: break-word;
  }
  .msg.user { background: #1a3a5c; color: #58a6ff; }
  .msg.assistant { background: #161b22; color: #c9d1d9; }
  .msg.event {
    background: transparent; color: #8b949e; font-size: 11px;
    padding: 4px 14px; border-left: 3px solid #30363d;
  }
  .msg.event.loop { border-left-color: #58a6ff; }
  .msg.event.tool { border-left-color: #d29922; }
  .msg.event.stall { border-left-color: #f85149; }
  .input-bar {
    padding: 12px 16px; background: #161b22;
    border-top: 1px solid #30363d; display: flex; gap: 8px;
  }
  .input-bar input {
    flex: 1; background: #0d1117; border: 1px solid #30363d;
    color: #c9d1d9; padding: 8px 12px; border-radius: 6px;
    font-family: inherit; font-size: 14px; outline: none;
  }
  .input-bar input:focus { border-color: #58a6ff; }
  .input-bar button {
    background: #238636; color: #fff; border: none;
    padding: 8px 20px; border-radius: 6px; cursor: pointer;
    font-family: inherit; font-weight: 600;
  }
  .input-bar button:hover { background: #2ea043; }
  .input-bar button:disabled {
    background: #21262d; color: #484f58; cursor: not-allowed;
  }
  .input-bar button.clear { background: #da3633; }
  .input-bar button.clear:hover { background: #f85149; }
</style>
</head>
<body>
  <header>
    <h1>EventLoopNode Live</h1>
    <span id="status" class="status">Idle</span>
    <span id="iter" class="status" style="display:none">Step 0</span>
  </header>
  <div id="chat" class="chat"></div>
  <div class="input-bar">
    <input id="input" type="text"
           placeholder="Ask anything..." autofocus />
    <button id="go" onclick="run()">Send</button>
    <button class="clear"
            onclick="clearConversation()">Clear</button>
  </div>

<script>
let ws = null;
let currentAssistantEl = null;
let iterCount = 0;
const chat = document.getElementById('chat');
const status = document.getElementById('status');
const iterEl = document.getElementById('iter');
const goBtn = document.getElementById('go');
const inputEl = document.getElementById('input');

inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter') run();
});

function setStatus(text, cls) {
  status.textContent = text;
  status.className = 'status ' + cls;
}

function addMsg(text, cls) {
  const el = document.createElement('div');
  el.className = 'msg ' + cls;
  el.textContent = text;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

function connect() {
  ws = new WebSocket('ws://' + location.host + '/ws');
  ws.onopen = () => {
    setStatus('Ready', 'done');
    goBtn.disabled = false;
  };
  ws.onmessage = handleEvent;
  ws.onerror = () => { setStatus('Error', 'error'); };
  ws.onclose = () => {
    setStatus('Reconnecting...', '');
    goBtn.disabled = true;
    setTimeout(connect, 2000);
  };
}

function handleEvent(msg) {
  const evt = JSON.parse(msg.data);

  if (evt.type === 'llm_text_delta') {
    if (currentAssistantEl) {
      currentAssistantEl.textContent += evt.content;
      chat.scrollTop = chat.scrollHeight;
    }
  }
  else if (evt.type === 'ready') {
    setStatus('Ready', 'done');
    if (currentAssistantEl && !currentAssistantEl.textContent)
      currentAssistantEl.remove();
    goBtn.disabled = false;
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
    addMsg('RESULT  ' + evt.tool_name + ': ' + preview,
           'event ' + cls);
    currentAssistantEl = addMsg('', 'assistant');
  }
  else if (evt.type === 'result') {
    setStatus('Session ended', evt.success ? 'done' : 'error');
    if (evt.error) addMsg('ERROR  ' + evt.error, 'event stall');
    if (currentAssistantEl && !currentAssistantEl.textContent)
      currentAssistantEl.remove();
    goBtn.disabled = false;
  }
  else if (evt.type === 'node_stalled') {
    addMsg('STALLED  ' + evt.reason, 'event stall');
  }
  else if (evt.type === 'cleared') {
    chat.innerHTML = '';
    iterCount = 0;
    iterEl.textContent = 'Step 0';
    iterEl.style.display = 'none';
    setStatus('Ready', 'done');
    goBtn.disabled = false;
  }
}

function run() {
  const text = inputEl.value.trim();
  if (!text || !ws || ws.readyState !== 1) return;
  addMsg(text, 'user');
  currentAssistantEl = addMsg('', 'assistant');
  inputEl.value = '';
  setStatus('Running', 'running');
  goBtn.disabled = true;
  ws.send(JSON.stringify({ topic: text }));
}

function clearConversation() {
  if (ws && ws.readyState === 1) {
    ws.send(JSON.stringify({ command: 'clear' }));
  }
}

connect();
</script>
</body>
</html>"""
)


# -------------------------------------------------------------------------
# WebSocket handler
# -------------------------------------------------------------------------


async def handle_ws(websocket):
    """Persistent WebSocket: long-lived EventLoopNode with client_facing blocking."""
    global STORE

    # -- Event forwarding (WebSocket ← EventBus) ----------------------------
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

    # -- Per-connection state -----------------------------------------------
    node = None
    loop_task = None

    tools = list(TOOL_REGISTRY.get_tools().values())
    tool_executor = TOOL_REGISTRY.get_executor()

    node_spec = NodeSpec(
        id="assistant",
        name="Chat Assistant",
        description="A conversational assistant that remembers context across messages",
        node_type="event_loop",
        client_facing=True,
        system_prompt=(
            "You are a helpful assistant with access to tools. "
            "You can search the web, scrape webpages, and query HubSpot CRM. "
            "Use tools when the user asks for current information or external data. "
            "You have full conversation history, so you can reference previous messages."
        ),
    )

    # -- Ready callback: subscribe to CLIENT_INPUT_REQUESTED on the bus ---
    async def on_input_requested(event):
        try:
            await websocket.send(json.dumps({"type": "ready"}))
        except Exception:
            pass

    bus.subscribe(
        event_types=[EventType.CLIENT_INPUT_REQUESTED],
        handler=on_input_requested,
    )

    async def start_loop(first_message: str):
        """Create an EventLoopNode and run it as a background task."""
        nonlocal node, loop_task

        memory = SharedMemory()
        ctx = NodeContext(
            runtime=RUNTIME,
            node_id="assistant",
            node_spec=node_spec,
            memory=memory,
            input_data={},
            llm=LLM,
            available_tools=tools,
        )
        node = EventLoopNode(
            event_bus=bus,
            config=LoopConfig(max_iterations=10_000, max_history_tokens=32_000),
            conversation_store=STORE,
            tool_executor=tool_executor,
        )
        await node.inject_event(first_message)

        async def _run():
            try:
                result = await node.execute(ctx)
                try:
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "result",
                                "success": result.success,
                                "output": result.output,
                                "error": result.error,
                                "tokens": result.tokens_used,
                            }
                        )
                    )
                except Exception:
                    pass
                logger.info(f"Loop ended: success={result.success}, tokens={result.tokens_used}")
            except websockets.exceptions.ConnectionClosed:
                logger.info("Loop stopped: WebSocket closed")
            except Exception as e:
                logger.exception("Loop error")
                try:
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "result",
                                "success": False,
                                "error": str(e),
                                "output": {},
                            }
                        )
                    )
                except Exception:
                    pass

        loop_task = asyncio.create_task(_run())

    async def stop_loop():
        """Signal the node and wait for the loop task to finish."""
        nonlocal node, loop_task
        if loop_task and not loop_task.done():
            if node:
                node.signal_shutdown()
            try:
                await asyncio.wait_for(loop_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                loop_task.cancel()
        node = None
        loop_task = None

    # -- Message loop (runs for the lifetime of this WebSocket) -------------
    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            # Clear command
            if msg.get("command") == "clear":
                import shutil

                await stop_loop()
                await STORE.close()
                conv_dir = STORE_DIR / "conversation"
                if conv_dir.exists():
                    shutil.rmtree(conv_dir)
                STORE = FileConversationStore(conv_dir)
                await websocket.send(json.dumps({"type": "cleared"}))
                logger.info("Conversation cleared")
                continue

            topic = msg.get("topic", "")
            if not topic:
                continue

            if node is None:
                # First message — spin up the loop
                logger.info(f"Starting persistent loop: {topic}")
                await start_loop(topic)
            else:
                # Subsequent message — inject into the running loop
                logger.info(f"Injecting message: {topic}")
                await node.inject_event(topic)

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        await stop_loop()
        logger.info("WebSocket closed, loop stopped")


# -------------------------------------------------------------------------
# HTTP handler for serving the HTML page
# -------------------------------------------------------------------------


async def process_request(connection, request: Request):
    """Serve HTML on GET /, upgrade to WebSocket on /ws."""
    if request.path == "/ws":
        return None  # let websockets handle the upgrade
    # Serve the HTML page for any other path
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
    port = 8765
    async with websockets.serve(
        handle_ws,
        "0.0.0.0",
        port,
        process_request=process_request,
    ):
        logger.info(f"Demo running at http://localhost:{port}")
        logger.info("Open in your browser and enter a topic to research.")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
