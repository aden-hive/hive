/**
 * Hive Browser Bridge - service worker
 *
 * Commands from Hive (via WebSocket through offscreen.js):
 *
 *   context.create  { agentId }           → { groupId, tabId }
 *   context.destroy { groupId }           → { ok, closedTabs }
 *   tab.create      { groupId, url }      → { tabId }
 *   tab.close       { tabId }             → { ok }
 *   tab.list        { groupId? }          → { tabs: [{id,url,title,groupId}] }
 *   tab.activate    { tabId }             → { ok }
 *   tab.reveal      { tabId }             → { ok }   (activate + raise window)
 *   cdp.attach      { tabId }             → { ok }
 *   cdp.detach      { tabId }             → { ok }
 *   cdp             { tabId, method, params } → { ...cdp result }
 *
 * All responses: { id, result } or { id, error }.
 */

import { threeWordId } from "./wordlist.js";

// ---------------------------------------------------------------------------
// Offscreen document (persistent WebSocket host)
// ---------------------------------------------------------------------------

async function ensureOffscreen() {
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
  });
  if (contexts.length === 0) {
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["WORKERS"],
      justification: "Persistent WebSocket connection to Hive GCU server",
    });
  }
}

function wsSend(obj) {
  chrome.runtime.sendMessage({ _beeline: true, type: "ws_send", data: JSON.stringify(obj) });
}

// ---------------------------------------------------------------------------
// Extension identity
// ---------------------------------------------------------------------------

// Stable per-install identifier so the bridge can recognise the same
// extension across reconnects. chrome.storage.local survives extension
// reloads, updates, and Chrome restarts.
// Protocol versions:
//   1 — original command surface.
//   2 — adds tab.audit (raw observation snapshot used by the runtime's
//       health-blocker registry). Older runtimes never call it; newer
//       runtimes feature-gate the call on this version so an old extension
//       doesn't pay a wasted round-trip per attach.
//   3 — adds tabGroup.list (used by the bridge's stale-context sweep) and
//       tab_group_event (outbound, fires on tabGroups.onRemoved so the
//       bridge can prune its registry the instant Chrome drops a group).
//   4 — adds tab.get, tab.adopt, tab.release (Feature 2 / Step 6 —
//       Hand-over). Bridge feature-gates the corresponding POST
//       endpoints so older extensions surface a clear 409 instead of an
//       opaque "Unknown command".
//   5 — context.destroy ungroups before closing and returns persistedGroup
//       (true when Chrome's "Saved Tab Groups" kept an empty chip); context.create
//       accepts recycleGroupId to reuse such a chip instead of minting a new one.
//       Hive-created group titles also carry HIVE_GROUP_MARKER. Bridge
//       feature-gates recycling on protocol >= 5; older extensions behave exactly
//       as before (a fresh chip per session).
//   6 — auto-groups page-spawned tabs (window.open / target="_blank") into their
//       opener's Hive group so they can't escape and leak a renderer; emits a
//       tab_event with reason "regrouped" when it does. Adds tab.listUngrouped
//       (chrome.tabs.query({groupId:-1})) so the bridge's sweep can reap ungrouped
//       Hive tabs that escaped into a new window. Bridge feature-gates the
//       listUngrouped reaper on protocol >= 6; an older bridge ignores the
//       "regrouped" reason harmlessly.
const EXTENSION_PROTOCOL_VERSION = 6;
const EXTENSION_VERSION = (chrome.runtime.getManifest && chrome.runtime.getManifest().version) || "0.0.0";

async function getOrCreateExtensionId() {
  const stored = await chrome.storage.local.get(["beelineExtensionId"]);
  if (stored.beelineExtensionId) return stored.beelineExtensionId;
  const id = (self.crypto && self.crypto.randomUUID) ? self.crypto.randomUUID() : `ext-${Date.now()}-${Math.random()}`;
  await chrome.storage.local.set({ beelineExtensionId: id });
  return id;
}

// Human-readable label identifying THIS Chrome profile to the bridge (sent in
// the hello frame so the bridge can route a worker bound to "linkedin-acct1" to
// the right extension connection). Generated as a friendly 3-word id on first
// run; the user can rename it in the side panel. chrome.storage.local is
// per-profile, so each Chrome profile gets its own stable label.
async function getOrCreateProfileLabel() {
  const stored = await chrome.storage.local.get(["beelineProfileLabel"]);
  if (stored.beelineProfileLabel) return stored.beelineProfileLabel;
  const label = threeWordId();
  await chrome.storage.local.set({ beelineProfileLabel: label });
  return label;
}

// ---------------------------------------------------------------------------
// Command dispatch
// ---------------------------------------------------------------------------

const TAB_GROUP_COLORS = ["blue", "red", "yellow", "green", "pink", "purple", "cyan", "orange", "grey"];

function pickColor(groupId) {
  return TAB_GROUP_COLORS[groupId % TAB_GROUP_COLORS.length];
}

// Invisible (zero-width) marker appended to every Hive-created tab-group title.
// The bridge's forward orphan reaper uses it to recognise Hive-owned groups from
// tabGroup.list — the only group field that survives a registry wipe or a Chrome
// restart — without changing what the user sees in the tab strip. Failure mode
// is safe: a stripped marker only means a Hive group isn't reaped (a leak),
// never a user group wrongly closed. Must match HIVE_GROUP_MARKER in
// tools/src/gcu/browser/bridge.py.
const HIVE_GROUP_MARKER = "\u200b"; // zero-width space (U+200B)

function groupTitle(name) {
  return (name || "Hive Agent") + HIVE_GROUP_MARKER;
}

// True if groupId names a live Hive-owned group (title carries the marker).
// Returns false on any error — a group that's gone is not ours to claim. Used
// by adoptEscapedTab to decide whether a page-spawned tab belongs to Hive.
async function isHiveGroup(groupId) {
  if (groupId == null || groupId < 0) return false;
  try {
    const g = await chrome.tabGroups.get(groupId);
    return (g.title || "").includes(HIVE_GROUP_MARKER);
  } catch (_) {
    return false;
  }
}

// Window affinity: keep ALL of this profile's Hive tab groups in ONE window
// instead of letting each new group pop into whatever window the user last
// focused. chrome.tabs.create() with no windowId targets the last-focused
// window, so with multiple windows open on a profile a fresh group lands
// unpredictably — often hijacking the window the user is actively using.
// The Hive window is the first window a Hive group ever landed in. We cache it
// but ALSO re-derive it from any live Hive-marked group, so it survives a
// service-worker eviction (MV3) and re-establishes if the user closed it.
let _hiveWindowId = null;

async function resolveHiveWindow() {
  // Cached window still open?
  if (_hiveWindowId != null) {
    try {
      await chrome.windows.get(_hiveWindowId);
      return _hiveWindowId;
    } catch (_) {
      _hiveWindowId = null; // user closed it — re-establish below
    }
  }
  // Re-derive from any live Hive-marked group (the first window holding one).
  try {
    const groups = await chrome.tabGroups.query({});
    for (const g of groups) {
      if ((g.title || "").includes(HIVE_GROUP_MARKER)) {
        _hiveWindowId = g.windowId;
        return _hiveWindowId;
      }
    }
  } catch (_) {}
  return null; // no Hive window yet — the caller lets Chrome pick, then records it
}

