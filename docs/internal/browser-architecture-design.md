# Agent Browser Architecture — Design

**Status:** Draft for review — no decision locked
**Scope:** 4 repos — `hive-desktop-runtime` (Python runtime + browser bridge + extension source), `hive-desktop` (Electron app), `hive-backend` (VM orchestration), `infra/sandbox-images/hive-novnc` (VM template)
**Author:** design conversation, 2026-07-30

---

## 1. Summary

Hive drives browsers two ways today, with different architectures, different failure modes, and no shared user experience:

- **Local** — an MV3 extension (`chrome.debugger` CDP) inside the **user's own** Chrome/Brave/Edge, with their real profile and logged-in sessions.
- **VM** — the **same extension**, force-installed by managed policy into `google-chrome-stable` inside a Firecracker sandbox, streamed to the user as a noVNC desktop in a detached Electron window.

The goal is a **single experience**: the user watches an agent browse inside the Hive window and can take over at any moment; signs in once and stays signed in; sees exactly what the agent can reach; and cannot tell — and need not care — whether the work is happening on their machine or in a cloud VM.

Everything technical in this document is derived from that outcome. What it turns out to require is a browser binary we bundle and version-control, embedded in the app, with an isolated persistent profile whose format is compatible across both deployments — because **profile compatibility is version-locked**, and that single fact constrains the binary, the shell, and the migration path (§4).

This document records the tradeoffs on every axis, what has been verified in code versus researched versus assumed, and the two live defects found along the way. **It does not lock a decision.**

---

## 2. Requirements

Ranked from the user outcome down. Technical requirements are **derived** from these, not stated alongside them — so that any option can be judged by which user outcome it damages, and so that a technical requirement serving no user outcome is visible as a choice rather than a constraint.

### 2.1 User experience requirements (ranked)

| #       | The user should be able to say…                                       | Notes                                                                                                                       |
| ------- | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **UX1** | "It's the same whether the agent runs on my machine or in the cloud." | The original goal — _flatten the experience_. Same surface, same controls; I shouldn't have to know where it runs           |
| **UX2** | "I can watch the agent work, and take over instantly."                | In the Hive window — not a separate app, and not something that looks like a remote desktop. Click in, intervene, hand back |
| **UX3** | "I sign in once and stay signed in."                                  | Across restarts, **and** across local↔cloud. Session continuity is what makes UX1 real rather than cosmetic                 |
| **UX4** | "The agent only reaches what I gave it."                              | Not sitting in my personal browser with my banking, health and personal mail. Visible scope, revocable                      |
| **UX5** | "It doesn't degrade my machine or fight my own browsing."             | Doesn't exhaust RAM, doesn't touch my tabs, doesn't contend with my browser                                                 |
| **UX6** | "It's responsive and feels like a real app."                          | Native window; actions land promptly; no remote-desktop lag on what _I_ do                                                  |

Non-goals: a general-purpose consumer browser; a daily driver; being the user's default browser.

### 2.2 Derived technical requirements

| #   | Requirement                                        | Serves        | Forced or chosen?                                                                                                                                           |
| --- | -------------------------------------------------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | A browser **binary we bundle and version-control** | UX1, UX3, UX5 | **Forced** — profile compatibility is version-locked (§4)                                                                                                   |
| R2  | **Runtime memory control**                         | UX5           | **Forced in the VM** (2 GiB cgroup); materially weaker locally (§5.4)                                                                                       |
| R3  | **No debugger panel; low-overhead automation**     | UX2, UX6      | _Split._ No-panel is **forced**, but comes free once R1 holds. A **native API is chosen, not forced** — CDP with preload batching serves UX6 equally (§5.3) |
| R4  | **Embedded rendering inside the app**              | UX2, UX6      | **Forced**                                                                                                                                                  |
| R5  | **Isolated persistent profile**                    | UX3, UX4      | **Forced**                                                                                                                                                  |
| R6  | Profile data **compatible across local and VM**    | UX1, UX3      | **Forced** — and the constraint that drives most of this document (§4)                                                                                      |

### 2.3 Engineering choices with no direct user outcome

These are real decisions, but they should be argued on cost, risk and maintainability — **not** on user value, and they must not be allowed to override §2.1:

