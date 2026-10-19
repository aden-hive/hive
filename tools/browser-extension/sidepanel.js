/**
 * Hive Browser Bridge — side panel v2.
 *
 * Single source of truth: the bridge's HTTP /status and /contexts endpoints.
 * Per-tab action history comes from /tabs/{tabId}/actions with incremental
 * polling via the `since=` cursor so the bridge never has to ship the full
 * buffer on the 2s tick. The side panel is otherwise stateless — every poll
 * rebuilds from server state.
 */

// ── Constants ──────────────────────────────────────────────────────────────
// Try the current port first; fall back to the legacy 9230 during the
// migration window. The origin that answers is remembered.
const BRIDGE_ORIGINS = ["http://127.0.0.1:14830", "http://127.0.0.1:9230"];
let originIndex = 0;
const POLL_INTERVAL_MS = 2000;

const GROUP_COLORS = {
  grey: "#5f6368",
  blue: "#1a73e8",
  red: "#d93025",
  yellow: "#f9ab00",
  green: "#1e8e3e",
  pink: "#d01884",
  purple: "#9334e6",
  cyan: "#007b83",
  orange: "#fa903e",
};

// ── DOM handles ────────────────────────────────────────────────────────────
const el = (id) => document.getElementById(id);
const $substatus = el("substatus");
const $fixHint = el("fix-hint");
const $tabCard = el("tab-card");
const $agentsSection = el("agents-section");
const $agentsCount = el("agents-count");
const $agents = el("agents");
const $bridgeVersion = el("bridge-version");
const $runtimeVersion = el("runtime-version");

// ── Per-tab action cache ──────────────────────────────────────────────────
// Keyed by tabId. {rows: [entry...], latestTs, expanded: bool}. Incremental
// polling: each tick we fetch since=latestTs and prepend new rows. Clicking
// "Show more" sets expanded=true and we one-shot fetch limit=200.
const tabActionCache = new Map();

// Verdict from the last successful poll. Lets the reconnect handler branch
// without re-fetching, and lets renderers cooperate across functions.
let lastVerdict = { state: "checking", reason: "checking" };
let lastSystemBlocker = null;
let lastRoundTripMs = null;
let lastFocusedTabId = null;
// Per-focused-tab blocker list from /tabs/{id}/health. Re-fetched on every
// poll; cleared on focus change. Renders as a callout above the tab-control
// row so a user landing on a Calendly-injected LinkedIn page sees "Blocked
// by Calendly" with a one-click chrome://extensions affordance.
let focusedTabBlockers = [];
let polling = false;
let popoverOpen = false;
// Set while a fix-hint button action is mid-flight. Suppresses fix-hint
// re-rebuilds for the same verdict reason so the button's pending visual
// state (disabled, "Stopping bridge…") isn't undone by the next pollOnce
// re-rendering identical content before the action takes effect.
let pendingFixHintAction = null;

// ── Generic helpers ────────────────────────────────────────────────────────
function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function shortUrl(url) {
  if (!url) return "";
  try {
    const u = new URL(url);
    let s = u.host + u.pathname;
    if (u.search) s += u.search;
    return s.replace(/\/$/, "");
  } catch (_) {
    return url;
  }
}

function hostOf(url) {
  try {
    return new URL(url).host || url;
  } catch (_) {
    return url || "";
  }
}

function fmtTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function fmtAgo(ms) {
  if (ms == null || !isFinite(ms)) return "";
  const s = Math.round((Date.now() - ms) / 1000);
  if (s < 5) return "now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function fmtSince(ms) {
  // Coarser stamp for "Last action 4m 12s ago — paused" — shows the agent
  // has been quiet a long time. Uses m+s for short ranges.
  if (ms == null || !isFinite(ms)) return "—";
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function agentName(c) {
  return c.name || c._title || c.profile || "agent";
}

function colorFor(c) {
  return c._color || "#9aa0a6";
}

// ── Network ────────────────────────────────────────────────────────────────
async function fetchJson(path, timeoutMs = 2500) {
  for (let attempt = 0; attempt < BRIDGE_ORIGINS.length; attempt++) {
    const origin = BRIDGE_ORIGINS[originIndex];
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), timeoutMs);
      const res = await fetch(origin + path, { signal: ctrl.signal });
      clearTimeout(t);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (_) {
      // Rotate to the other origin for the next attempt.
      originIndex = (originIndex + 1) % BRIDGE_ORIGINS.length;
    }
  }
  return null;
}

async function postJson(path, body, timeoutMs = 4000) {
  for (let attempt = 0; attempt < BRIDGE_ORIGINS.length; attempt++) {
    const origin = BRIDGE_ORIGINS[originIndex];
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), timeoutMs);
      const res = await fetch(origin + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
        signal: ctrl.signal,
      });
      clearTimeout(t);
      const data = await res.json().catch(() => ({}));
      return { ok: res.ok, status: res.status, ...data };
    } catch (_) {
      originIndex = (originIndex + 1) % BRIDGE_ORIGINS.length;
    }
  }
  return { ok: false, error: "network" };
}

// ── Current focused tab ────────────────────────────────────────────────────
// The side panel runs inside a Chrome side-panel window. lastFocusedWindow
// excludes panel-only windows on modern Chrome and points back at the user's
// actual browsing window. Returns the tab object or null.
async function getFocusedTab() {
  try {
    const tabs = await chrome.tabs.query({
      active: true,
      lastFocusedWindow: true,
    });
    return (tabs && tabs[0]) || null;
  } catch (_) {
    return null;
  }
}