// Best-effort macOS app name for this Chromium-based browser, so the desktop
// app can raise it via `open -a <name>`. Derived from the UA brand list; Brave
// hides its brand (looks like Chrome) so it falls back to "Google Chrome" —
// the desktop side treats this as a hint and can be overridden by the user.
function detectBrowserApp() {
  try {
    const brands = (navigator.userAgentData && navigator.userAgentData.brands) || [];
    const names = brands.map((b) => b.brand || "");
    if (names.some((n) => /Edge/i.test(n))) return "Microsoft Edge";
    if (names.some((n) => /Opera|OPR/i.test(n))) return "Opera";
    if (names.some((n) => /Brave/i.test(n))) return "Brave Browser";
    if (names.some((n) => /Chromium/i.test(n)) && !names.some((n) => /Google Chrome/i.test(n)))
      return "Chromium";
  } catch (_) {}
  return "Google Chrome";
}


// Prevention for the renderer leak: a tab the PAGE spawns (window.open,
// target="_blank", JS-opened) is created by Chrome, not via tab.create, and
// Chrome may leave it UNGROUPED. An ungrouped tab carries no HIVE_GROUP_MARKER,
// so neither context.destroy (closes only tabs in the group) nor the bridge's
// group reaper can ever close it — it leaks, holding a renderer process. If the
// new tab's opener lives in a Hive group, pull the new tab into that same group
// so teardown always catches it. Fires only when the opener's group is Hive's,
// so a user's own new tab (no opener, or a non-Hive opener) is never touched.
// Fire-and-forget; never throws (grouping can fail under enterprise tab-group
// policy or mid-drag — then the tab stays ungrouped and the bridge's
// listUngrouped backstop reaper handles it).
async function adoptEscapedTab(tab) {
  try {
    if (tab.groupId != null && tab.groupId >= 0) return; // already grouped
    const opener = tab.openerTabId;
    if (opener == null) return; // no opener → can't attribute to Hive
    let openerTab;
    try {
      openerTab = await chrome.tabs.get(opener);
    } catch (_) {
      return; // opener already gone → leave the tab alone
    }
    if (openerTab.groupId == null || openerTab.groupId < 0) return;
    // New-window popups can't be grouped with a tab in another window.
    if (openerTab.windowId !== tab.windowId) return;
    if (!(await isHiveGroup(openerTab.groupId))) return; // opener not Hive's
    // Re-fetch the new tab: settle the onCreated groupId=-1 ordering quirk and
    // lose the race against tab.create's own grouping if it already happened.
    let fresh;
    try {
      fresh = await chrome.tabs.get(tab.id);
    } catch (_) {
      return; // tab vanished mid-flight
    }
    if (fresh.groupId != null && fresh.groupId >= 0) return; // grouped already
    await chrome.tabs.group({ tabIds: [tab.id], groupId: openerTab.groupId });
    // Tell the bridge the settled group so _tab_to_profile / _hive_tab_ids
    // attribute the adopted tab to the owning context.
    postTabEvent("regrouped", tab.id, openerTab.groupId, { active: !!fresh.active });
  } catch (_) {
    // Never let a tab listener throw.
  }
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
      // Create a blank tab then group it so we have a groupId to return. Pin the
      // tab to this profile's Hive window (window affinity) so a new group
      // doesn't pop into whatever window the user is currently focused on. The
      // bridge passes the durable windowId it remembers for this connection
      // (params.windowId); if absent we derive it from a live Hive group.
      const hiveWin = (params.windowId != null) ? params.windowId : await resolveHiveWindow();
      const createProps = { url: "about:blank", active: false };
      if (hiveWin != null) createProps.windowId = hiveWin;
      let tab;
      try {
        tab = await chrome.tabs.create(createProps);
      } catch (_) {
        // The remembered window was closed — fall back to the current window;
        // the response's windowId teaches the bridge the new home.
        _hiveWindowId = null;
        tab = await chrome.tabs.create({ url: "about:blank", active: false });
      }
      // recycleGroupId (protocol 5): adopt an existing — possibly empty, saved —
      // group instead of minting a fresh chip, so Chrome's un-deletable saved
      // groups don't accumulate one-per-session. Fall back to a new group if the
      // recycle target was removed out from under us.
      let groupId;
      if (params.recycleGroupId != null) {
        try {
          groupId = await chrome.tabs.group({ tabIds: [tab.id], groupId: params.recycleGroupId });
        } catch (_) {
          groupId = await chrome.tabs.group({ tabIds: [tab.id] });
        }
      } else {
        groupId = await chrome.tabs.group({ tabIds: [tab.id] });
      }
      await chrome.tabGroups.update(groupId, {
        // displayName is the human-readable queen/colony label; agentId is the
        // stable session id used only as a fallback. groupTitle() appends the
        // invisible HIVE_GROUP_MARKER so the bridge's orphan reaper can tell
        // Hive groups apart from the user's own.
        title: groupTitle(params.displayName ?? params.agentId ?? "Hive Agent"),
        color: pickColor(groupId),
        collapsed: false,
      });
      // ENFORCE the anchor window. Grouping into a recycled saved chip (or a
      // fallback create) can land the group in a DIFFERENT window than the one
      // we anchored to — which would drag Hive's groups into whatever window
      // the user is currently in. If we have an intended window and the group
      // didn't land there, move it back. Only the FIRST group (no anchor yet)
      // is allowed to establish a new window; after that the anchor is sticky.
      let groupWin;
      try {
        groupWin = (await chrome.tabGroups.get(groupId)).windowId;
      } catch (_) {
        groupWin = tab.windowId;
      }
      if (hiveWin != null && groupWin !== hiveWin) {
        try {
          await chrome.tabGroups.move(groupId, { windowId: hiveWin, index: -1 });
          groupWin = hiveWin;
        } catch (_) {
          // Anchor window is gone — accept where it landed; the response
          // windowId below teaches the bridge the new home.
        }
      }
      _hiveWindowId = groupWin;
      return { groupId, tabId: tab.id, windowId: groupWin };
    }

    case "context.destroy": {
      const tabs = await chrome.tabs.query({ groupId: params.groupId });
      if (tabs.length > 0) {
        // Detach debugger from all tabs before closing them.
        await Promise.allSettled(
          tabs.map((t) => chrome.debugger.detach({ tabId: t.id }).catch(() => {}))
        );
        // Ungroup before removing so a NON-saved group empties and Chrome
        // auto-deletes it (same idiom as tab.release). Best-effort: ungroup can
        // no-op under enterprise tab-group policy or mid-drag — proceed to
        // remove regardless.
        await Promise.allSettled(
          tabs.map((t) => chrome.tabs.ungroup(t.id).catch(() => {}))
        );
        await chrome.tabs.remove(tabs.map((t) => t.id));
      }
      // Probe whether the group survived. Chrome's "Saved Tab Groups" keeps an
      // empty chip that MV3 has no API to delete; persistedGroup tells the
      // bridge to recycle this group next time rather than leak a fresh chip.
      let persistedGroup = false;
      try {
        await chrome.tabGroups.get(params.groupId);
        persistedGroup = true;
      } catch (_) {
        // Group is gone — the happy path for non-saved groups.
      }
      return { ok: true, closedTabs: tabs.length, persistedGroup };
    }

    // ── Tab management ────────────────────────────────────────────────────
    case "tab.create": {
      // Create the tab directly in the target group's window so it doesn't
      // flash into the user's focused window before chrome.tabs.group moves it.
      const createProps = { url: params.url ?? "about:blank", active: false };
      if (params.groupId != null) {
        try {
          createProps.windowId = (await chrome.tabGroups.get(params.groupId)).windowId;
        } catch (_) {}
      }
      const tab = await chrome.tabs.create(createProps);
      if (params.groupId != null) {
        await chrome.tabs.group({ tabIds: [tab.id], groupId: params.groupId });
      }
      return { tabId: tab.id };
    }

    case "tab.close": {
      await chrome.debugger.detach({ tabId: params.tabId }).catch(() => {});
      await chrome.tabs.remove(params.tabId);
      return { ok: true };
    }

    case "tab.list": {
      const query = params.groupId != null ? { groupId: params.groupId } : {};
      const tabs = await chrome.tabs.query(query);
      return {
        tabs: tabs.map((t) => ({ id: t.id, url: t.url, title: t.title, groupId: t.groupId })),
      };
    }

    case "tab.activate": {
      await chrome.tabs.update(params.tabId, { active: true });
      return { ok: true };
    }

    case "tab.reveal": {
      // User-initiated jump-to-tab: focus the tab AND raise its window so the
      // person actually lands on it. Agents use tab.activate (no window focus)
      // so automated actions never steal the user's foreground.
      //
      // chrome.windows.update({focused}) is one cross-platform API, but the OS
      // governs whether Chrome actually comes forward over the Hive app:
      // macOS raises it, Windows/Linux often downgrade to a taskbar flash under
      // focus-stealing prevention. We can't override that from here (it'd need
      // OS-level activation from the Electron main process) — but we DO restore
      // a minimized window, which `focused` alone doesn't do on any platform.
      await chrome.tabs.update(params.tabId, { active: true });
      let info = { ok: true, revealed: false };
      try {
        const t = await chrome.tabs.get(params.tabId);
        if (t.windowId != null) {
          const w = await chrome.windows.get(t.windowId);
          const update = { focused: true };
          if (w.state === "minimized") update.state = "normal";
          const updated = await chrome.windows.update(t.windowId, update);
          info = {
            ok: true,
            revealed: true,
            windowId: t.windowId,
            prevState: w.state,
            newState: updated.state,
            focused: updated.focused,
            // macOS app name so the desktop app can raise this browser at the
            // OS level (the extension can't pull itself over the Hive window).
            browserApp: detectBrowserApp(),
          };
          console.log("[hive] tab.reveal", info);
        }
      } catch (e) {
        console.warn("[hive] tab.reveal failed", e);
        info = { ok: true, revealed: false, error: String(e) };
      }
      return info;
    }

    // ── Tab adoption / release (Feature 2 — Hand-over) ───────────────────
    //
    // The bridge owns the conflict policy (refuse if tab already in another
    // agent's group); the extension is a thin executor. Returns the
    // resulting tab info so the bridge can confirm the move stuck.
    case "tab.get": {
      const tab = await chrome.tabs.get(params.tabId);
      return {
        id: tab.id,
        groupId: tab.groupId,
        url: tab.url || "",
        title: tab.title || "",
        active: !!tab.active,
        windowId: tab.windowId,
      };
    }

    case "tab.adopt": {
      // Move an existing tab into the target group. The "groupId" param is
      // mandatory and refers to a tab group the bridge already owns. If the
      // tab is already in that group, this is a no-op at Chrome's level.
      await chrome.tabs.group({ tabIds: [params.tabId], groupId: params.groupId });
      const tab = await chrome.tabs.get(params.tabId);
      return { ok: true, tabId: tab.id, groupId: tab.groupId };
    }

    case "tab.release": {
      // Remove a tab from whatever group it's in. Chrome auto-removes the
      // group when its last tab leaves, firing tabGroups.onRemoved — the
      // bridge's _prune_group then cleans the registry entry.
      //
      // We follow up with chrome.tabs.get so the bridge can verify the
      // ungroup actually took. chrome.tabs.ungroup can resolve without
      // throwing yet leave the tab in its original group on some
      // Chromium forks, under enterprise tab-group policy, or mid-drag —
      // returning the post-call groupId lets the bridge detect that
      // instead of optimistically reporting ok.
      await chrome.tabs.ungroup(params.tabId);
      let postGroupId = -1;
      try {
        const t = await chrome.tabs.get(params.tabId);
        postGroupId = t.groupId;
      } catch (_) {
        // Tab vanished between ungroup and get — treat as released.
      }
      return { ok: true, tabId: params.tabId, groupId: postGroupId };
    }

    // ── Tab-group enumeration (used by the bridge's stale-context sweep) ─
    //
    // Returns the live tab groups Chrome currently has, so the bridge can
    // reconcile its _context_registry against ground truth and drop entries
    // whose groupIds were closed out-of-band. Lightweight: O(N) over groups.
    case "tabGroup.list": {
      const groups = await chrome.tabGroups.query({});
      return {
        groups: groups.map((g) => ({
          id: g.id,
          title: g.title || "",
          color: g.color || "",
          collapsed: !!g.collapsed,
          windowId: g.windowId,
        })),
      };
    }

    // ── Ungrouped-tab enumeration (protocol 6 — renderer-leak backstop) ──
    //
    // tabGroup.list only surfaces grouped tabs, so an escaped Hive tab that
    // landed UNGROUPED (a new-window popup adoptEscapedTab couldn't group) is
    // invisible to the bridge's group reaper. This returns the loose tabs
    // (chrome.tabs.TAB_GROUP_ID_NONE === -1) so the bridge can intersect them
    // with the set of tab ids it knows were Hive's and reap the orphans.
    case "tab.listUngrouped": {
      const tabs = await chrome.tabs.query({ groupId: -1 });
      return {
        tabs: tabs.map((t) => ({ id: t.id, windowId: t.windowId, url: t.url || "" })),
      };
    }

    case "tab.group_by_target": {
      // Resolve a CDP target ID to a Chrome tabId, then move it into the group.
      const targets = await new Promise((resolve) => chrome.debugger.getTargets(resolve));
      const target = targets.find((t) => t.tabId != null && t.id === params.targetId);
      if (!target) throw new Error(`CDP target not found: ${params.targetId}`);
      await chrome.tabs.group({ tabIds: [target.tabId], groupId: params.groupId });
      return { ok: true, tabId: target.tabId };
    }

    // ── Tab audit (raw observation, no judgement) ─────────────────────────
    //
    // Returns a flat snapshot of everything the Python-side blocker registry
    // needs to classify "why might automation be blocked on this tab" — frame
    // URLs/extension ids, main URL, incognito flag, file-scheme access. The
    // extension intentionally makes no judgement here; health.py owns policy.
    case "tab.audit": {
      const tabId = params.tabId;
      const out = {
        tabId,
        url: "",
        incognito: false,
        ourExtensionId: chrome.runtime.id,
        fileAccess: null,
        targets: [],
        cdpFrames: null,
      };
      try {
        const tab = await chrome.tabs.get(tabId);
        out.url = tab.url || tab.pendingUrl || "";
        out.incognito = !!tab.incognito;
      } catch (_) {
        // Tab gone — surface what we have; the caller's classify() will see
        // no useful signals and the upstream error tells the real story.
      }
      try {
        out.fileAccess = await chrome.extension.isAllowedFileSchemeAccess();
      } catch (_) {
        // API may be unavailable in some Chrome variants — leave null.
      }
      try {
        const all = await new Promise((resolve) => chrome.debugger.getTargets(resolve));
        out.targets = all
          .filter((t) => t.tabId === tabId)
          .map((t) => ({
            url: t.url || "",
            type: t.type || "",
            extensionId: t.extensionId || null,
            attached: !!t.attached,
          }));
      } catch (_) {
        // Targets API is normally available; ignore failures.
      }
      // Page.getFrameTree catches in-process iframes that don't appear as
      // separate debugger targets. Best-effort — fails when the foreign-frame
      // block is already in effect, which is fine: targets[] still names the
      // culprit by extensionId, and the error string drives the reactive rule.
      try {
        const tree = await chrome.debugger.sendCommand(
          { tabId },
          "Page.getFrameTree",
          {}
        );
        const frames = [];
        const walk = (node) => {
          if (node && node.frame) {
            frames.push({
              url: node.frame.url || "",
              securityOrigin: node.frame.securityOrigin || "",
            });
          }
          (node && node.childFrames ? node.childFrames : []).forEach(walk);
        };
        walk(tree.frameTree);
        out.cdpFrames = frames;
      } catch (_) {
        // Common: debugger not attached, or the very foreign-frame condition
        // we're trying to detect is blocking CDP. Leave cdpFrames null.
      }
      // PAGE-DOM probe via chrome.scripting.executeScript with a STATIC
      // function. This is the ONLY path that reveals foreign-extension
      // iframes when Chrome's other introspection APIs scrub them:
      // running `document.querySelectorAll('iframe, frame')` inside the
      // page world sees them as regular DOM nodes regardless of who
      // injected them. The function is static (no `eval` / no
      // `new Function`), so Chrome treats it as extension-source code and
      // the page's CSP doesn't block it — that's the workaround for the
      // 2026-05-26 "unsafe-eval not allowed" wall we hit when the func
      // tried to eval a caller-supplied expression string.
      //
      // Skipped silently when ``scripting`` permission isn't granted yet
      // (e.g. the extension was reloaded mid-migration); the other audit
      // paths still fill in what they can.
      if (chrome.scripting && chrome.scripting.executeScript) {
        try {
          const results = await chrome.scripting.executeScript({
            target: { tabId, allFrames: false },
            world: "MAIN",
            func: () => {
              try {
                const all = document.querySelectorAll("iframe, frame");
                const out = [];
                for (let i = 0; i < all.length; i++) {
                  const f = all[i];
                  out.push({ src: f.src || "", id: f.id || "", name: f.name || "" });
                }
                return out;
              } catch (e) {
                return { __error: String((e && e.message) || e) };
              }
            },
          });
          const r = results && results[0] && results[0].result;
          if (Array.isArray(r)) {
            out.domFrames = r;
          }
        } catch (_) {
          // chrome.scripting can throw on chrome:// pages, the Web Store,
          // PDFs, etc. — every place where we can't run page scripts. Not
          // a culprit case; leave domFrames absent.
        }
      }
      return out;
    }

    // ── Debugger (CDP) ────────────────────────────────────────────────────
    case "cdp.attach": {
      try {
        await chrome.debugger.attach({ tabId: params.tabId }, "1.3");
        // Track for the LRU reaper — an attached tab must not be discarded
        // while an agent is driving it.
        hiveAttachedTabs.add(params.tabId);
        return { ok: true, attached: true };
      } catch (err) {
        // Already attached is OK
        if (err.message.includes("already attached") || err.message.includes("Debugger")) {
          // Same reaper-tracking invariant: even if OUR attach was a no-op
          // because it was already attached, mark it — the queen relies on
          // the debugger being live.
          hiveAttachedTabs.add(params.tabId);
          return { ok: true, attached: false, message: "Already attached" };
        }
        throw err;
      }
    }

    case "cdp.detach": {
      try {
        await chrome.debugger.detach({ tabId: params.tabId });
        hiveAttachedTabs.delete(params.tabId);
        return { ok: true };
      } catch (err) {
        // Not attached is OK
        if (err.message.includes("not attached") || err.message.includes("Debugger")) {
          hiveAttachedTabs.delete(params.tabId);
          return { ok: true, message: "Was not attached" };
        }
        throw err;
      }
    }

    case "cdp": {
      // A live CDP command from the queen means this tab is in-flight; treat
      // it as a "touch" for the LRU. This handles the case where an agent
      // drives a background tab for minutes without activating it — without
      // this the LRU threshold would trigger a discard mid-conversation.
      hiveTouchTab(params.tabId);
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
//
// The popup deliberately does NOT route its health check through here — it
// reads the bridge's HTTP /status endpoint directly, so a busy or suspended
// service worker can never make a live connection look dead. This listener
// only handles the WebSocket relay and an offscreen-revive request.

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg._beeline) return;

  // Side panel asks which window holds this profile's Hive tab groups, so it
  // can show a small "anchor window" marker when it's the one. resolveHiveWindow
  // re-derives from a live Hive group if the SW was evicted, so the answer is
  // accurate even after a restart. Async → return true to keep the channel open.
  if (msg.type === "get_anchor_window") {
    resolveHiveWindow().then((w) => {
      try {
        sendResponse({ anchorWindowId: w });
      } catch (_) {}
    });
    return true;
  }

  if (msg.type === "ws_open") {
    Promise.all([getOrCreateExtensionId(), getOrCreateProfileLabel()]).then(
      ([extensionId, profileLabel]) => {
        wsSend({
          type: "hello",
          version: EXTENSION_VERSION,
          protocolVersion: EXTENSION_PROTOCOL_VERSION,
          extensionId,
          // The Chrome profile's routing label (protocol >= 5). Older bridges
          // ignore the extra field and fall back to the "default" profile.
          profileLabel,
        });
      }
    );
    return;
  }

  if (msg.type === "ws_message") {
    handleCommand(JSON.parse(msg.data));
    return;
  }

  // Popup pressed Reconnect. The popup also messages the offscreen document
  // directly; this path additionally recreates it if it was evicted (only
  // the service worker can call chrome.offscreen.createDocument).
  if (msg.type === "revive_offscreen") {
    ensureOffscreen()
      .then(() => {
        try {
          chrome.runtime.sendMessage({ _beeline: true, type: "force_reconnect" });
        } catch (_) {
          // Offscreen still spinning up — its own connect() runs on load.
        }
      })
      .catch(() => {});
    return;
  }
});