- **CLI control plane instead of MCP** — agent-side ergonomics and context cost (§5.3). Invisible to the user.
- **Which rung of the browser ladder** (A0 flags / A own build / B patchset) — cost and risk (§5.1). R1 forces _a_ controlled binary; it does not dictate how customized.
- **Shape A vs Shape B** (Electron shell vs Chromium shell) — cost and rewrite exposure (§5.2). Both can satisfy UX1-UX6; they differ in price.

**The one place a technical requirement was mistaken for a user requirement:** "native API instead of CDP" was originally stated as a hard requirement. Decomposed, its two motives are the visible debugger panel (UX2) and round-trip overhead (UX6) — and both are satisfied without abandoning CDP. Treating it as forced would have cost the 13,562-line automation layer for no user-visible gain.

---

## 3. Current state (verified in code)

### 3.1 Local path

| Aspect             | Detail                                                                                                                              |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| Transport          | gcu MCP → JSON-RPC/WS (14831) → `bridge_host` → WS relay (14829, legacy 9229) → MV3 extension → `chrome.debugger` CDP               |
| Browser            | The **user's own** installed Chrome/Brave/Edge, their real profile                                                                  |
| Extension delivery | Chrome Web Store, id `jkpcegnbfimimjodblcemoheedidnppm`, v1.7.4. The desktop app **never installs it** — it deep-links to the store |
| Bundled copy       | `hive-desktop/vendor/hive/tools/browser-extension` is **stale: v1.2.3, 351 lines, no reaper**                                       |
| Automation code    | `tools/src/gcu/browser/` = **13,562 lines**, `bridge.py` alone 6,375; `bridge_host.py` 483                                          |

### 3.2 VM path

| Aspect        | Detail                                                                                                                           |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Template      | `infra/sandbox-images/hive-novnc/` — Debian bookworm, 2 vCPU / 4096 MB / 6144 MB disk                                            |
| Browser       | `google-chrome-stable` from apt; same extension force-installed via managed policy                                               |
| Display stack | Xvfb `1280x800x24` (no `-randr`) → x11vnc → websockify → noVNC, with **xfwm4 + xfce4-panel + xfdesktop** all running             |
| Chrome window | `--window-size=1100,720 --window-position=80,40` — i.e. a WM-decorated window on a visible desktop                               |
| Presentation  | noVNC page in a **detached** Electron `BrowserWindow` (1280×860), `resize=scale` client-side scaling, **no fps tuning anywhere** |
| Memory cage   | cgroup v2: `memory.max` 2 GiB, `memory.high` 1.5 GiB; VM idles ~2.7 GiB of 4 GB                                                  |
| Already open  | `--remote-debugging-port=9222` on loopback, **currently unused** — a raw-CDP path exists today                                   |
| Notable flags | `--password-store=basic`, `--js-flags=--max-old-space-size=384`, `--renderer-process-limit=8`, `--disable-dev-shm-usage`         |

### 3.3 Desktop shell

Electron **33.4.11** (Chromium 130, EOL). electron-builder → dmg (mac arm64) / NSIS perMachine (win) / AppImage (linux). `hardenedRuntime: true`, notarization configured (team `N897NVV9VC`), Azure Trusted Signing wired for Windows. **No auto-updater** — manual version poll against `open-hive.com/api/version` plus full installer re-download. `src/main` = **10,593 lines** (cloud.ts 3,622 · ipc.ts 1,420 · remote-runtime.ts 1,406 · runtime.ts 1,294 · vm-sync 575 · main 485 · sse 335 · translocation 268 · others).

---

## 4. The constraint that drives everything: R6

Chrome's profile format is **version-coupled, and downgrade is unsupported** — Chrome records the last version in the profile and refuses or resets on an older build. Therefore "user data compatible between local and VM" is not a sync problem, it is a **version-lock problem**, and it forces the same binary (or tightly version-locked binaries) on both sides.

Two consequences:

**(a) Electron's `WebContentsView` is disqualified.** Electron 33 is Chromium 130; the VM runs ~151. Even Electron 43 (~Chromium 150) is a downgrade relative to VM stable. A browser whose version you do not control cannot satisfy R6. _This kills the embedded-WebContentsView plan that was recommended earlier in the analysis._