// ── Verdict ────────────────────────────────────────────────────────────────
// Server state → a stable {state, reason} the side panel renders against.
// Each reason is grounded in a single directly-observable signal so the rail
// never reports something it can't verify.
//
//   runtime_alive — bridge's direct PID check on HIVE_DESKTOP_PARENT_PID.
//     true:  the desktop app process is running. (Whether it's actively
//            doing work is a separate question — control_rpc_clients
//            answers that, informationally.)
//     false: the bridge is up but the desktop app process is gone. The
//            classic orphan-bridge case — we render runtime_dead and
//            let the user act.
//     null:  bridge has no PID to check (e.g., running outside the
//            Electron shell). Skip the runtime check; fall back to the
//            other signals.
function computeVerdict(status) {
  if (status == null)
    return { state: "disconnected", reason: "server_unreachable" };
  if (status.bridge !== "running")
    return { state: "disconnected", reason: "bridge_stopped" };
  // Direct truth about the desktop app — checked before extension state
  // because a dead runtime is a higher-priority problem than a missing
  // WebSocket. The bridge can still be answering /status during the
  // 30-second watchdog window after the desktop dies; this catches that.
  if (status.runtime_alive === false) {
    return { state: "disconnected", reason: "runtime_dead" };
  }
  if (!status.connected)
    return { state: "disconnected", reason: "not_connected" };
  const sb = status.system_blocker;
  if (sb && sb.kind) {
    return { state: "degraded", reason: "system_blocked", blocker: sb };
  }
  return { state: "healthy", reason: "ok" };
}

// ── Renderers ──────────────────────────────────────────────────────────────

function setNodeState(nodeId, state) {
  // state: "ok" | "warn" | "fail"
  const node = el(nodeId);
  if (!node) return;
  node.classList.remove("warn", "fail", "checking");
  if (state === "warn") node.classList.add("warn");
  else if (state === "fail") node.classList.add("fail");
}

function setLineState(lineId, state) {
  const node = el(lineId);
  if (!node) return;
  node.classList.remove("warn", "fail", "checking");
  if (state === "warn") node.classList.add("warn");
  else if (state === "fail") node.classList.add("fail");
  const check = node.querySelector(".check");
  if (check) check.textContent = state === "fail" ? "✕" : "✓";
}

function setTipBody(tipId, text) {
  const node = el(tipId);
  if (!node) return;
  const body = node.querySelector(".tip-body");
  if (body) body.textContent = text;
}

function renderRail(verdict, status) {
  const reason = verdict.reason;

  // control_rpc_clients is purely informational here — it's the live count
  // of gcu MCP processes currently bound to the bridge. Shown in the Hive
  // tooltip so the user can see who's using the browser, but never drives
  // node colour or the verdict (see computeVerdict).
  const rpcClients = Number(status?.control_rpc_clients || 0);
  const bridgePort = status?.port || 14829;
  const agentsLine =
    rpcClients === 0
      ? "No agents using the browser right now."
      : `${rpcClients} agent${rpcClients === 1 ? "" : "s"} using the browser.`;

  if (reason === "server_unreachable" || reason === "bridge_stopped") {
    setNodeState("node-hive", "fail");
    setLineState("line-hb", "fail");
    setNodeState("node-bridge", reason === "bridge_stopped" ? "warn" : "fail");
    setLineState("line-bb", "fail");
    setNodeState("node-browser", "fail");
    setTipBody(
      "tip-hive",
      reason === "server_unreachable"
        ? "Hive desktop app is closed."
        : "Hive desktop app not reachable via the bridge.",
    );
    setTipBody(
      "tip-bridge",
      reason === "bridge_stopped" ? "Bridge stopped." : "Bridge is down — it runs inside Hive.",
    );
    setTipBody("tip-bb", "Bridge unreachable.");
    setTipBody("tip-browser", "Unknown — bridge offline.");
  } else if (reason === "runtime_dead") {
    // Bridge is up and the extension can talk to it, but the desktop
    // app process itself is gone (verified via direct PID check). The
    // classic orphan-bridge case — the bridge is serving nobody.
    setNodeState("node-hive", "fail");
    setLineState("line-hb", "fail");
    setNodeState("node-bridge", "ok");
    setLineState("line-bb", "ok");
    setNodeState("node-browser", "ok");
    setTipBody("tip-hive", "Hive desktop app isn't running.");
    setTipBody("tip-bridge", `Running on :${bridgePort} (no consumer).`);
    setTipBody("tip-bb", "Extension connected.");
    setTipBody(
      "tip-browser",
      "Debugger available, but Hive isn't there to drive it.",
    );
  } else if (reason === "not_connected") {
    setNodeState("node-hive", "ok");
    setLineState("line-hb", "ok");
    setNodeState("node-bridge", "ok");
    setLineState("line-bb", "fail");
    setNodeState("node-browser", "fail");
    setTipBody("tip-hive", agentsLine);
    setTipBody("tip-bridge", `Running on :${bridgePort}.`);
    setTipBody("tip-bb", "Extension not linked.");
    setTipBody("tip-browser", "Extension not connected to the bridge.");
  } else if (reason === "system_blocked") {
    setNodeState("node-hive", "ok");
    setLineState("line-hb", "ok");
    setNodeState("node-bridge", "ok");
    setLineState("line-bb", "fail");
    setNodeState("node-browser", "fail");
    setTipBody("tip-hive", agentsLine);
    setTipBody("tip-bridge", `Running on :${bridgePort}.`);
    setTipBody("tip-bb", "Browser refusing commands.");
    setTipBody("tip-browser", verdict.blocker?.title || "Browser blocked.");
  } else {
    // healthy
    setNodeState("node-hive", "ok");
    setLineState("line-hb", "ok");
    setNodeState("node-bridge", "ok");
    setLineState("line-bb", "ok");
    setNodeState("node-browser", "ok");
    setTipBody("tip-hive", agentsLine);
    setTipBody("tip-bridge", `Running on :${bridgePort}.`);
    const rtt = lastRoundTripMs;
    setTipBody(
      "tip-bb",
      rtt != null ? `Round-trip · ${Math.round(rtt)} ms` : "Healthy.",
    );
    setTipBody("tip-browser", "Debugger available.");
  }

  // The rail is always a 2-node Hive ↔ Browser view (the Bridge node + its
  // second link are hidden by CSS). The single connector reflects the END-TO-END
  // path, not the hive↔bridge segment the branches above set: red only when the
  // connection is genuinely broken (disconnected), green otherwise — a blocked
  // browser is an endpoint problem (node-browser), not a link problem. The
  // node-hive/node-browser states set per-reason above already show which end is
  // at fault; the specifics live in the node tooltips + the fix-hint text.
  const hbHead = el("tip-hb")?.querySelector(".head");
  if (hbHead) hbHead.textContent = "hive ↔ browser";
  setLineState("line-hb", verdict.state === "disconnected" ? "fail" : "ok");
  const rtt = lastRoundTripMs;
  setTipBody(
    "tip-hb",
    verdict.state === "healthy"
      ? rtt != null
        ? `Round-trip · ${Math.round(rtt)} ms`
        : "Healthy."
      : verdict.state === "degraded"
        ? "Connected — browser blocked."
        : "Not connected.",
  );
}

