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

function connect() {
  // Don't try to reconnect too fast
  const delay = Math.min(reconnectAttempts * 1000, 5000);

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
        console.log(`[Beeline] WebSocket closed: code=${event.code}`);
        chrome.runtime.sendMessage({ _beeline: true, type: "ws_close" });
        reconnectAttempts++;
        setTimeout(connect, 2000);
      };

      ws.onerror = (error) => {
        console.error("[Beeline] WebSocket error:", error);
        ws.close();
      };
    } catch (error) {
      console.error("[Beeline] Failed to create WebSocket:", error);
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
      console.warn("[Beeline] Cannot send - WebSocket not connected");
    }
  }
});

connect();