// When the user renames this profile in the side panel, reconnect so the bridge
// re-handshakes and re-keys the connection under the new label. A full
// reconnect (vs a bare re-hello) guarantees the bridge drops the old label
// cleanly instead of leaving it as a dangling alias.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local" || !changes.beelineProfileLabel) return;
  const { oldValue, newValue } = changes.beelineProfileLabel;
  if (oldValue === newValue) return;
  try {
    chrome.runtime.sendMessage({ _beeline: true, type: "force_reconnect" });
  } catch (_) {
    // Offscreen may be spinning up — its own connect() sends the new label.
  }
});

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

chrome.runtime.onInstalled.addListener(ensureOffscreen);
chrome.runtime.onStartup.addListener(ensureOffscreen);

// Clicking the toolbar icon opens the side panel (there is no popup). The
// side panel hosts the connection health UI and stays docked while the user
// works — see sidepanel.html.
if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((err) => console.warn("[Beeline] setPanelBehavior failed:", err));
}

// ---------------------------------------------------------------------------
// CDP event forwarder — diagnostic channel
// ---------------------------------------------------------------------------
//
// chrome.debugger.sendCommand (the cdp handler above) only responds to
// requests. CDP also emits unsolicited EVENTS (Runtime.consoleAPICalled,
// Page.frameResized, Target.targetInfoChanged, …) that the bridge doesn't
// see today. Forward the narrow subset we're currently diagnosing so the
// Python side can correlate viewport changes with page lifecycle events.
// Filtered at the source to keep the wire slim.
const FORWARDED_CDP_EVENTS = new Set([
  "Runtime.consoleAPICalled",
  "Page.lifecycleEvent",
  "Page.frameResized",
  "Page.frameNavigated",
  "Target.targetInfoChanged",
  // When chrome.debugger is attached, native dialogs (alert/confirm/prompt/
  // beforeunload) are no longer auto-handled by Chrome — they sit open
  // pausing the page until Page.handleJavaScriptDialog is sent. Forward
  // these so the bridge can track pending dialogs and short-circuit the
  // navigation poll loop instead of timing out at 30s.
  "Page.javascriptDialogOpening",
  "Page.javascriptDialogClosed",
]);