function renderSubstatusAndFixHint(verdict) {
  // Substatus: short, one-line, only when not healthy.
  const SUBSTATUS = {
    ok: "",
    server_unreachable: "Hive isn't running",
    bridge_stopped: "Browser bridge stopped",
    runtime_dead: "Hive desktop app isn't running",
    not_connected: "Extension not linked to Hive",
    system_blocked: verdict.blocker?.title || "Browser blocked",
    checking: "Running diagnostics…",
  };
  $substatus.textContent = SUBSTATUS[verdict.reason] || "";

  // Fix-hint: shown only when not healthy; copy comes from the blocker
  // (system_blocked) or a static map (other reasons).
  if (verdict.state === "healthy" || verdict.state === "checking") {
    $fixHint.style.display = "none";
    $fixHint.classList.remove("severity-warn");
    return;
  }
  // While a button action for THIS reason is mid-flight, leave the fix-hint
  // alone. Re-rendering identical content would swap the live button (with
  // its disabled + "Stopping…" state) for a fresh one, which is exactly the
  // "blink" the user saw before this guard existed.
  if (
    pendingFixHintAction === verdict.reason &&
    $fixHint.style.display !== "none"
  ) {
    return;
  }
  let head = "",
    body = "";
  if (verdict.reason === "system_blocked" && verdict.blocker) {
    head = verdict.blocker.title || "Hive can't drive the browser";
    body = [verdict.blocker.detail, verdict.blocker.fix]
      .filter(Boolean)
      .join(" ");
    if (verdict.blocker.severity === "warn")
      $fixHint.classList.add("severity-warn");
    else $fixHint.classList.remove("severity-warn");
  } else {
    $fixHint.classList.remove("severity-warn");
    const FIX_HINTS = {
      server_unreachable: [
        "Hive isn't running",
        "The browser bridge runs inside Hive. Open the Hive desktop app to reconnect. If Hive is already running, another program may be holding the bridge ports.",
      ],
      bridge_stopped: ["Bridge stopped", "Restart the Hive app."],
      runtime_dead: [
        "Hive desktop app isn't running",
        "The bridge is still alive from a previous session. Start Hive to use it; the bridge will clean itself up shortly if you don't.",
      ],
      not_connected: [
        "Connection dropped",
        "Press Reconnect. If it keeps failing, make sure the Hive desktop app is running.",
      ],
    };
    [head, body] = FIX_HINTS[verdict.reason] || [
      "Something's off",
      "Press Reconnect.",
    ];
  }
  $fixHint.style.display = "";
  clear($fixHint);
  const h = document.createElement("span");
  h.className = "head";
  h.textContent = head;
  const t = document.createTextNode(" " + body);
  const actions = document.createElement("div");
  actions.className = "actions";
  const btn = document.createElement("button");
  btn.className = "btn-sm primary";
  btn.textContent = "Reconnect";
  btn.addEventListener("click", () => onFixHintAction(btn, verdict));
  actions.append(btn);
  $fixHint.append(h, t, actions);
}

