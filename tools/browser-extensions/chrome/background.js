/**
 * Hive Browser Bridge - background script (Firefox compatible)
 *
 * Commands from Hive (via WebSocket directly):
 *
 *   context.create  { agentId }           → { groupId, tabId }
 *   context.destroy { groupId }           → { ok, closedTabs }
 *   tab.create      { groupId, url }      → { tabId }
 *   tab.close       { tabId }             → { ok }
 *   tab.list        { groupId? }          → { tabs: [{id,url,title,groupId}] }
 *   tab.activate    { tabId }             → { ok }
 *   cdp.attach      { tabId }             → { ok }
 *   cdp.detach      { tabId }             → { ok }
 *   cdp             { tabId, method, params } → { ...cdp result }
 *
 * All responses: { id, result } or { id, error }.
 */

// ---------------------------------------------------------------------------
// WebSocket connection logic (Integrated from offscreen.js for Firefox MV3)
// ---------------------------------------------------------------------------

const HIVE_WS_URL = "ws://127.0.0.1:9229/bridge";
let ws = null;
const RETRY_INTERVAL = 2000;

async function setConnected(value) {
  // Use session storage to persist state across background page suspensions/reloads
  await chrome.storage.session.set({ wsConnected: value });
}

function connect() {
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
    return;
  }

  try {
    ws = new WebSocket(HIVE_WS_URL);

    ws.onopen = () => {
      console.log("[Beeline] WebSocket connected to Hive");
      setConnected(true);
      wsSend({ type: "hello", version: "1.0" });
    };

    ws.onmessage = (event) => {
      handleCommand(JSON.parse(event.data));
    };

    ws.onclose = (event) => {
      console.log(`[Beeline] WebSocket closed: code=${event.code}, reason=${event.reason}`);
      setConnected(false);
      ws = null;
      setTimeout(connect, RETRY_INTERVAL);
    };

    ws.onerror = () => {
      console.warn(`[Beeline] WebSocket connection failed (server may not be running)`);
    };
  } catch (error) {
    console.error("[Beeline] Failed to create WebSocket:", error.message);
    setConnected(false);
    ws = null;
    setTimeout(connect, RETRY_INTERVAL);
  }
}

function wsSend(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  } else {
    console.warn("[Beeline] Cannot send - WebSocket not connected (state: %s)",
      ws ? ws.readyState : "null");
  }
}

// ---------------------------------------------------------------------------
// Command dispatch
// ---------------------------------------------------------------------------

const TAB_GROUP_COLORS = ["blue", "red", "yellow", "green", "pink", "purple", "cyan", "orange", "grey"];

function pickColor(groupId) {
  return TAB_GROUP_COLORS[groupId % TAB_GROUP_COLORS.length];
}

async function handleCommand(msg) {
  const { id, type, ...params } = msg;
  try {
    const result = await dispatch(type, params);
    wsSend({ id, result });
  } catch (err) {
    wsSend({ id, error: err.message });
  }
}

