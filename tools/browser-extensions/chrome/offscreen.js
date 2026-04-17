/**
 * Offscreen document: hosts the persistent WebSocket connection to Hive.
 *
 * MV3 service workers suspend after ~30s of inactivity, which would drop a
 * WebSocket. The offscreen document lives as long as Chrome does and relays
 * messages to/from the background service worker.
 */

const HIVE_WS_URL = "ws://127.0.0.1:9229/bridge";

let ws = null;
const RETRY_INTERVAL = 2000; // Poll every 2s while disconnected

function connect() {
  try {
    ws = new WebSocket(HIVE_WS_URL);

    ws.onopen = () => {
      console.log("[Beeline] WebSocket connected to Hive");
      chrome.runtime.sendMessage({ _beeline: true, type: "ws_open" });
    };

    ws.onmessage = (event) => {
      chrome.runtime.sendMessage({ _beeline: true, type: "ws_message", data: event.data });
    };

    ws.onclose = (event) => {
      console.log(`[Beeline] WebSocket closed: code=${event.code}, reason=${event.reason}`);
      chrome.runtime.sendMessage({ _beeline: true, type: "ws_close" });
      setTimeout(connect, RETRY_INTERVAL);
    };

    ws.onerror = () => {
      console.warn(`[Beeline] WebSocket connection failed (server may not be running)`);
    };
  } catch (error) {
    console.error("[Beeline] Failed to create WebSocket:", error.message);
    setTimeout(connect, RETRY_INTERVAL);
  }
}

// Forward outbound messages from the service worker onto the WebSocket.
chrome.runtime.onMessage.addListener((msg) => {
  if (msg._beeline && msg.type === "ws_send") {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(msg.data);
    } else {
      console.warn("[Beeline] Cannot send - WebSocket not connected (state: %s)",
        ws ? ws.readyState : "null");
    }
  }
});

// Start connection
connect();