async function onFixHintAction(btn, verdict) {
  // Visible feedback so the click doesn't feel dead. The button stays in
  // its pending state until either (a) the verdict actually transitions —
  // at which point renderSubstatusAndFixHint rebuilds with new content and
  // replaces this button entirely — or (b) we give up after a few rapid
  // follow-up polls and restore the button so the user can retry.
  const originalLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Reconnecting…";
  pendingFixHintAction = verdict.reason;

  try {
    await doReconnect(verdict);
  } catch (_) {
    // doReconnect is best-effort; the follow-up polls below tell us
    // whether the action took effect regardless.
  }

  // Rapid follow-up polls — the next regular 2s tick is too slow for the
  // user to feel responsiveness. Break the moment the verdict reason
  // changes; that's our signal the action worked.
  for (const delay of [250, 600, 1200, 2000, 3000]) {
    await new Promise((r) => setTimeout(r, delay));
    await pollOnce();
    if (lastVerdict.reason !== verdict.reason) break;
  }

  pendingFixHintAction = null;
  // If the verdict didn't transition, this button is still in the DOM and
  // disabled — restore it so the user can try again. If it did transition,
  // renderSubstatusAndFixHint already replaced the button and isConnected
  // is false, so this is a no-op.
  if (btn.isConnected) {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
}

// ── Per-tab blocker banner ────────────────────────────────────────────────
// Render a blocker dict (foreign_extension_frame in practice) as a callout
// in the tab card. Pulls the offender id and human name out of the
// blocker's context — populated by health.py / lookup_extension — so the
// banner can say "Blocked by Calendly" instead of "Blocked by extension
// cbhilkc…". The primary button opens chrome://extensions/?id=<offender>,
// which Chrome scrolls + visually pulses on, so the user lands on the
// exact row to disable. For known offenders we ALSO surface the per-site
// disable hint (e.g. "Click the Calendly toolbar icon…") because that's
// usually faster than the chrome://extensions round trip.
function renderBlockerBanner(blocker) {
  const node = document.createElement("div");
  node.className = "blocker-banner";
  const head = document.createElement("div");
  head.className = "blk-head";
  head.textContent = blocker.title || "Browser action blocked";
  node.append(head);
  if (blocker.detail) {
    const body = document.createElement("div");
    body.className = "blk-body";
    body.textContent = blocker.detail;
    node.append(body);
  }
  const ctx = blocker.context || {};
  const offenderId = ctx.offender_extension_id;
  if (blocker.fix) {
    // Show the bridge-supplied actionable instruction directly. Detail
    // explains WHAT broke; fix tells the user EXACTLY what to do. Keeping
    // them as two visually distinct blocks reads better in a 240px banner
    // than collapsing them into one paragraph.
    const hint = document.createElement("div");
    hint.className = "blk-hint";
    hint.textContent = blocker.fix;
    node.append(hint);
  }
  const actions = document.createElement("div");
  actions.className = "blk-actions";
  if (offenderId) {
    const btn = document.createElement("button");
    btn.className = "btn-sm primary";
    // Use the name only when it's a real one (known offender). For
    // unknowns the name is the placeholder "an unknown extension"
    // which doesn't read right inside a button label.
    const label = ctx.offender_known
      ? `Open ${ctx.offender_name} in chrome://extensions`
      : "Open chrome://extensions";
    btn.textContent = label;
    btn.addEventListener("click", () => openExtensionsPage(offenderId));
    actions.append(btn);
  } else {
    const btn = document.createElement("button");
    btn.className = "btn-sm primary";
    btn.textContent = "Open chrome://extensions";
    btn.addEventListener("click", () => openExtensionsPage(null));
    actions.append(btn);
  }
  node.append(actions);
  return node;
}

async function openExtensionsPage(extId) {
  // chrome.tabs.create on chrome:// URLs is allowed for extensions; the
  // ?id=<id> query string makes Chrome scroll the offender into view and
  // visually pulse its card.
  const url = extId
    ? `chrome://extensions/?id=${extId}`
    : "chrome://extensions";
  try {
    await chrome.tabs.create({ url, active: true });
  } catch (_) {
    // Falling back to a window.open in case the extension lacks the right
    // permission in some Chrome flavour.
    try {
      window.open(url, "_blank");
    } catch (_) {}
  }
}

function ownerOfTab(tabId, contexts) {
  if (!tabId) return null;
  for (const c of contexts) {
    for (const t of c.tabs || []) {
      if (t.id === tabId) return c;
    }
  }
  return null;
}

function renderTabCard(currentTab, contexts, verdict) {
  clear($tabCard);
  if (!currentTab) {
    const e = document.createElement("div");
    e.className = "empty-card";
    e.textContent = "No focused tab.";
    $tabCard.append(e);
    return;
  }

  // Tab header — favicon + title + url.
  const row = document.createElement("div");
  row.className = "tab-row";
  const fav = document.createElement("div");
  fav.className = "favicon";
  if (currentTab.favIconUrl)
    fav.style.backgroundImage = `url("${currentTab.favIconUrl}")`;
  const col = document.createElement("div");
  col.className = "tab-col";
  const title = document.createElement("div");
  title.className = "tab-title";
  title.textContent = currentTab.title || hostOf(currentTab.url) || "Untitled";
  const url = document.createElement("div");
  url.className = "tab-url";
  url.textContent = shortUrl(currentTab.url);
  col.append(title, url);
  row.append(fav, col);
  $tabCard.append(row);

  // Per-tab blocker banner — rendered ABOVE the controlled-by row so the
  // user sees "Blocked by Calendly" before being prompted to hand over a
  // tab nothing can drive. Only block-severity blockers surface here;
  // warns stay quiet to keep the banner uncluttered.
  const blockBlocker = focusedTabBlockers.find(
    (b) => b && b.severity === "block",
  );
  if (blockBlocker) {
    $tabCard.append(renderBlockerBanner(blockBlocker));
  }

  // Controlled-by row.
  const owner = ownerOfTab(currentTab.id, contexts);
  const ctrl = document.createElement("div");
  ctrl.className = "tab-control";
  const dot = document.createElement("div");
  dot.className = "ctrl-dot";
  dot.style.background = owner ? colorFor(owner) : "hsl(40 8% 78%)";
  const text = document.createElement("div");
  text.className = "ctrl-text";

  const suspended = verdict.state !== "healthy" && verdict.state !== "checking";

  if (owner) {
    const labelEl = document.createElement("div");
    labelEl.className = "label";
    labelEl.textContent = "controlled by";
    const agentEl = document.createElement("div");
    agentEl.className = "agent";
    agentEl.textContent = agentName(owner);
    text.append(labelEl, agentEl);
    if (suspended) {
      const warn = document.createElement("div");
      warn.className = "warning";
      warn.textContent =
        verdict.reason === "system_blocked"
          ? "Control suspended — debugger unavailable"
          : "Control suspended — connection unhealthy";
      text.append(warn);
    }
    const releaseBtn = document.createElement("button");
    releaseBtn.className = "btn-sm";
    releaseBtn.textContent = "Pause";
    // Only disable when the connection is genuinely down (no bridge to deliver
    // the command). Pause must stay clickable when control is merely SUSPENDED
    // by a system_blocker (degraded, but WS/bridge healthy): ungrouping a tab is
    // a chrome.tabs API call, not CDP, so reclaiming it from a blocked agent
    // works fine — and that's exactly when a user wants to. Hand over below
    // stays gated on `suspended` (no point handing a tab to a stuck agent).
    releaseBtn.disabled = verdict.state === "disconnected";
    releaseBtn.addEventListener("click", () => doRelease(currentTab.id));
    ctrl.append(dot, text, releaseBtn);
  } else {
    const uncEl = document.createElement("div");
    uncEl.className = "uncontrolled";
    uncEl.textContent = "Not controlled by any agent";
    text.append(uncEl);
    const handoverBtn = document.createElement("button");
    handoverBtn.className = "btn-sm primary";
    handoverBtn.textContent = popoverOpen ? "Hand over ▴" : "Hand over ▾";
    if (suspended) handoverBtn.disabled = true;
    handoverBtn.addEventListener("click", () => {
      popoverOpen = !popoverOpen;
      renderTabCard(currentTab, contexts, verdict);
    });
    ctrl.append(dot, text, handoverBtn);
  }
  $tabCard.append(ctrl);

  // Hand-over popover when applicable.
  if (!owner && popoverOpen) {
    const pop = document.createElement("div");
    pop.className = "popover";
    const popHead = document.createElement("div");
    popHead.className = "pop-head";
    popHead.textContent = "hand over to…";
    pop.append(popHead);
    if (!contexts.length) {
      const e = document.createElement("div");
      e.className = "pop-empty";
      e.textContent = "No agents available.";
      pop.append(e);
    } else {
      for (const c of contexts) {
        const item = document.createElement("div");
        item.className = "pop-item";
        const pdot = document.createElement("div");
        pdot.className = "pdot";
        pdot.style.background = colorFor(c);
        const nm = document.createElement("div");
        nm.className = "nm";
        nm.textContent = agentName(c);
        const role = document.createElement("div");
        role.className = "role";
        role.textContent = c.profile || "";
        item.append(pdot, nm, role);
        item.addEventListener("click", () =>
          doHandover(c.profile, currentTab.id),
        );
        pop.append(item);
      }
    }
    $tabCard.append(pop);
  }

  // Action history — only render the nested section when the tab is owned.
  // An uncontrolled tab has no semantic action history to show.
  if (owner) {
    const history = document.createElement("details");
    history.className = "tab-history";
    // Preserve open/closed across renders by tying it to the cached entry.
    const cached = tabActionCache.get(currentTab.id);
    if (cached && cached.openExpanded) history.open = true;
    const summary = document.createElement("summary");
    summary.textContent = "Action history ";
    const countEl = document.createElement("span");
    countEl.className = "count";
    summary.append(countEl);
    history.append(summary);
    history.addEventListener("toggle", () => {
      const c = tabActionCache.get(currentTab.id) || {};
      c.openExpanded = history.open;
      tabActionCache.set(currentTab.id, c);
    });
    const list = document.createElement("div");
    list.className = "hist-list";
    history.append(list);
    $tabCard.append(history);
    renderHistory(list, countEl, currentTab.id, verdict);
  }
}

function renderHistory(list, countEl, tabId, verdict) {
  clear(list);
  const cached = tabActionCache.get(tabId);
  const rows = (cached && cached.rows) || [];
  const lastTs = cached?.lastActionTs ?? null;
  const count = rows.length;
  countEl.textContent = count ? `· ${count}` : "";

  // Connection unhealthy → show "paused" empty state per the mockup state 3.
  if (verdict.state !== "healthy" && verdict.state !== "checking") {
    const e = document.createElement("div");
    e.className = "hist-empty";
    e.textContent = lastTs
      ? `Last action ${fmtSince(lastTs)} ago — paused.`
      : "No actions yet — paused.";
    list.append(e);
    return;
  }

  if (!rows.length) {
    const e = document.createElement("div");
    e.className = "hist-empty";
    e.textContent = "No actions yet.";
    list.append(e);
    return;
  }

  const displayLimit = cached.expanded ? 200 : 8;
  const shown = rows.slice(0, displayLimit);
  for (const r of shown) {
    const row = document.createElement("div");
    row.className = "hist-row" + (r.ok === false ? " failed" : "");
    const t = document.createElement("div");
    t.className = "t";
    t.textContent = fmtTime(r.ts_ms);
    const v = document.createElement("div");
    v.className = `verb ${r.verb || ""}`;
    v.textContent = r.verb || "";
    const b = document.createElement("div");
    b.className = "body";
    b.textContent = r.target || "";
    row.append(t, v, b);
    list.append(row);
  }
  // Show more — appears when there are rows beyond the current display.
  if (!cached.expanded && count > displayLimit) {
    const foot = document.createElement("div");
    foot.className = "hist-foot";
    const more = document.createElement("button");
    more.className = "more";
    const n = document.createElement("span");
    n.className = "n";
    n.textContent = `${displayLimit} of ${count}`;
    more.append(n, document.createTextNode("Show more ▾"));
    more.addEventListener("click", async () => {
      cached.expanded = true;
      tabActionCache.set(tabId, cached);
      // One-shot fetch to fill the buffer up to its cap.
      await pollActions(tabId, /* full */ true);
      pollOnce(); // re-render
    });
    foot.append(more);
    list.append(foot);
  }
}

function renderAgentRow(c) {
  const row = document.createElement("div");
  row.className = "ag";
  const dot = document.createElement("div");
  dot.className = "dot";
  dot.style.background = colorFor(c);
  const col = document.createElement("div");
  col.className = "col";
  const nm = document.createElement("div");
  nm.className = "nm";
  nm.textContent = agentName(c);
  const tabs = c.tabs || [];
  const active = tabs.find((t) => t.id === c.activeTab);
  const host = active ? active.title || hostOf(active.url) : "";
  const sub = document.createElement("div");
  sub.className = "sub";
  sub.textContent =
    `${tabs.length} tab${tabs.length === 1 ? "" : "s"}` +
    (host ? ` · ${host}` : "");
  col.append(nm, sub);
  const right = document.createElement("div");
  right.className = "right";
  const badge = document.createElement("span");
  const status = c.status || "idle";
  badge.className = `badge ${status}`;
  badge.textContent = status;
  const when = document.createElement("span");
  when.className = "when";
  when.textContent = fmtAgo(c.last_active_ms);
  right.append(badge, when);
  row.append(dot, col, right);
  row.addEventListener("click", () => focusContext(c));
  return row;
}

function renderAgents(contexts) {
  // Only agents that actually have an OPEN BROWSER PAGE are shown (this is what
  // the section's help text promises). A worker that has ended leaves its
  // context lingering in the bridge registry — soft-pruned (groupId=null, no
  // tabs) or awaiting hard cleanup — and `dormant` only flips after 6h of
  // inactivity, so filtering on dormancy alone left ended workers in the list
  // for hours. Requiring a live tab is the right signal: list_contexts only
  // populates `tabs` for a context with a live tab group, so an ended/
  // soft-pruned context has none and is correctly dropped here.
  const active = contexts.filter(
    (c) => !c.dormant && Array.isArray(c.tabs) && c.tabs.length > 0,
  );
  $agentsCount.textContent = active.length ? `· ${active.length}` : "";
  clear($agents);
  if (!active.length) {
    const e = document.createElement("div");
    e.className = "empty-card";
    e.textContent = "No agents using the browser.";
    $agents.append(e);
    return;
  }
  for (const c of active) $agents.append(renderAgentRow(c));
}

function renderFooter(status) {
  const bv = status?.bridge_version;
  const rv = status?.runtime_version;
  if (bv) {
    $bridgeVersion.textContent = `Bridge v${bv}`;
    $bridgeVersion.classList.remove("disconnected");
  } else {
    $bridgeVersion.textContent = "Bridge —";
    $bridgeVersion.classList.add("disconnected");
  }
  if (rv) {
    $runtimeVersion.textContent = `Runtime v${rv}`;
    $runtimeVersion.classList.remove("disconnected");
  } else {
    $runtimeVersion.textContent = "Runtime —";
    $runtimeVersion.classList.add("disconnected");
  }
}

// ── Focus / actions ────────────────────────────────────────────────────────

async function focusContext(c) {
  if (c.activeTab) {
    try {
      await chrome.tabs.update(c.activeTab, { active: true });
    } catch (_) {}
  } else if ((c.tabs || []).length) {
    try {
      await chrome.tabs.update(c.tabs[0].id, { active: true });
    } catch (_) {}
  }
}

async function doHandover(profile, tabId) {
  popoverOpen = false;
  const res = await postJson(
    `/contexts/${encodeURIComponent(profile)}/adopt-tab`,
    { tabId },
  );
  if (!res.ok) {
    // Surface conflicts inline; keep UX low-friction.
    if (res.status === 409) {
      alert(res.error || "Tab is already owned by another agent.");
    } else if (res.code === "unsupported_extension") {
      alert("Update the Hive Browser Bridge Chrome extension to v1.5+.");
    } else {
      alert(res.error || "Couldn't hand over the tab.");
    }
  }
  pollOnce();
}

async function doRelease(tabId) {
  const res = await postJson(`/tabs/${tabId}/release`, {});
  if (!res.ok && res.error) {
    alert(res.error || "Couldn't pause the tab.");
  }
  pollOnce();
}

async function doReconnect(verdict) {
  // Perform the side effect for each reason. The caller handles follow-up
  // polling — running pollOnce here too would rebuild the fix-hint mid-flight
  // and undo the button's pending visual state.
  //   not_connected       → force WS drop+reconnect via the offscreen page.
  //   server_unreachable
  //   / bridge_stopped    → also force WS reconnect. Currently the only path
  //                         the extension can drive: if a desktop-side fix
  //                         has just revived the bridge, this lands on the
  //                         fresh socket without waiting for the offscreen
  //                         backoff timer (up to 30s).
  //   system_blocked      → no-op (WS is fine; debugger is external).
  const reason = verdict?.reason || lastVerdict.reason;
  if (
    reason === "not_connected" ||
    reason === "server_unreachable" ||
    reason === "bridge_stopped"
  ) {
    try {
      chrome.runtime.sendMessage({ _beeline: true, type: "revive_offscreen" });
    } catch (_) {}
  }
}

// ── Action polling ─────────────────────────────────────────────────────────
async function pollActions(tabId, full) {
  if (!tabId) return;
  const cached = tabActionCache.get(tabId) || {
    rows: [],
    lastActionTs: null,
    expanded: false,
  };
  const limit = full ? 200 : 8;
  let path = `/tabs/${tabId}/actions?limit=${limit}`;
  if (!full && cached.lastActionTs != null)
    path += `&since=${cached.lastActionTs}`;
  const res = await fetchJson(path, 2500);
  if (!res || !res.ok) return;
  if (full) {
    // One-shot — replace cached list entirely with the full buffer.
    cached.rows = (res.actions || []).slice();
  } else {
    // Incremental — new entries (descending). Prepend to keep newest first.
    const newRows = res.actions || [];
    if (newRows.length) {
      cached.rows = newRows.concat(cached.rows);
      // Cap cached length so memory doesn't grow unbounded if the user
      // never expands. 200 matches the server-side buffer.
      if (cached.rows.length > 200) cached.rows.length = 200;
    }
  }
  cached.lastActionTs = res.last_action_ts_ms ?? cached.lastActionTs;
  tabActionCache.set(tabId, cached);
}

// ── Anchor-window marker ─────────────────────────────────────────────────────
// A small pill in the "current browser tab" section showing whether THIS window
// is the one Hive opens its agents' tab groups in (window affinity). The side
// panel is per-window, so it just compares its own window to the anchor the
// background reports.
let _panelWindowId = null;

async function getPanelWindowId() {
  if (_panelWindowId != null) return _panelWindowId;
  try {
    _panelWindowId = (await chrome.windows.getCurrent()).id;
  } catch (_) {}
  return _panelWindowId;
}

function queryAnchorWindow() {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(
        { _beeline: true, type: "get_anchor_window" },
        (resp) => {
          if (chrome.runtime.lastError) {
            resolve(null);
            return;
          }
          resolve(
            resp && typeof resp.anchorWindowId === "number"
              ? resp.anchorWindowId
              : null,
          );
        },
      );
    } catch (_) {
      resolve(null);
    }
  });
}