**(b) Cookie encryption backends must match.** The VM already runs `--password-store=basic` (hardcoded key → portable cookie DB). macOS binds to Keychain and Windows to DPAPI + App-Bound Encryption — both machine-bound. Running `basic` locally makes profiles portable **at the cost of weakly-encrypted cookies at rest on the user's disk.** This is a deliberate security decision, not a detail.

**Prerequisite that does not exist yet:** VM Chrome profiles do not persist at all. `hive-userdata-snapshot.sh:15` states plainly that `/data/chrome` is excluded — "A later RC will add a second tarball for chrome state." The durable NFS mount covers `/root/.hive`, not the browser profile.

---

## 5. Decision axes

### 5.1 Browser binary — the ladder

| Rung   | What                                                                                                                                  | Buys                                                                                                                                                                                                                                                                                                   | Costs                                                                                                                                                  | Verdict                        |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------ |
| **A0** | Stock Chrome + runtime flags                                                                                                          | Site-isolation off (~10-13% RAM), V8 caps, `--in-process-gpu` (−38 MiB measured), process limits. Measured **−7.6%** total PSS (−12.4% with `--jitless`, which costs ~40% Speedometer)                                                                                                                 | Site-isolation-off means a compromised renderer reads other sites' data **inside the browser** — acceptable only for short-lived, per-task profiles    | **Do first.** Free, reversible |
| **A**  | Own gn-args build (ungoogled-style: `safe_browsing_mode=0`, `enable_reporting=false`, no API keys, server trims, `is_official_build`) | Reproducible in-house binary, no phone-home services, tens of MB RSS, the base for rung B, and **a binary whose version you control (R1, R6)**                                                                                                                                                         | ~50 CPU-hours/clean build (single-digit $); CI pipeline; must track security releases                                                                  | **Required for R1/R6**         |
| **B**  | Thin **<30-file** patchset                                                                                                            | The only levers unreachable otherwise: **PSI/cgroup pressure wiring** (Linux Chrome ships _no_ MemoryPressureMonitor, so it never self-purges under cgroup pressure), a **CDP tab-discard command** (`chrome.tabs.discard` is extension-only), **per-renderer hard budgets**, tiled screenshot capture | Rebase burden. Track the 8-week **extended-stable** channel (~6.5/yr), _not_ stable — which moves to 2-week milestones at Chrome 153 on **2026-09-08** | **Only on measured need**      |
| **C**  | content_shell / CEF / headless shell                                                                                                  | Roughly halves footprint                                                                                                                                                                                                                                                                               | Google **blocks sign-in from embedded frameworks** (CEF-class) — fatal for R5/R6; no extension runtime; no headful UI                                  | **Rejected**                   |

Market census: Browserbase and Anchor patch Chromium; Steel, Kernel and browserless run stock. BrowserOS = 4 people + AI tooling sustaining a 366-file fork, but **12 weeks behind stable**. There is _no published quantitative evidence_ that AI compresses Chromium rebase effort — treat that as plausible-but-unproven.

### 5.2 Embedding — Shape A vs Shape B

This is the open decision.

|             | **Shape A** — Electron shell + bundled Chromium child                                                                       | **Shape B** — Chromium _is_ the shell                                                                                    |
| ----------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Embedding   | **Hard.** No cheap path exists                                                                                              | **Non-problem** — one process tree; UI is a WebUI page, browsing is a view                                               |
| Preserves   | All 10,593 lines of `src/main`, electron-builder, existing UI                                                               | UI survives as WebUI; main-process logic does not                                                                        |
| Memory      | Two Chromium trees locally (Electron's shell measures ~303 MiB PSS, within 1.3% of Chrome's own fixed cost) → **~+300 MiB** | Deletes the duplicate tree                                                                                               |
| Bundling    | Keeps electron-builder; still must hand-sign nested Chromium helpers in `afterPack`                                         | Loses electron-builder; adopts Chromium's own installer pipeline (`mini_installer`, mac packaging) — **Brave's model**   |
| Native feel | Unchanged                                                                                                                   | **Unchanged** — Electron already _is_ Chromium in a native window; Chrome/Brave/Arc/Vivaldi/BrowserOS all look like apps |