chrome.debugger.onEvent.addListener((source, method, params) => {
  if (!FORWARDED_CDP_EVENTS.has(method)) return;
  wsSend({
    type: "cdp_event",
    tabId: source.tabId,
    method,
    params: params ?? {},
  });
});

// ---------------------------------------------------------------------------
// Tab event forwarder
// ---------------------------------------------------------------------------
//
// chrome.tabs.* events tell the Python lifecycle registry about tabs that
// appear or move outside our explicit tab.create/tab.activate commands —
// target="_blank" clicks, window.open popups, manual user activations. The
// bridge filters by groupId so only events in groups we own update _contexts.
//
// onCreated fires before Chrome has assigned the new tab to its inherited
// group (groupId is -1 in the initial event), so onUpdated re-emits with
// the settled groupId. The bridge handler is idempotent — duplicates are
// safe.

function postTabEvent(eventName, tabId, groupId, extras) {
  const payload = {
    type: "tab_event",
    event: eventName,
    tabId,
    groupId: groupId == null ? -1 : groupId,
  };
  if (extras) Object.assign(payload, extras);
  wsSend(payload);
}

chrome.tabs.onCreated.addListener((tab) => {
  postTabEvent("created", tab.id, tab.groupId, {
    openerTabId: tab.openerTabId ?? null,
    url: tab.pendingUrl || tab.url || "",
    active: !!tab.active,
  });
  // Prevention: pull a page-spawned tab into its opener's Hive group so it
  // can't escape and leak a renderer. No-op unless the opener is Hive's.
  void adoptEscapedTab(tab);
});