async function updateAnchorPill() {
  const pill = el("anchor-pill");
  if (!pill) return;
  const [mine, anchor] = await Promise.all([
    getPanelWindowId(),
    queryAnchorWindow(),
  ]);
  // Only surface the marker in windows that are NOT the anchor — it's a hint
  // that Hive's tab groups live in a different window. On the anchor window
  // itself (the common case) there's nothing to say, so stay hidden. The pill's
  // text and hover bubble are static markup; we only toggle visibility.
  pill.hidden = anchor == null || (mine != null && anchor === mine);
}

// ── Poll loop ──────────────────────────────────────────────────────────────
async function pollOnce() {
  if (polling) return;
  polling = true;
  try {
    const [status, ctxResp, focused] = await Promise.all([
      fetchJson("/status", 2500),
      fetchJson("/contexts", 3500),
      getFocusedTab(),
    ]);
    const contexts = ctxResp?.contexts || [];
    // Enrich contexts with tab-group colour/title for rendering. The
    // bridge is now responsible for keeping its _context_registry honest
    // (event-driven prune via tab_group_event, registry clear on
    // extension disconnect, plus the 30s sweep as fallback) — the panel
    // trusts whatever /contexts returns instead of double-checking each
    // groupId against chrome.tabGroups. If a stale entry appears here,
    // that's a bridge bug to fix, not something to hide client-side.
    await Promise.all(
      contexts.map(async (c) => {
        if (c.groupId != null) {
          try {
            const grp = await chrome.tabGroups.get(c.groupId);
            c._color = GROUP_COLORS[grp.color] || "#9aa0a6";
            c._title = grp.title || "";
          } catch (_) {
            c._color = "#9aa0a6";
            c._title = "";
          }
        }
      }),
    );

    const verdict = computeVerdict(status);
    lastVerdict = verdict;
    lastSystemBlocker = verdict.blocker || null;
    const prevFocusedId = lastFocusedTabId;
    lastFocusedTabId = focused?.id || null;

    // Per-tab blocker probe for the focused tab. Runs even on uncontrolled
    // tabs because the most useful place to surface "Calendly is blocking
    // this site" is the moment the user lands on it, BEFORE they try to
    // hand it over to an agent that can't drive it. Clear the cache on
    // focus change so we never display blockers from the prior tab during
    // the next tick's in-flight fetch.
    if (focused?.id !== prevFocusedId) focusedTabBlockers = [];
    if (focused?.id) {
      const health = await fetchJson(`/tabs/${focused.id}/health`, 2500);
      if (health && health.ok && Array.isArray(health.blockers)) {
        focusedTabBlockers = health.blockers;
      } else if (focused?.id !== prevFocusedId) {
        // Probe failed on a fresh focus — leave the (already-cleared) cache
        // empty rather than carrying stale rows from another tab.
        focusedTabBlockers = [];
      }
    } else {
      focusedTabBlockers = [];
    }

    // Action polling for the current focused tab — only when it's
    // controlled (otherwise the history section won't render anyway).
    if (focused && ownerOfTab(focused.id, contexts)) {
      const cached = tabActionCache.get(focused.id);
      await pollActions(
        focused.id,
        /* full */ cached?.expanded === true && !cached?.rows?.length,
      );
    }

    renderSubstatusAndFixHint(verdict);
    renderRail(verdict, status);
    renderTabCard(focused, contexts, verdict);
    renderAgents(contexts);
    renderFooter(status);
    updateAnchorPill();

    // "This browser profile" only matters when there's more than one profile to
    // disambiguate — the routing label is noise for the ~90% single-profile
    // user. Show it only when 2+ extensions are talking to the bridge (one per
    // Chrome profile, from status.connections), or while the rename row is open
    // mid-edit. NB: we can't gate on _profileLabel — background.js auto-assigns
    // every profile a stable threeWordId() label, so it's never empty.
    const profileCount = Array.isArray(status?.connections) ? status.connections.length : 0;
    const editRow = el("profile-edit-row");
    const editing = !!editRow && !editRow.hidden;
    const profileSection = el("profile-section");
    if (profileSection) {
      profileSection.hidden = !(profileCount > 1 || editing);
    }
  } catch (_) {
    // Never let the panel go blank — leave the last frame intact.
  } finally {
    polling = false;
  }
}