**Correction recorded:** Electron 33.4.11 _does_ expose `webPreferences.offscreen.useSharedTexture`, but it lets Electron **produce** frames from its own `webContents` — there is **no API to import a foreign process's IOSurface/D3D11 texture**. So Shape A embedding reduces to: pixel-pumping over IPC (~110 MB/s RGBA at 1280×800×30fps), native window reparenting (fragile, Wayland-hostile), or a per-platform native compositing addon (the 6-12 engineer-month class of work; Atlas used a private macOS API only because OpenAI compiled both sides).

**R1 + R4 collide in Shape A.** That collision is why every browser-shaped product — Arc, Brave, BrowserOS, Comet, Atlas — made the browser the app.

**Mitigation for Shape B's cost:** much of `src/main` is not Electron-coupled. cloud.ts, remote-runtime.ts, sse.ts and vm-sync.ts are HTTP/API orchestration that lives there only because that is where Node was; they could move into the Python runtime, which already runs locally on every install. The genuinely native surface (window/lifecycle, IPC bridge, protocol handler, translocation) is closer to **~2k lines**. **This extraction is valuable in every branch** and is reversible — it converts "rewrite 10.6k lines" into "write a 2k-line shell."

### 5.3 Control plane — CLI vs MCP, CDP vs native API

**Decided by the team: CLI, not MCP.** Evidence supports it — Vercel `agent-browser` (Rust CLI → Unix-socket daemon → raw CDP, `@eN` refs, env-var sessions) and Microsoft `playwright-cli` converged independently; measured ~90%+ context savings vs MCP (Playwright MCP ~13.7k tokens of definitions at startup; a 10-step flow ~7k CLI vs ~114k MCP), corroborated by Anthropic's own code-execution-with-MCP result (150k → 2k tokens).

**On "native API instead of CDP":**

- The **panel is an extension artifact**, not a CDP one. It comes from `chrome.debugger.attach`, and it shows today because `--silent-debugger-extension-api` appears nowhere in the config. Raw CDP over `--remote-debugging-port` shows nothing — `--enable-automation` is also absent, so there is no automation infobar in the VM at all. **Owning the binary removes the panel without changing protocols.**
- If the motive is **round-trip cost** (a selector click is 8-12 serialized CDP round trips today), the fix is a **preload/injected batching layer** — one call doing the whole selector dance — which works over CDP.
- A genuine native API (CEF `CefBrowserHost`) is a legitimate choice but costs the 13,562-line Python automation layer, all expressed in CDP verbs. CEF also carries the Google embedded-framework sign-in block, colliding with R5/R6.

**Recommendation on this axis:** own the binary, keep CDP as the wire format, batch through preload. R3's actual goals are met without discarding the brain.

**What CDP portability looks like today:** the AX snapshot engine, `>>>` shadow-piercing selectors, all input paths, `evaluate`, screenshots, waits and `Page.handleJavaScriptDialog` are pure CDP and port unchanged. Extension-coupled and needing reimplementation: tab **groups** (a `chrome.tabGroups`-only concept), `chrome.debugger` attach bookkeeping, the dialog event fan-in relay, the LRU reaper, and the `tab.audit` health probe feeding `health.py`.

### 5.4 Memory levers — what needs the build and what does not

| Lever                                            | Without custom build              | Notes                                                                                                                            |
| ------------------------------------------------ | --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Process count / site isolation                   | ✅ flags                          | Biggest single lever (~10-13%); security tradeoff                                                                                |
| V8 heap caps                                     | ✅ `--js-flags`                   | Per-renderer; converts a leak into one dead tab                                                                                  |
| GPU process elimination                          | ✅ `--in-process-gpu`             | −38 MiB measured; SwiftShader under Xvfb anyway                                                                                  |
| cgroup hard ceiling + renderer-first OOM         | ✅ `memory.max` + `oom_score_adj` | Kernel-enforced; makes 18 GB leaks impossible by construction                                                                    |
| PSI pressure → self-purge                        | ❌ **needs patch**                | Linux Chrome has no MemoryPressureMonitor                                                                                        |
| Tab discard                                      | ❌ **extension-only today**       | No CDP verb; interim = `Target.closeTarget` + reload (loses history/scroll/form state), or `Memory.simulatePressureNotification` |
| Per-renderer hard budgets                        | ❌ **needs patch**                | In-process only                                                                                                                  |
| Own the lifecycle (create/destroy on our policy) | ✅ once we own the process        | Most of the practical win                                                                                                        |

