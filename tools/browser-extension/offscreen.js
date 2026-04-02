/**
 * Offscreen document: hosts the persistent WebSocket connection to Hive.
 *
 * MV3 service workers suspend after ~30s of inactivity, which would drop a
 * WebSocket. The offscreen document lives as long as Chrome does and relays
 * messages to/from the background service worker.
 */

const HIVE_WS_URL = "ws://127.0.0.1:9229/bridge";

let ws = null;

function connect() {
  ws = new WebSocket(HIVE_WS_URL);

  ws.onopen = () => {
    chrome.runtime.sendMessage({ _beeline: true, type: "ws_open" });
  };

  ws.onmessage = (event) => {
    chrome.runtime.sendMessage({ _beeline: true, type: "ws_message", data: event.data });
  };

  ws.onclose = () => {
    chrome.runtime.sendMessage({ _beeline: true, type: "ws_close" });
    setTimeout(connect, 2000);
  };

  ws.onerror = () => {
    ws.close();
  };
}

// Forward outbound messages from the service worker onto the WebSocket.
chrome.runtime.onMessage.addListener((msg) => {
  if (msg._beeline && msg.type === "ws_send" && ws?.readyState === WebSocket.OPEN) {
    ws.send(msg.data);
  }
});

connect();