chrome.tabs.onAttached.addListener((tabId) => {
  // A tab moved into another window (a popup that settled its window after
  // creation, or a drag) doesn't re-fire onCreated; retry adoption so a tab
  // that lands in a Hive group's window still gets pulled in.
  chrome.tabs.get(tabId, (tab) => {
    if (chrome.runtime.lastError || !tab) return;
    void adoptEscapedTab(tab);
  });
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  // Only forward when the tab actually changed groups — onUpdated otherwise
  // fires for every URL/title/favicon/status tick and would flood the wire.
  if (changeInfo.groupId === undefined) return;
  postTabEvent("grouped", tabId, tab.groupId, { active: !!tab.active });
});

chrome.tabs.onActivated.addListener((activeInfo) => {
  chrome.tabs.get(activeInfo.tabId, (tab) => {
    if (chrome.runtime.lastError || !tab) return;
    postTabEvent("activated", tab.id, tab.groupId);
  });
});

chrome.tabs.onRemoved.addListener((tabId) => {
  // groupId is unavailable here (the tab is already gone); the bridge
  // clears the id from any ctx that still tracks it.
  postTabEvent("removed", tabId, null);
});

// Tab-group lifecycle forwarder. The bridge owns _context_registry — a
// profile→groupId map — and previously had no way to know when Chrome
// dropped a group out from under it (user closed every tab, dragged the
// last one out, etc.). Without this signal stale rows lingered in the
// side panel until the next reconnect. The bridge listens for "removed"
// here and prunes the matching registry entry the moment Chrome reports
// the group is gone; the periodic tabGroup.list sweep is the belt-and-
// braces fallback for events lost during a disconnect.
chrome.tabGroups.onRemoved.addListener((group) => {
  wsSend({
    type: "tab_group_event",
    event: "removed",
    groupId: group.id,
    windowId: group.windowId,
  });
});

// ---------------------------------------------------------------------------
// LRU tab reaper — proactively free renderers before the kernel has to
// ---------------------------------------------------------------------------
//
// Chrome runs inside a cgroup v2 slice (chrome.slice, memory.max=2 GiB) on
// the sandbox VM (see sandbox-images/hive-novnc/start-chrome.sh in the infra
// repo). When Chrome exceeds the ceiling, the kernel picks a renderer
// inside the slice and SIGKILLs it — the tab then shows Chrome's "Aw, Snap!"
// splash. That's the SAFETY NET, not the goal. The goal is to release
// renderers of idle tabs BEFORE we hit the ceiling, using chrome.tabs.discard(),
// which drops the renderer while keeping the tab in the tab strip; re-
// activation navigates the tab and cleanly re-spawns a renderer.
//
// What "idle" means here:
//   - Not active in any window (the currently-focused tab per-window is off-limits)
//   - Not audible (playing audio/video)
//   - Not pinned (user-signal that this tab shouldn't disappear)
//   - Not already discarded
//   - No chrome.debugger session attached (an agent might be driving it via
//     CDP without activating it; discarding auto-detaches the debugger and
//     the queen's next CDP command would fail. This is the critical safety.)
//   - Last "touched" (activated / navigated to complete / created) more than
//     IDLE_MS ago, OR the total count of live-backed tabs exceeds
//     MAX_TABS_TOTAL (in which case we discard oldest-first even if under
//     IDLE_MS).
//
// Cap scope (changed 2026-07-05): the cap now applies to ALL live-backed
// tabs, not just tabs whose current groupId is in a Hive-marked group.
// Reason: 2026-07-04 investigation on team 14034's v73 sandbox found 8
// active renderers with 0 Hive groups reported. The old cap was scoped to
// tabs whose groupId's title carries HIVE_GROUP_MARKER; page-window.open
// escapees into new windows, plus tabs orphaned by context.destroy races
// or bridge_host restarts, were invisible to it. Those ex-agent tabs sat
// forever, holding renderers. Global cap closes the hole without needing
// _hive_tab_ids membership tracking.
//
// Numbers are tuned for the 2 GiB cage:
//   IDLE_MS = 2 min           — was 5 min. Short enough that a stray
//                               research tab dies before it eats real
//                               memory; still long enough that a queen
//                               reading a page for a couple minutes isn't
//                               reaped mid-thought.
//   MAX_TABS_TOTAL = 3        — 3 tabs × ~384 MiB V8 heap + browser proc
//                               + GPU proc + Xvfb overhead fits well under
//                               the 2 GiB cgroup ceiling with slack.
//                               Queue-like flow (open one, read, close/
//                               discard, open next) is the intended usage.
//   REAP_PERIOD_MIN = 0.5     — was 1. chrome.alarms allows 30 s in stable
//                               MV3 as of 2024; Chrome MV3 SW keepAlive
//                               fires at 24 s so a 30 s sweep is safe.