**Sizing reality:** nobody streams a headful browser in 2 GiB. Kernel prices headful at 8 GB vs headless 1 GB; Steel budgets 300-500 MB per session with ≥4 GB; neko wants 3-4 GB. A 6-8 GB VM tier is cheaper than any engineering above.

### 5.5 Distribution — the real cost of shipping a browser locally

Corrected during analysis: **notarization is not the problem.** It is per-submission, the app bundle is already notarized (`hardenedRuntime`, team `N897NVV9VC`), Electron already ships a Chromium with the same nested-helper structure, and SmartScreen publisher reputation carries across releases.

What survives:

1. **The update channel — the actual blocker.** Chrome 150 alone shipped 382 security fixes; 5 zero-days were exploited in the wild in 2026 by July. A browser rendering hostile content needs 40-60 releases/platform/year. There is **no auto-updater** today. Omaha-4 commercially is ~€12,000 _per target OS_ plus license and annual.
2. **One-time signing work:** a foreign `Chromium.app` needs its nested helpers signed inside-out with per-helper entitlements (renderer needs JIT; others should not get it). Days-to-weeks in the `afterPack`/`afterSign` hook. **Required in Shape A too.**
3. **Size:** installer ~134 MB → ~250-280 MB; installed 270-347 MB → ~700-850 MB.
4. **Build matrix:** gn args and the patchset port nearly unchanged (only the PSI patch is Linux-only — macOS and Windows already _have_ a MemoryPressureMonitor). Windows cross-builds from Linux (Brave has done this in production since 2023). **macOS requires Apple hardware** (~$2k + 1-2 engineer-weeks).

**Counterpoint in our favour:** we already ship Chromium 130 via Electron 33 (EOL, 21 milestones stale). A freshly-built custom Chromium tracking extended-stable would be _newer_ than what ships today. The honest distinction is **exposure, not staleness** — Electron's renderer currently shows our own UI and the noVNC page; a browsing Chromium eats hostile content continuously.

**Asymmetry:** the VM needs none of this — no signing, no notarization, no updater, no store. Monthly rebuilds plus out-of-band rebuilds for actively-exploited CVEs are defensible there. **The VM half of the custom browser is cheap; the desktop half is where the cost lives, and it gates on an updater we need regardless.**

### 5.6 Privacy and profile model

The premise "shared-profile access is a liability, not just an asset" is **correct and under-weighted in earlier analysis**. The property that makes the extension effective — indistinguishable from the user browsing, with all their sessions — is exactly what makes it invasive. **The VM path already implements the model we want**; the extension on the user's own profile is the outlier.

Market evidence (researched 2026-07-30):

- **Brave is the only browser that isolates the profile** for AI browsing ("creates a brand-new browser profile… cookies, logged-in state, caches do not cross profiles"). Shipped to all channels May 2026; **stayed niche**.
- **Chrome auto browse** (targeting 200M devices) deliberately runs on the **user's authenticated sessions**.
- What actually shipped and won is **credential brokering**, not profile isolation: 1Password for Claude (July 2026) injects credentials scoped to the current task, terminated on completion, agent never sees the secret. Steel, Kernel and Browserbase all scope credentials; **Steel explicitly recommends profile persistence over isolation**.
- **Enterprise:** Five Eyes guidance (May 2026) requires agent identity, least privilege and short-lived credentials. A scoped profile satisfies this — _so does credential brokering_. The guidance contains **no** language about browser profiles specifically.
- **Enforcement matters:** Anthropic's Claude-in-Chrome has the only true per-site delegation surface, and its permission store is bypassable by writing directly to LevelDB. **Extension-storage permissions are UX; a profile/OS boundary is enforcement.**

