/**
 * Offscreen document: hosts the persistent WebSocket connection to Hive.
 *
 * MV3 service workers suspend after ~30s of inactivity, which would drop a
 * WebSocket. The offscreen document lives as long as Chrome does and relays
 * messages to/from the background service worker.
 */

// The bridge listens on the current port and — during the migration window —
// on the legacy 9229. Try the new port first; fall back to 9229 so this build
// still works against an older Hive runtime. connect() rotates ports on each
// failed attempt, so whichever the running bridge offers is found within a
// couple of tries.
const BRIDGE_PORTS = [14829, 9229];
let portIndex = 0;
function bridgeUrl() {
  return `ws://127.0.0.1:${BRIDGE_PORTS[portIndex]}/bridge`;
}

let ws = null;
let reconnectAttempts = 0;
let reconnectTimer = null;

// Wall-clock ms of the last frame received from the server — ANY frame,
// including the server's app-level pings. The popup's health check reads
// this to detect a half-open socket: if the server has gone quiet for far
// longer than its ping interval, the link is dead even though onclose
// never fired and ws.readyState still reads OPEN.
let lastServerMessageAt = 0;

// ── Connection watchdog (two-way health check) ─────────────────────────────
//
// On a half-open socket (TCP dies with no FIN — laptop sleep, NAT reaper, a
// process stealing the port) the bridge's pings never arrive, its close frame
// never arrives, and ws.onclose never fires — the extension would believe it
// is connected forever. So the offscreen page watches `lastServerMessageAt`:
// if NOTHING at all has arrived from the bridge for far longer than its ping
// cadence, the socket is dead and we tear it down so onclose can reconnect.
//
// Each tick we also send our own ping. A current bridge echoes it (the
// reverse-direction half of the two-way check); any bridge has it provoke
// traffic. Crucially the liveness signal is `lastServerMessageAt` — ANY
// inbound frame — not the pong specifically, so an older bridge that doesn't
// echo our ping is never mistaken for a dead connection.
let lastPongAt = 0;            // last bridge → extension pong (display only)
let lastPingSentAt = 0;        // when the current outstanding ping was sent
let lastPingRttMs = null;      // measured ping→pong round-trip, ms (null = unknown)
let heartbeatTimer = null;
const HEARTBEAT_INTERVAL_MS = 10_000;
// The bridge talks to us at least every ~5s when healthy (its app-level
// ping). 35s of total silence is an unambiguously dead socket, not a quiet
// one — comfortably clear of any normal gap.
const SERVER_SILENCE_MS = 35_000;

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    // Half-open detection: the bridge has gone completely silent.
    if (Date.now() - lastServerMessageAt > SERVER_SILENCE_MS) {
      console.warn("[Beeline] No frames from the bridge for 35s — socket is dead, reconnecting");
      try { ws.close(4002, "server_silent"); } catch (_) { /* already closing */ }
      return;
    }
    try {
      lastPingSentAt = Date.now();
      ws.send(JSON.stringify({ type: "ping" }));
    } catch (_) {
      // send() threw — the socket is broken; onclose will follow.
    }
  }, HEARTBEAT_INTERVAL_MS);
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

// Exponential backoff: 250ms, 500ms, 1s, 2s, 4s, ..., capped at 30s. The old
// fixed 2s flooded the runtime log when Hive was intentionally down and never
// gave a slow start any breathing room.
const RECONNECT_BASE_MS = 250;
const RECONNECT_CAP_MS = 30_000;