const HIVE_IDLE_MS = 2 * 60 * 1000;
const HIVE_MAX_TABS_TOTAL = 3;
const HIVE_REAP_ALARM = "hive-reap-idle-tabs";
// Escalation policy: chrome.tabs.discard is silently refused by pages with
// beforeunload handlers or active downloads. After N failed discards we
// escalate to chrome.tabs.remove — an unconditional close. beforeunload
// on an agent tab is almost always a leaked SPA (docs, editors, chat) and
// is a false signal; two idle sweeps in a row is enough certainty.
const HIVE_DISCARD_FAIL_ESCALATION_THRESHOLD = 2;

// tabId → epoch ms of most recent "touch" (activation / navigation complete /
// creation). Note (2026-07-05): a tab with no entry USED to be treated as
// just-seen (?? now), which meant every SW respawn granted every existing
// tab a fresh IDLE_MS grace. The seedHiveTabLastSeen IIFE below now seeds
// all tabs at startup with a 30 s grace instead, so unknown tabs after
// startup are the rare case (races with tab creation). Missing entries
// are still tolerated safely via ?? now to avoid a false-positive reap.
const hiveTabLastSeen = new Map();
// tabId set of active CDP debugger sessions. A discard would detach the
// debugger; the queen's next CDP command would then fail. Track membership
// so the reaper can skip these.
const hiveAttachedTabs = new Set();
// tabId → consecutive-refused-discard count. Chrome refuses to discard tabs
// with a beforeunload handler / active download; when the count reaches
// HIVE_DISCARD_FAIL_ESCALATION_THRESHOLD we call chrome.tabs.remove instead.
const hiveDiscardFailCount = new Map();

function hiveTouchTab(tabId) {
  if (typeof tabId === "number" && tabId >= 0) {
    hiveTabLastSeen.set(tabId, Date.now());
  }
}

function hiveForgetTab(tabId) {
  hiveTabLastSeen.delete(tabId);
  hiveAttachedTabs.delete(tabId);
  hiveDiscardFailCount.delete(tabId);
}

// Snapshot of which tab groups are Hive-marked. tabGroups.query gives us the
// authoritative view; we recompute per sweep so a user manually removing the
// marker (or Chrome auto-recreating a saved group) is picked up next tick.
// Still used by the sweep log line — no longer used to gate the cap.
async function hiveGroupIdSet() {
  try {
    const groups = await chrome.tabGroups.query({});
    const s = new Set();
    for (const g of groups) {
      if ((g.title || "").includes(HIVE_GROUP_MARKER)) s.add(g.id);
    }
    return s;
  } catch (_) {
    return new Set();
  }
}

async function hiveReapIdleTabs() {
  let tabs;
  try {
    tabs = await chrome.tabs.query({});
  } catch (_) {
    return;
  }
  const hiveGroups = await hiveGroupIdSet();
  const now = Date.now();
  const live = tabs.filter((t) => !t.discarded);
  const discarded = tabs.length - live.length;
  // Build the eligibility list. chrome.tabs.discard is best-effort at the
  // API layer (fails silently on beforeunload, active downloads, etc.); we
  // skip the obvious "don't touch" cases here, then escalate refused
  // discards below to chrome.tabs.remove.
  const eligible = [];
  let hiveGroupTabs = 0;
  let ungroupedTabs = 0;
  for (const t of live) {
    if (t.groupId != null && hiveGroups.has(t.groupId)) hiveGroupTabs++;
    else ungroupedTabs++;
    if (t.active || t.audible || t.pinned) continue;
    if (hiveAttachedTabs.has(t.id)) continue;
    const seen = hiveTabLastSeen.get(t.id) ?? now; // absent → treat as just-seen
    eligible.push({ tabId: t.id, seen });
  }
  eligible.sort((a, b) => a.seen - b.seen); // oldest first

  // Cap: applies to ALL live-backed tabs (agent + user + orphan). No Hive-
  // group scoping — see block comment above for why the previous scoped-cap
  // let ungrouped orphans accumulate.
  const overCap = Math.max(0, eligible.length - HIVE_MAX_TABS_TOTAL);
  const capReaps = eligible.slice(0, overCap).map((e) => e.tabId);

  // Idle reap: any eligible tab past the idle window. Memory hygiene for
  // tabs under the cap but sitting cold.
  const idleReaps = eligible
    .filter((e) => now - e.seen > HIVE_IDLE_MS)
    .map((e) => e.tabId);

  const toDiscard = new Set([...capReaps, ...idleReaps]);
  const summary = {
    live: live.length,
    discarded,
    hiveGroupTabs,
    ungroupedTabs,
    capReaps: capReaps.length,
    idleReaps: idleReaps.length,
    discardCalls: 0,
    removeEscalations: 0,
  };
  if (toDiscard.size === 0) {
    console.info("[hive.reaper.sweep]", summary);
    return;
  }

  await Promise.all(
    [...toDiscard].map(async (tabId) => {
      summary.discardCalls++;
      try {
        await chrome.tabs.discard(tabId);
      } catch (_) {
        // Chrome refused via a thrown error. Fall through to the re-query
        // below — it will land in the "still not discarded" branch.
      }
      // Verify the discard actually took. Chrome silently no-ops on some
      // tabs (beforeunload, active downloads, form entry). Re-query and
      // decide whether to escalate to remove().
      let after;
      try {
        after = await chrome.tabs.get(tabId);
      } catch (_) {
        // Tab is gone (Chrome closed it, user closed it, race with
        // onRemoved). Nothing to do — the onRemoved listener has already
        // cleared hiveTabLastSeen / hiveAttachedTabs / hiveDiscardFailCount.
        return;
      }
      if (after.discarded) {
        hiveDiscardFailCount.delete(tabId);
        return;
      }
      // Discard was refused. Increment fail count; escalate if we've been
      // trying long enough.
      const fails = (hiveDiscardFailCount.get(tabId) ?? 0) + 1;
      if (fails >= HIVE_DISCARD_FAIL_ESCALATION_THRESHOLD) {
        summary.removeEscalations++;
        try {
          await chrome.tabs.remove(tabId);
        } catch (_) {
          // Even remove can fail (tab already gone, extension policy). Not
          // an error — next sweep will re-evaluate.
        }
        hiveDiscardFailCount.delete(tabId);
      } else {
        hiveDiscardFailCount.set(tabId, fails);
      }
    })
  );
  console.info("[hive.reaper.sweep]", summary);
}

// Seed hiveTabLastSeen at SW startup so tabs that predate this SW instance
// aren't granted a fresh IDLE_MS grace. Previously (v64-v73) `?? now` meant
// every SW respawn (extension reload, keepAlive miss, service-worker eviction)
// reset the LRU clock on every existing tab — 8 renderers on a "zero Hive
// groups" sandbox trace directly to this. Give a 30 s grace so the first
// sweep after respawn doesn't nuke everything; that's plenty for the queen
// to reassert its CDP attachment on a tab it cares about.
(async function seedHiveTabLastSeen() {
  try {
    const now = Date.now();
    const graceMs = 30_000;
    const seedTs = now - HIVE_IDLE_MS + graceMs;
    for (const t of await chrome.tabs.query({})) {
      if (!hiveTabLastSeen.has(t.id)) hiveTabLastSeen.set(t.id, seedTs);
    }
  } catch (_) {
    // chrome.tabs.query can fail during SW init before permissions land;
    // best-effort — the next onActivated / onUpdated will populate anyway.
  }
})();