// ── This-profile card ───────────────────────────────────────────────────────
// Lets the user name THIS Chrome profile (the routing label workers target) and
// star it as the machine's default browser profile. The label lives in
// chrome.storage.local (per-profile); saving it triggers background.js to
// reconnect so the bridge re-keys under the new label.
let _profileLabel = "";
let _profileExtId = null;

let _profileHintTimer = null;
// Hints are transient ACTION feedback ("saved…", "couldn't set default"), not
// persistent status — the inline id and the ★ default toggle are the live
// state. Auto-clear so a confirmation like "default for this machine" can't
// linger and misreport (e.g. after the default profile goes down).
function setProfileHint(text) {
  const h = el("profile-hint");
  if (!h) return;
  h.textContent = text || "";
  if (_profileHintTimer) {
    clearTimeout(_profileHintTimer);
    _profileHintTimer = null;
  }
  if (text) {
    _profileHintTimer = setTimeout(() => {
      h.textContent = "";
      _profileHintTimer = null;
    }, 4000);
  }
}

function updateSaveEnabled() {
  const input = el("profile-label");
  const save = el("profile-save");
  if (!input || !save) return;
  const v = input.value.trim();
  save.disabled = v === "" || v === _profileLabel;
}

// Reflect the stored label in the read-only inline id (default view).
function renderProfileId() {
  const idEl = el("profile-id");
  if (!idEl) return;
  if (_profileLabel) {
    idEl.textContent = _profileLabel;
    idEl.classList.remove("unset");
  } else {
    idEl.textContent = "unnamed";
    idEl.classList.add("unset");
  }
}