**Implication:** we already have the enforceable half (the VM is a real boundary). The differentiation is not the boundary — it is pairing it with a low-friction credential path. Brave shipped the boundary without solving friction and stayed niche.

**Unverified:** that SOC 2 / ISO 27001 / security questionnaires specifically block full-profile agent access. Do **not** use this as a sales argument without verification.

### 5.7 Presentation — why the current VM experience is bad, independent of the binary

**UX quality and browser ownership are orthogonal.** A custom build buys memory and control; it buys zero UX.

Today the user sees: Electron window → noVNC web page → XFCE desktop with taskbar and wallpaper → WM-decorated Chrome window → tabs. Four levels of nested chrome, client-side-scaled because Xvfb runs without `-randr`, in a detached window, with no fps tuning anywhere.

Fixes, in payoff order — none require a custom binary:

1. **Stop streaming a desktop.** Drop `xfwm4`/`xfce4-panel`/`xfdesktop` from the browser view; Chrome owns the display, undecorated, at full size. _Product decision:_ the VM is currently also a usable desktop (xfce4-terminal, default-browser chain), so this may need two modes.
2. **Render browser chrome in our own UI** — tab strip, URL bar, back/forward in React fed by the daemon over the existing 8787 channel; the stream carries only the viewport. Pairs with `--kiosk`.
3. **Add `-randr`** so resolution follows the pane instead of scaling; **dock** the pane in the main window instead of detaching it.
4. **Transport:** VNC → WebRTC later (Steel measured 25 fps vs 4-12 for CDP screencast). A project, not a config change.

**Ceiling:** human interaction still crosses the network. But the agent, daemon and browser are **colocated inside the VM**, so automation speed is unaffected — only watching and takeover cross the wire.

---

## 6. Verified traps

Found during analysis; each would bite in week 1 of a naive migration.

1. **`Target.createBrowserContext` contexts are ephemeral.** Incognito-like: cookies/localStorage never hit disk, destroyed on dispose or browser restart. Per-agent contexts therefore **break login persistence (R5/R6)**. There is also **no CDP verb to move a target between contexts**, so the adopt/release human-takeover model stops working.
2. **The extension reaper cannot see raw-CDP attaches.** `hiveAttachedTabs` is populated only by the extension's own `cdp.attach` dispatch (background.js:625-648) and is the reaper's skip check (background.js:1015). Any coexistence window where a daemon drives port 9222 will have its tabs discarded and removed — reproducing the 2026-07-01 "tab creates but immediately dies" signature.
3. **Daemon-side policy is bypassable** while 127.0.0.1:9222 is open and agents have bash. `command_guard` blocks launching/killing browsers by name, not `curl` to a loopback port. Fix: `--remote-debugging-pipe` owned solely by the daemon, or an iptables uid-owner rule.
4. **Reverting the reaper to Hive-group scoping re-opens a known leak.** That was the design until 2026-07-05 and was removed because it missed `window.open` escapees and orphans after bridge restarts. The fix is positive tab-ownership tracking that survives service-worker respawn.

---

## 7. Live defects (independent of any decision here)

### 7.1 The extension reaper acts on the user's own tabs

In v1.7.4 — the Web Store build local users install:

- Runs on a **30-second alarm** from service-worker startup (background.js:1115-1118, :1453), with **no gate** on an active Hive session or a connected bridge.
- Eligible tabs = all live tabs except active/audible/pinned/CDP-attached. **The user's own idle tabs qualify.** In-code comment: the cap "applies to ALL live-backed tabs (agent + user + orphan). No Hive-group scoping."
- Cap is **3 globally**, and the cap path has **no idle requirement** (background.js:1024-1025). Ten tabs open → six discarded on the next sweep.
- After two refused discards it escalates to `chrome.tabs.remove()` (background.js:1078-1085). Chrome refuses discards on `beforeunload`, form entry and active downloads — so the escalation path is **biased toward tabs holding unsaved work**.

The desktop-bundled copy is v1.2.3 with no reaper, so this does not ship through that channel — but the app deep-links to the store, where the listing is v1.7.4. **Reproduce against a real profile to confirm blast radius.**

### 7.2 VM Chrome profiles do not persist