chrome.alarms.create(HIVE_REAP_ALARM, {
  periodInMinutes: 0.5, // was 1 — reap twice as often
  delayInMinutes: 0.5, // was 1 — first sweep 30 s after SW startup
});

// Event-driven reap kicker: without this, opening a 4th tab could leave 4
// renderers alive for up to 30 s until the alarm ticks — a long time under
// the 2 GiB cage. Debounced so a burst of tab.create calls (e.g.
// context.create + tab.create back-to-back) coalesces to a single sweep
// rather than N races.
let hiveReapDebounceId = null;
function hiveKickReap() {
  if (hiveReapDebounceId != null) return;
  hiveReapDebounceId = setTimeout(() => {
    hiveReapDebounceId = null;
    void hiveReapIdleTabs();
  }, 500);
}

// onActivated / onCreated are already listened for below (in the tab-event
// forwarder block). To keep the reaper's tracking colocated with the alarm
// definition, hook them here too — separate listeners are additive and both
// fire. onUpdated (status=complete) tracks page-load-finish as a "touch".
chrome.tabs.onActivated.addListener((activeInfo) => hiveTouchTab(activeInfo.tabId));
chrome.tabs.onCreated.addListener((tab) => {
  hiveTouchTab(tab.id);
  // A new tab may push us past the total-tab cap. Kick a debounced reap so
  // we shed to the LRU immediately rather than at the next alarm tick.
  hiveKickReap();
});
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "complete") {
    hiveTouchTab(tabId);
    // Page-load completion could reveal a new URL that pushes us over the
    // cap (or a redirect to a heavy site). Re-evaluate.
    hiveKickReap();
  }
  // Chrome fires onUpdated with discarded=true when the reaper (or user, or
  // Chrome itself under memory pressure) discards the tab. Drop it from the
  // LRU map so it doesn't skew "oldest-first" on the next sweep. Also clear
  // any pending discard-fail count since the tab is now in the discarded
  // state we were trying to reach.
  if (changeInfo.discarded === true) {
    hiveTabLastSeen.delete(tabId);
    hiveDiscardFailCount.delete(tabId);
  }
  // A tab entering (or leaving) a Hive group changes the sweep log's
  // hiveGroupTabs / ungroupedTabs split; keep kicking so the log is
  // meaningful for operators reading it.
  if (changeInfo.groupId !== undefined) hiveKickReap();
});
chrome.tabs.onRemoved.addListener(hiveForgetTab);

// Track CDP attach/detach so we don't discard a tab the queen is driving.
// The existing dispatch() cases for cdp.attach and cdp.detach are where the
// bridge issues the debugger calls; add tracking there too (below) so state
// stays consistent even if a tab is attached out-of-band via chrome.debugger.
// The onDetach event covers the "target closed" / "canceled_by_user" cases.
chrome.debugger.onDetach.addListener((source, _reason) => {
  if (source && typeof source.tabId === "number") {
    hiveAttachedTabs.delete(source.tabId);
    // A released tab is immediately reap-eligible; don't wait 30 s for the
    // next alarm to notice.
    hiveKickReap();
  }
});

// ---------------------------------------------------------------------------
// Agent-control affordance — pulsing glow around agent-driven tabs
// ---------------------------------------------------------------------------
//
// When a tab is controlled by an agent (i.e. it lives in a Hive tab group), we
// inject a thin pulsing glow around the viewport so the user can see at a glance
// "an agent is driving this page". Reliability choices:
//   • A closed Shadow DOM + a constructed CSSStyleSheet: isolated from the
//     page's CSS AND exempt from its CSP (a naive injected <style> isn't).
//   • position:fixed + pointer-events:none: zero layout shift and it never
//     intercepts the agent's (or the user's) clicks.
// The glow is a few px at the very viewport edge, so it shows up only faintly in
// the agent's CDP screenshots without obscuring content — simpler and more
// robust than racing to hide it around every Page.captureScreenshot.