// Toggle between the read-only view (id + Edit) and the edit row (input + Save).
function setProfileEditing(editing) {
  const view = el("profile-view");
  const editRow = el("profile-edit-row");
  if (!view || !editRow) return;
  view.hidden = editing;
  editRow.hidden = !editing;
  if (editing) {
    const input = el("profile-label");
    if (input) {
      input.value = _profileLabel;
      updateSaveEnabled();
      input.focus();
      input.select();
    }
  }
}

async function loadProfileIdentity() {
  try {
    const stored = await chrome.storage.local.get([
      "beelineProfileLabel",
      "beelineExtensionId",
    ]);
    _profileLabel = stored.beelineProfileLabel || "";
    _profileExtId = stored.beelineExtensionId || null;
  } catch (_) {
    /* storage unavailable — leave blanks */
  }
  renderProfileId();
  const input = el("profile-label");
  // Don't clobber what the user is mid-typing.
  if (input && document.activeElement !== input) input.value = _profileLabel;
  updateSaveEnabled();
}

async function saveProfileLabel() {
  const input = el("profile-label");
  if (!input) return;
  const v = input.value.trim();
  if (!v || v === _profileLabel) {
    setProfileEditing(false); // nothing to save — just collapse the editor
    return;
  }
  _profileLabel = v;
  try {
    await chrome.storage.local.set({ beelineProfileLabel: v });
  } catch (_) {
    /* best-effort */
  }
  renderProfileId();
  setProfileEditing(false);
  updateSaveEnabled();
  setProfileHint("saved · reconnecting…");
}