`hive-userdata-snapshot.sh:15` excludes `/data/chrome`. R6 has no foundation until this is fixed.

---

## 8. Open questions / prerequisites

| #   | Question                                                                                        | Why it blocks                                                                                                                              | Cost               |
| --- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------ |
| Q1  | Does a profile written in the VM load locally on the same binary with `--password-store=basic`? | **The entire unified-experience requirement rests on this.** If it fails, R6 is unachievable and the plan changes                          | 1-2 days           |
| Q2  | Shape A or Shape B?                                                                             | Determines whether the Electron shell survives                                                                                             | Decide after Q3    |
| Q3  | How much of `src/main` can move to the Python runtime?                                          | Converts Shape B from a 10.6k-line rewrite to a ~2k-line shell; **valuable in every branch**                                               | Scoping needed     |
| Q4  | Do we accept `--password-store=basic` locally (weak at-rest cookie encryption)?                 | Security decision, required for R6                                                                                                         | Decision, not work |
| Q5  | Do we accept site-isolation-off in the VM given profiles now hold real credentials?             | A0's biggest lever conflicts with durable logged-in sessions                                                                               | Decision           |
| Q6  | Is `--disable-features=AutomationControlled` (start-chrome.sh:130) a no-op?                     | The effective switch is likely `--disable-blink-features=AutomationControlled`; rung B budgets webdriver cleanups that may already be free | 1 hour             |
| Q7  | VM sizing: stay at 4 GB/2 GiB cgroup or move to 6-8 GB?                                         | Cheaper than any engineering in §5.1                                                                                                       | Decision           |

---

## 9. Where the analysis currently points

Not a locked decision — the reasoning as it stands. Ordered by user outcome served, since that is what the work is for:

0. **The fastest visible UX wins need no architecture decision at all.** The presentation fixes in §5.7 (stop streaming a desktop, render browser chrome in our own UI, add `-randr`, dock the pane) move **UX2 and UX6** more than any binary choice, and work on stock Chrome today. Fixing the reaper (§7.1) is the single largest **UX5** win and is a live defect regardless of direction.
1. **Do first, valuable in every branch:** the §5.7 presentation fixes; fix the reaper scoping (§7.1); make VM profiles persist and run Q1 (**UX3** has no foundation until this holds); extract non-Electron logic from `src/main` (Q3); A0 flags.
2. **The CLI control plane on raw CDP** is the highest-value, lowest-risk change and works on stock Chrome today — port 9222 is already open and unused. It also removes the debugger panel (R3) without a protocol change.
3. **Rung A (own build) is required** by R1/R6 — a version we control is the only way profiles stay compatible.
4. **The VM is where the custom browser is cheap and where memory actually binds.** The desktop half gates on an auto-updater we owe regardless (Electron 33 / Chromium 130 is EOL today).
5. **Shape B fits the spec; Shape A protects the investment.** R1+R4 collide in Shape A, which is real evidence for B — but the decision should wait until Q3 tells us what the shell actually costs.

---

## 10. Provenance

- **Verified in code during this analysis:** all of §3, §4 (the snapshot exclusion), §5.2 (Electron version + OSR API surface, `src/main` line counts), §5.3 (absence of `--enable-automation` / `--silent-debugger-extension-api`), §5.5 (signing config), §6.2, §7.
- **From code-reading agents:** transport chain details, CDP verb counts, extension-coupled vs portable breakdown.
- **From web research (2026-07-30), cited inline:** §5.1 build economics and market census, §5.3 CLI-vs-MCP measurements, §5.4 memory figures and vendor sizing, §5.5 distribution costs, §5.6 privacy/market evidence.
- **First-party measurements** (Chrome 149, headless, 3 tabs, PSS): the −7.6%/−12.4% flag deltas and the −38 MiB `--in-process-gpu` figure were measured on a 31.9 GB desktop with a real GPU on **logged-out** pages — **not** in a 2 vCPU / 2 GiB-cgroup Xvfb VM. Do not quote them as VM numbers.
- **Explicitly unverified:** SOC 2 / questionnaire language on agent profile access; that AI compresses Chromium rebase effort; enterprise-browser vendor positioning; 2026 standards work on scoped agent identity beyond 1Password.