// These two run IN the page (serialized by chrome.scripting), so they must be
// fully self-contained — no references to anything outside their own body.
function __hiveInjectAgentOverlay() {
  const ID = "__hive_agent_overlay_host__";
  if (document.getElementById(ID)) return; // idempotent
  const rootEl = document.documentElement || document.body;
  if (!rootEl) return;
  const SVGNS = "http://www.w3.org/2000/svg";
  const host = document.createElement("div");
  host.id = ID;
  // Set via the CSSOM (not a style="" attribute) so a strict page CSP can't
  // block it.
  const s = host.style;
  s.position = "fixed";
  s.top = "0";
  s.left = "0";
  s.right = "0";
  s.bottom = "0";
  s.zIndex = "2147483647";
  s.pointerEvents = "none";
  s.margin = "0";
  s.padding = "0";
  s.border = "0";
  s.overflow = "hidden"; // let edge cells bleed off-screen instead of squishing
  const shadow = host.attachShadow({ mode: "closed" });
  const css =
    "@keyframes hiveBreathe{0%,100%{opacity:.1}50%{opacity:.9}}" +
    ".hc{display:block;filter:drop-shadow(0 0 3px rgba(255,196,0,.55));" +
    "animation:hiveBreathe 1.8s ease-in-out infinite;}" +
    // Light-weight full-viewport border glow in the honey fill colour, pulsing in
    // sync with the honeycomb. Pure box-shadow → GPU-composited, no per-cell cost.
    ".edge{position:absolute;inset:0;border-radius:2px;" +
    // Layered *blurred* inset shadows — a bright ~4px soft core fading inward —
    // so the edge glows instead of being a hard solid line.
    "box-shadow:inset 0 0 6px 1px rgba(255,196,0,.85)," +
    "inset 0 0 18px 4px rgba(255,196,0,.45)," +
    "inset 0 0 36px 8px rgba(255,196,0,.18);" +
    "animation:hiveBreathe 1.8s ease-in-out infinite;}" +
    "@media (prefers-reduced-motion:reduce){.hc,.edge{animation:none;opacity:.9}}";
  try {
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(css);
    shadow.adoptedStyleSheets = [sheet];
  } catch (_) {
    // adoptedStyleSheets/constructed sheets unsupported — fall back to a scoped
    // <style> inside the shadow root (still CSS-isolated from the page).
    const st = document.createElement("style");
    st.textContent = css;
    shadow.appendChild(st);
  }
  // The border glow is size-independent (inset:0), so create it once here; only
  // the honeycomb <svg> gets rebuilt on resize.
  const edge = document.createElement("div");
  edge.className = "edge";
  shadow.appendChild(edge);

  // A honeycomb is a tessellation of REGULAR hexagons: every vertex sits at a
  // 60° step around the centre, and the cells lock together on an offset grid
  // (pointy-top → columns √3·R apart, rows 1.5·R apart, odd rows shoved half a
  // column over). Compute that exactly rather than approximating.
  function hexPoints(cx, cy, R) {
    let p = "";
    for (let k = 0; k < 6; k++) {
      const a = (Math.PI / 180) * (60 * k - 90); // -90° = a vertex pointing up
      p += (cx + R * Math.cos(a)).toFixed(1) + "," + (cy + R * Math.sin(a)).toFixed(1) + " ";
    }
    return p.trim();
  }
  // Stable pseudo-random in [0,1) keyed on a cell's position (plus a per-corner
  // seed). Anchored to the corner, so the same cell always gets the same value
  // — a ragged, organic edge that doesn't shimmer when the window resizes.
  function jitter(a, b) {
    const n = Math.sin(a * 12.9898 + b * 78.233) * 43758.5453;
    return n - Math.floor(n);
  }
  function build() {
    const W = window.innerWidth;
    const H = window.innerHeight;
    const old = shadow.querySelector("svg");
    if (old) old.remove();
    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("width", String(W));
    svg.setAttribute("height", String(H));
    svg.setAttribute("class", "hc");
    // Each corner is its OWN honeycomb — different cell size, reach, spread
    // direction and brightness — so no two corners look alike. Gently scaled to
    // the viewport, but otherwise fixed so the composition is stable on resize.
    const k = Math.max(0.6, Math.min(1.25, Math.min(W, H) / 1000));
    const sp = (v) => Math.max(110, v * k);
    const cornerConfigs = [
      // ox,oy = the corner; sx,sy = direction inward. reachX/reachY make the
      // falloff elliptical → some corners run along the top, others down a side.
      // Cell size and brightness are kept near-uniform on purpose; the
      // diversity lives in how far/which-way each corner spreads (reachX/reachY)
      // and its frayed-edge seed.
      { ox: 0, oy: 0, sx: 1, sy: 1, R: 21, reachX: sp(400), reachY: sp(210), intensity: 1.0, seed: 0 }, // TL: runs along the top
      { ox: W, oy: 0, sx: -1, sy: 1, R: 20, reachX: sp(140), reachY: sp(320), intensity: 0.9, seed: 41 }, // TR: trickles down the side
      { ox: 0, oy: H, sx: 1, sy: -1, R: 21, reachX: sp(250), reachY: sp(250), intensity: 0.95, seed: 87 }, // BL: even both ways
      { ox: W, oy: H, sx: -1, sy: -1, R: 20, reachX: sp(180), reachY: sp(120), intensity: 0.85, seed: 129 }, // BR: small, faint trace
    ];
    for (const c of cornerConfigs) {
      const R = c.R;
      const dx = Math.sqrt(3) * R; // horizontal centre spacing
      const dy = 1.5 * R; // row spacing
      const band = R * 2.6; // ribbon depth from each edge of this corner
      const maxReach = Math.max(c.reachX, c.reachY);
      // x,y are distances INTO the page from this corner along each axis.
      for (let row = 0; row * dy <= maxReach + R; row++) {
        const y = row * dy;
        const xoff = row % 2 ? dx / 2 : 0;
        for (let x = xoff; x <= maxReach + R; x += dx) {
          // L-shaped ribbon hugging the two edges that meet at this corner.
          if (!(x < band || y < band)) continue;
          // Elliptical falloff — different reach per axis = different shape.
          const t = 1 - Math.hypot(x / c.reachX, y / c.reachY);
          if (t <= 0) continue;
          const px = c.ox + c.sx * x;
          const py = c.oy + c.sy * y;
          const j = jitter(Math.round(x) + c.seed, Math.round(y));
          if (t <= 0.08 + 0.24 * j) continue; // ragged, frayed edge
          const poly = document.createElementNS(SVGNS, "polygon");
          poly.setAttribute("points", hexPoints(px, py, R * 0.9)); // *0.9 → mortar gap
          // Smoothstep the corner falloff: a soft uniform core that feathers
          // gently at the edge — more natural than a straight linear ramp
          // (perceived brightness and light falloff are both non-linear).
          const s = t * t * (3 - 2 * t);
          const a = (0.1 + 0.8 * s) * c.intensity * (0.78 + 0.22 * j);
          poly.setAttribute("fill", "rgba(255,196,0," + (0.05 * s * c.intensity).toFixed(3) + ")");
          // Outline a touch deeper than the fill/glow for a crisper comb edge.
          poly.setAttribute("stroke", "rgba(245,190,0," + a.toFixed(3) + ")");
          poly.setAttribute("stroke-width", "1.3");
          svg.appendChild(poly);
        }
      }
    }
    shadow.appendChild(svg);
  }
  build();
  // Rebuild on resize (debounced). Tie the listener to an AbortController stored
  // on the isolated world's window so the remover can cancel it — otherwise it
  // leaks after the glow is gone. The isolated world persists across our
  // executeScript calls, so the remover sees the same global.
  try {
    const ac = new AbortController();
    let t = 0;
    window.addEventListener(
      "resize",
      () => {
        clearTimeout(t);
        t = setTimeout(build, 150);
      },
      { signal: ac.signal },
    );
    window.__hiveAgentOverlayAbort = ac;
  } catch (_) {}
  rootEl.appendChild(host);
}

function __hiveRemoveAgentOverlay() {
  try {
    if (window.__hiveAgentOverlayAbort) {
      window.__hiveAgentOverlayAbort.abort();
      delete window.__hiveAgentOverlayAbort;
    }
  } catch (_) {}
  const el = document.getElementById("__hive_agent_overlay_host__");
  if (el) el.remove();
}

async function showAgentOverlay(tabId) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: false },
      func: __hiveInjectAgentOverlay,
    });
  } catch (_) {
    // chrome://, the Web Store, the PDF viewer, or a tab that closed mid-flight
    // — pages we can't script. The glow simply won't show; not an error.
  }
}

async function hideAgentOverlay(tabId) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: false },
      func: __hiveRemoveAgentOverlay,
    });
  } catch (_) {}
}

async function syncAgentOverlay(tabId) {
  if (tabId == null) return;
  let tab;
  try {
    tab = await chrome.tabs.get(tabId);
  } catch (_) {
    return; // tab gone
  }
  if (await isHiveGroup(tab.groupId)) await showAgentOverlay(tabId);
  else await hideAgentOverlay(tabId);
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.groupId !== undefined) {
    // Joined or left a group — add the glow if it's now Hive's, remove if not.
    void syncAgentOverlay(tabId);
  } else if (
    changeInfo.status === "complete" &&
    tab &&
    tab.groupId != null &&
    tab.groupId >= 0
  ) {
    // A navigation discards the injected overlay; re-inject, but only for
    // Hive-group tabs (a plain isHiveGroup check, no page scripting otherwise).
    void (async () => {
      if (await isHiveGroup(tab.groupId)) await showAgentOverlay(tabId);
    })();
  }
});

// Re-apply glows on service-worker startup (e.g. after MV3 eviction) for tabs
// already sitting in Hive groups. Only touches Hive-group tabs.
async function syncAllAgentOverlays() {
  try {
    const groups = await chrome.tabGroups.query({});
    const hive = new Set(
      groups
        .filter((g) => (g.title || "").includes(HIVE_GROUP_MARKER))
        .map((g) => g.id),
    );
    if (!hive.size) return;
    const tabs = await chrome.tabs.query({});
    for (const t of tabs) {
      if (t.id != null && hive.has(t.groupId)) void showAgentOverlay(t.id);
    }
  } catch (_) {}
}
void syncAllAgentOverlays();

// Periodic alarm keeps the service worker from being garbage-collected and
// recreates the offscreen document if it was evicted. The keepalive ping
// also nudges the offscreen page to send a noop on the WS so a half-open
// socket surfaces as an onclose instead of sitting dead until the next
// real command.
chrome.alarms.create("keepAlive", { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepAlive") {
    ensureOffscreen();
    try {
      chrome.runtime.sendMessage({ _beeline: true, type: "ws_keepalive" });
    } catch (_) {
      // sendMessage throws when there are no listeners (offscreen still spinning up) — fine.
    }
    return;
  }
  if (alarm.name === HIVE_REAP_ALARM) {
    void hiveReapIdleTabs();
    return;
  }
});