async function dispatch(type, params) {
  switch (type) {
    // ── Context (tab group) management ────────────────────────────────────
    case "context.create": {
      // Create a blank tab. In Firefox, tabGroups are not supported natively.
      const tab = await chrome.tabs.create({ url: "about:blank", active: false });
      let groupId = tab.windowId; // Fallback to windowId in Firefox
      
      if (chrome.tabs.group) {
        groupId = await chrome.tabs.group({ tabIds: [tab.id] });
        if (chrome.tabGroups && chrome.tabGroups.update) {
            await chrome.tabGroups.update(groupId, {
              title: params.agentId ?? "Hive Agent",
              color: pickColor(groupId),
              collapsed: false,
            });
        }
      }
      return { groupId, tabId: tab.id };
    }

    case "context.destroy": {
      let tabs = [];
      if (chrome.tabs.group) {
        tabs = await chrome.tabs.query({ groupId: params.groupId });
      } else {
        // Fallback for Firefox (uses windowId as groupId substitute)
        tabs = await chrome.tabs.query({ windowId: params.groupId });
      }
      
      if (tabs.length > 0) {
        // Detach debugger from all tabs before closing them.
        await Promise.allSettled(
          tabs.map((t) => chrome.debugger.detach({ tabId: t.id }).catch(() => {}))
        );
        await chrome.tabs.remove(tabs.map((t) => t.id));
      }
      return { ok: true, closedTabs: tabs.length };
    }

    // ── Tab management ────────────────────────────────────────────────────
    case "tab.create": {
      const tab = await chrome.tabs.create({
        url: params.url ?? "about:blank",
        active: false,
      });
      if (params.groupId != null) {
        if (chrome.tabs.group) {
          await chrome.tabs.group({ tabIds: [tab.id], groupId: params.groupId });
        } else {
          // Firefox fallback
          await chrome.tabs.move(tab.id, { windowId: params.groupId, index: -1 });
        }
      }
      return { tabId: tab.id };
    }

    case "tab.close": {
      await chrome.debugger.detach({ tabId: params.tabId }).catch(() => {});
      await chrome.tabs.remove(params.tabId);
      return { ok: true };
    }

    case "tab.list": {
      let query = {};
      if (params.groupId != null) {
        if (chrome.tabs.group) {
          query = { groupId: params.groupId };
        } else {
          query = { windowId: params.groupId };
        }
      }
      const tabs = await chrome.tabs.query(query);
      return {
        tabs: tabs.map((t) => ({ id: t.id, url: t.url, title: t.title, groupId: chrome.tabs.group ? t.groupId : t.windowId })),
      };
    }

    case "tab.activate": {
      await chrome.tabs.update(params.tabId, { active: true });
      return { ok: true };
    }

    case "tab.group_by_target": {
      // Resolve a CDP target ID to a Chrome/Firefox tabId, then move it into the group.
      const targets = await new Promise((resolve) => chrome.debugger.getTargets(resolve));
      const target = targets.find((t) => t.tabId != null && t.id === params.targetId);
      if (!target) throw new Error(`CDP target not found: ${params.targetId}`);
      
      if (chrome.tabs.group) {
        await chrome.tabs.group({ tabIds: [target.tabId], groupId: params.groupId });
      } else {
        await chrome.tabs.move(target.tabId, { windowId: params.groupId, index: -1 });
      }
      return { ok: true, tabId: target.tabId };
    }

    // ── Debugger (CDP) ────────────────────────────────────────────────────
    case "cdp.attach": {
      try {
        await chrome.debugger.attach({ tabId: params.tabId }, "1.3");
        return { ok: true, attached: true };
      } catch (err) {
        // Already attached is OK
        if (err.message.includes("already attached") || err.message.includes("Debugger")) {
          return { ok: true, attached: false, message: "Already attached" };
        }
        throw err;
      }
    }

    case "cdp.detach": {
      try {
        await chrome.debugger.detach({ tabId: params.tabId });
        return { ok: true };
      } catch (err) {
        // Not attached is OK
        if (err.message.includes("not attached") || err.message.includes("Debugger")) {
          return { ok: true, message: "Was not attached" };
        }
        throw err;
      }
    }

    case "cdp": {
      return await chrome.debugger.sendCommand(
        { tabId: params.tabId },
        params.method,
        params.params ?? {}
      );
    }

    default:
      throw new Error(`Unknown command: ${type}`);
  }
}

// ---------------------------------------------------------------------------
// Message router
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg._beeline) return;

  // Popup asking for live status
  if (msg.type === "status") {
    chrome.storage.session.get(["wsConnected"]).then((data) => {
      sendResponse({ connected: !!data.wsConnected });
    });
    return true; // keep channel open for async response
  }
});

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

chrome.runtime.onInstalled.addListener(connect);
chrome.runtime.onStartup.addListener(connect);

// Periodic alarm keeps the background script active or reconnects if necessary
chrome.alarms.create("keepAlive", { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepAlive") {
    connect();
  }
});

// Start connection immediately
connect();
