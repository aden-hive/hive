/**
 * Offscreen document: hosts the persistent WebSocket connection to Hive.
 *
 * MV3 service workers suspend after ~30s of inactivity, which would drop a
 * WebSocket. The offscreen document lives as long as Chrome does and relays
 * messages to/from the background service worker.
 */

const HIVE_WS_URL = "ws://127.0.0.1:9229/bridge";

let ws = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_DELAY = 10000; // Max 10 seconds between attempts

function connect() {
  // Exponential backoff with cap
  const delay = Math.min(reconnectAttempts * 1000, MAX_RECONNECT_DELAY);

  if (reconnectAttempts > 0) {
    console.log(`[Beeline] Reconnecting in ${delay}ms (attempt ${reconnectAttempts + 1})...`);
  }

  setTimeout(() => {
    try {
      ws = new WebSocket(HIVE_WS_URL);

      ws.onopen = () => {
        console.log("[Beeline] WebSocket connected to Hive");
        reconnectAttempts = 0;
        chrome.runtime.sendMessage({ _beeline: true, type: "ws_open" });
      };

      ws.onmessage = (event) => {
        chrome.runtime.sendMessage({ _beeline: true, type: "ws_message", data: event.data });
      };

      ws.onclose = (event) => {
        console.log(`[Beeline] WebSocket closed: code=${event.code}, reason=${event.reason}`);
        chrome.runtime.sendMessage({ _beeline: true, type: "ws_close" });
        reconnectAttempts++;
        // Reconnect after delay
        setTimeout(connect, 2000);
      };

      ws.onerror = () => {
        // Don't log the full error object - it's usually just an Event
        // The actual error will be reflected in onclose
        console.warn(`[Beeline] WebSocket connection failed (server may not be running)`);
        // Don't close here - let onclose handle cleanup
      };
    } catch (error) {
      console.error("[Beeline] Failed to create WebSocket:", error.message);
      reconnectAttempts++;
      setTimeout(connect, 2000);
    }
  }, delay);
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