async function setProfileAsDefault() {
  if (!_profileLabel) {
    setProfileHint("name this profile first");
    return;
  }
  const res = await postJson("/profiles/default", {
    label: _profileLabel,
    extensionId: _profileExtId,
  });
  setProfileHint(res && res.ok ? "✓ set as default" : "couldn't set default");
  refreshProfileDefault();
}

async function refreshProfileDefault() {
  const btn = el("profile-default");
  if (!btn) return;
  const data = await fetchJson("/profiles");
  const list = data && data.profiles;
  let isDefault = false;
  if (Array.isArray(list)) {
    for (const p of list) {
      const mine =
        (p.label && p.label === _profileLabel) ||
        (p.extension_id && p.extension_id === _profileExtId);
      if (mine && (p.is_default || p.starred)) isDefault = true;
    }
  }
  btn.classList.toggle("is-default", isDefault);
  btn.textContent = isDefault ? "★ default" : "☆ default";
  btn.title = isDefault
    ? "This profile is Hive's default for this machine."
    : "Make this profile Hive's default for this machine.";
}

(function wireProfileCard() {
  const input = el("profile-label");
  const save = el("profile-save");
  const def = el("profile-default");
  const edit = el("profile-edit");
  const cancel = el("profile-cancel");
  if (input) {
    input.addEventListener("input", updateSaveEnabled);
    // Enter saves, Escape cancels the edit.
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); saveProfileLabel(); }
      else if (e.key === "Escape") { e.preventDefault(); setProfileEditing(false); }
    });
  }
  if (save) save.addEventListener("click", saveProfileLabel);
  if (def) def.addEventListener("click", setProfileAsDefault);
  if (edit) edit.addEventListener("click", () => setProfileEditing(true));
  if (cancel) cancel.addEventListener("click", () => setProfileEditing(false));
  // React to a label generated/changed elsewhere (e.g. background.js auto-named
  // this profile on first connect).
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes.beelineProfileLabel) loadProfileIdentity();
  });
})();

// ── Chrome tab focus subscriptions ─────────────────────────────────────────
// Re-poll quickly when the user switches tabs so the panel snaps to the new
// current tab instead of waiting up to 2s for the next tick.
chrome.tabs.onActivated.addListener(() => pollOnce());
chrome.windows.onFocusChanged.addListener(() => pollOnce());
chrome.tabs.onUpdated.addListener((tabId, info) => {
  // Only matters when the focused tab's title or url changed.
  if (tabId === lastFocusedTabId && (info.title || info.url || info.favIconUrl))
    pollOnce();
});

// ── Boot ───────────────────────────────────────────────────────────────────
loadProfileIdentity();
setInterval(refreshProfileDefault, 4000);
refreshProfileDefault();
setInterval(pollOnce, POLL_INTERVAL_MS);
pollOnce();