function nextDelay() {
  const exp = Math.min(RECONNECT_CAP_MS, RECONNECT_BASE_MS * 2 ** reconnectAttempts);
  // Tiny jitter so two extension instances don't reconnect in lockstep.
  return exp + Math.floor(Math.random() * 250);
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  const delay = nextDelay();
  reconnectAttempts += 1;
  // Rotate to the next candidate port so a bridge on either port is found.
  portIndex = (portIndex + 1) % BRIDGE_PORTS.length;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

function connect() {
  try {
    ws = new WebSocket(bridgeUrl());

    ws.onopen = () => {
      reconnectAttempts = 0;
      lastServerMessageAt = Date.now();
      console.log("[Beeline] WebSocket connected to Hive");
      chrome.runtime.sendMessage({ _beeline: true, type: "ws_open" });
      startHeartbeat();
    };

    ws.onmessage = (event) => {
      // Any inbound frame proves the server is still talking to us.
      lastServerMessageAt = Date.now();
      // ping/pong are the two-way health check and are consumed here — they
      // never reach the service worker. WS-layer ping/pong frames are handled
      // automatically by the platform; these are app-level JSON frames.
      try {
        const parsed = JSON.parse(event.data);
        if (parsed && parsed.type === "ping") {
          // Bridge → extension health ping: answer it.
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "pong" }));
          }
          return;
        }
        if (parsed && parsed.type === "pong") {
          // Bridge's reply to our health ping — the reverse-direction proof,
          // and the round-trip time the side panel shows as link latency.
          lastPongAt = Date.now();
          if (lastPingSentAt) {
            lastPingRttMs = lastPongAt - lastPingSentAt;
            lastPingSentAt = 0;
          }
          return;
        }
      } catch (_) {
        // Non-JSON frames fall through to the SW.
      }
      chrome.runtime.sendMessage({ _beeline: true, type: "ws_message", data: event.data });
    };

    ws.onclose = (event) => {
      console.log(`[Beeline] WebSocket closed: code=${event.code}, reason=${event.reason}`);
      stopHeartbeat();
      chrome.runtime.sendMessage({
        _beeline: true,
        type: "ws_close",
        code: event.code,
        reason: event.reason || "",
      });
      scheduleReconnect();
    };

    ws.onerror = () => {
      // onerror is always followed by onclose, which rotates to the next
      // candidate port and schedules the retry. A miss here is routine while
      // probing ports, so don't claim the server is down — just name the port.
      console.warn(`[Beeline] WebSocket connect attempt failed on ${bridgeUrl()}`);
    };
  } catch (error) {
    console.error("[Beeline] Failed to create WebSocket:", error.message);
    scheduleReconnect();
  }
}

// Forward outbound messages from the service worker onto the WebSocket.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || !msg._beeline) return;

  if (msg.type === "ws_send") {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(msg.data);
    } else {
      console.warn("[Beeline] Cannot send - WebSocket not connected (state: %s)",
        ws ? ws.readyState : "null");
    }
    return;
  }

  // Health probe from the popup (via the service worker). Reports the
  // LIVE socket state — the only authoritative local source of truth.
  // A reply arriving at all also proves this offscreen document is alive.
  if (msg.type === "offscreen_probe") {
    sendResponse({
      readyState: ws ? ws.readyState : null,
      lastServerMessageAt,
      lastPongAt,
      lastPingRttMs,
      reconnectAttempts,
      url: bridgeUrl(),
    });
    return true; // keep the channel open for the response
  }

  // Manual reconnect requested from the popup. Tear down the current
  // socket, drop the backoff, and reconnect immediately.
  if (msg.type === "force_reconnect") {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    reconnectAttempts = 0;
    stopHeartbeat();
    if (ws) {
      // Detach handlers first so the stale socket's onclose doesn't
      // race a second scheduleReconnect() against the fresh connect().
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
      try { ws.close(); } catch (_) { /* already closing */ }
      ws = null;
    }
    connect();
    return;
  }

  // Service-worker poke: the background alarm pings us so the offscreen
  // page stays warm and the SW exercises its message channel. A noop on
  // a healthy WS is harmless; on a broken WS the send throws and onclose
  // schedules a reconnect.
  if (msg.type === "ws_keepalive") {
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: "noop" }));
      } catch (_) {
        // ignored — onclose will follow
      }
    }
  }
});

// Start connection
connect();
