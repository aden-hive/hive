# Hive Browser Bridge (Chrome Extension)

Connects Hive GCU subagents to your **existing Chrome browser** instead of
launching separate Chrome processes per agent. Each subagent gets its own
**tab group** — visually labelled in the tab bar, fully isolated, and
automatically cleaned up when the subagent finishes.

## How it works

```
Hive GCU MCP Server (Python)
  ↕  WebSocket  ws://localhost:9229/bridge
Chrome Extension (background.js + offscreen.js)
  ↕  chrome.debugger + chrome.tabs + chrome.tabGroups
Your existing Chrome browser
```

- **offscreen.js** — hosts the persistent WebSocket (survives service worker suspension)
- **background.js** — receives commands, executes via Chrome extension APIs, returns results
- Each subagent → one `chrome.tabGroups` entry, colour-coded in your tab bar
- `context.destroy` closes the group's tabs; Chrome stays alive

## Install (unpacked extension)

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** → select this directory

## GCU server changes needed

The extension connects to `ws://127.0.0.1:9229/beeline`. The GCU MCP server
needs to expose this endpoint and speak the protocol below.

### Protocol (JSON over WebSocket)

All messages from Hive → extension carry `{ id, type, ...params }`.
All replies carry `{ id, result }` or `{ id, error }`.

| Command | Params | Result |
|---|---|---|
| `context.create` | `agentId` | `{ groupId, tabId }` |
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
# 1. At GCU server startup, open ws://localhost:9229/beeline and wait for
#    the extension to connect (sends { type: "hello" }).
#
# 2. On browser_start(profile):
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
