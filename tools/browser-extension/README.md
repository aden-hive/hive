# Hive Browser Bridge (Chrome Extension)

Connects Hive GCU subagents to your **existing Chrome browser** instead of
launching separate Chrome processes per agent. Each subagent gets its own
**tab group** — visually labelled in the tab bar, fully isolated, and
automatically cleaned up when the subagent finishes.

## How it works

```
Hive GCU MCP Server (Python)
  ↕  WebSocket  ws://127.0.0.1:14829/bridge   (commands)
  ↕  HTTP       http://127.0.0.1:14830/status, /contexts   (diagnostics)
  (also listens on legacy 9229/9230 during the extension-migration window)
Chrome Extension (background.js + offscreen.js)
  ↕  chrome.debugger + chrome.tabs + chrome.tabGroups
Your existing Chrome browser
```

- **offscreen.js** — hosts the persistent WebSocket (survives service worker suspension)
- **background.js** — receives commands, executes via Chrome extension APIs, returns results
- Each subagent → one `chrome.tabGroups` entry, colour-coded in your tab bar
- `context.destroy` closes the group's tabs; Chrome stays alive

## Connection health side panel

Click the toolbar icon to open the **side panel** — it docks to the side of the
browser and stays put while you work. It runs a fresh end-to-end diagnostic
every ~2 seconds and holds no cached "connected" flag, so the indicator cannot
get stuck green on a dead link. The panel determines health itself by fetching
the bridge's HTTP endpoints directly — it never depends on the service worker
answering a message. It shows, independently:

- **Hive app** — the GCU bridge answers on `http://127.0.0.1:14830` (legacy `9230`).
- **Browser bridge** — the bridge server inside the app is running.
- **WebSocket** — the socket's *live* `readyState` (or the server's confirmation).
- **Extension link** — the bridge's own `/status` confirms it accepted *this*
  extension (and isn't bound to a different browser/extension instance).
- **Heartbeat** — round-trip freshness from the bridge's `/status`. The bridge
  pings the extension *and* the extension pings the bridge (two-way health
  check); a half-open socket is detected from either side and auto-reconnected.
- **Debugger** — warns when DevTools or another tool holds `chrome.debugger` on a
  tab, which blocks automation even while the socket is green.

The panel also lists **active agents** — one row per live tab group — so you can
see which colony workers are driving the browser right now.

## Install

Install from the Chrome Web Store:
https://chromewebstore.google.com/detail/hive-browser-bridge/jkpcegnbfimimjodblcemoheedidnppm

### Developer install (unpacked)

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** → select this directory

## GCU server changes needed

The extension connects to `ws://127.0.0.1:14829/bridge` (and falls back to the
legacy `9229` during the migration window). The GCU MCP server
needs to expose this endpoint and speak the protocol below.

### Protocol (JSON over WebSocket)

All messages from Hive → extension carry `{ id, type, ...params }`.
All replies carry `{ id, result }` or `{ id, error }`.

| Command | Params | Result |
|---|---|---|
| `context.create` | `agentId, displayName?` | `{ groupId, tabId }` |
| `context.destroy` | `groupId` | `{ ok, closedTabs }` |
| `tab.create` | `groupId?, url?` | `{ tabId }` |
| `tab.close` | `tabId` | `{ ok }` |
| `tab.list` | `groupId?` | `{ tabs }` |
| `tab.activate` | `tabId` | `{ ok }` |
| `cdp.attach` | `tabId` | `{ ok }` |
| `cdp.detach` | `tabId` | `{ ok }` |
| `cdp` | `tabId, method, params` | CDP result |

### GCU session.py sketch

```python
# Instead of launch_chrome() + playwright.connect_over_cdp():
#
# 1. At GCU server startup, open ws://127.0.0.1:14829/bridge and wait for
#    the extension to connect (sends { type: "hello" }).
#
# 2. On the first browser tool call for a profile (lazy-start via _ensure_context):
#    - Send { id, type: "context.create", agentId: profile }
#    - Receive { groupId, tabId }
#    - Store groupId in the session object (no Chrome process, no CDP port)
#
# 3. On browser tool calls (navigate, click, snapshot, …):
#    - Send { id, type: "cdp.attach", tabId } if not already attached
#    - Send { id, type: "cdp", tabId, method: "Page.navigate", params: { url } }
#    - Return CDP result to the agent
#
# 4. On browser_stop(profile):
#    - Send { id, type: "context.destroy", groupId }
#    - All tabs in the group close; Chrome stays running
```
