---
name: hive.browser-automation
description: Required before any hive-browser CLI command. The browser is driven from the terminal by running `hive-browser <command> ... --json` via terminal_exec — not via MCP tools. Teaches the browser lifecycle rules (the bridge attaches to the USER'S running Chrome — never kill or launch browser processes; timeouts are transport issues, not crashes), the screenshot + coordinate workflow (hive-browser interact with a fractional coordinate) that reaches shadow-DOM inputs selectors can't see, the viewport-fraction coordinate rule (not pixels), rich-text editor quirks ("send button stays disabled" failures), and CSP gotchas. Covers Chrome via CDP through the GCU Beeline extension. 
metadata:
  author: hive
  type: default-skill
  version: "2.2"
---

# GCU Browser Automation

All GCU browser automation drives a real Chrome instance through the Beeline extension and Chrome DevTools Protocol (CDP). You drive it **from the terminal**: every command is `hive-browser <command> ... --json`, run through `terminal_exec`. Always pass `--json` so the result is machine-readable. That means clicks, keystrokes, and screenshots are processed by the actual browser's native hit testing, focus, and layout engines — **not** a synthetic event layer. Understanding this unlocks strategies that make hard sites easy.

## Browser lifecycle & recovery — read this before "fixing" anything

The bridge attaches to the **user's already-running Chrome** via the extension. The browser is not yours: it holds the user's logged-in sessions and other agents' work, and the runtime — not you — owns the connection to it. Consequences:

- **There is nothing to "start."** If no browser is connected, `hive-browser setup --json` tells you and gives the user install steps. Launching Chrome yourself (any `google-chrome`/`chromium` command, `--remote-debugging-port`, `--user-data-dir`, headless flags) is forbidden and blocked — it opens a browser the bridge can't see, often under the wrong profile.
- **There is no situation where killing the browser helps.** Never use terminal tools to `kill`/`pkill`/`killall` Chrome, the bridge, or gcu processes. These commands are blocked, and attempting them breaks every agent sharing the connection. The same applies to the Hive desktop app and `bridge_host`.
- **A timeout is NOT a stuck browser.** All `hive-browser` commands share one transport across all agents; one slow call (a heavy `hive-browser evaluate` on a big page) can make YOUR calls time out while the browser is perfectly healthy. The timeout message tells you whether the server passed its liveness check and whether recovery is already running — believe it.
- **Allowed recovery, in order:** (1) wait ~30s and retry ONCE, with a smaller/simpler request — e.g. split a page-wide `hive-browser evaluate` sweep into chunked queries; (2) close YOUR OWN tabs with `hive-browser tab close <T> --json` and reopen; (3) report the failure (`report_to_parent` or your reporting channel) and move on to work that doesn't need the browser. Escalate to the user; never to the process table.
- Keep heavy `hive-browser evaluate` scripts cheap: avoid `innerText` over thousands of nodes (each read forces layout). Prefer `textContent`, scope the selector, and paginate the sweep.

## Targeting a specific Chrome profile / account

If your machine has more than one Chrome profile connected (different logged-in accounts), **say which one to act in** — if you omit it, the bridge falls back to the first-connected profile, which may be the wrong account. Pass `--browser-profile <label>` to `hive-browser open` (and `hive-browser navigate` / `hive-browser script`):

- **See every connected profile** in `hive-browser status --json` / `hive-browser setup --json` — both return a `connected_profiles` list of `{label, is_default, starred}` for ALL connected Chrome profiles (not just the one you're using). That's how you discover the labels. (`hive-browser status` reflects ALL connections; don't conclude "only one profile" from the single profile label of your own context.)
- The label is a **connected profile label** — the name shown in that profile's Hive extension side panel (or its auto 3-word id). If your task assigns you a profile (e.g. *"your profile is `acct-jpn`"*), pass exactly that.
- Every command's JSON echoes the profile it **actually** used. Check it: if it doesn't match what you intended, you opened the wrong account. Stop and fix the label (don't proceed).
- A label that isn't connected fails fast with the list of connected labels — bind to one of those.
- With one profile connected (or one starred default), you can omit it. With several connected and no star, omitting it uses the **first-connected** profile — fine for single-account work, risky for multi-account, so pass the label when the account matters.

## Working on LinkedIn?

For ANY LinkedIn flow, load `hive.linkedin-core` first — it owns the auth check, rate limits, stop protocol, reply-text policy, and DOM gotchas every LinkedIn script depends on. Then load the capability skill for the task: `hive.linkedin-discovery` (scans / People search), `hive.linkedin-messaging` (`lk_send_to_message_url`, `reply`, inbox), `hive.linkedin-connect` (`lk_send_invite`, post comments), or `hive.linkedin-sales-navigator` (premium search + InMail).

## Coordinates

Every `hive-browser interact` action that takes a `--coordinate` — and every command that returns one — operates in **fractions of the viewport (0..1 for both axes)**. Read a target's proportional position off `hive-browser screenshot` — "this button is about 35% from the left and 20% from the top" → pass `--coordinate 0.35,0.20`. Rect-returning commands (`hive-browser page shadow-query` and the `rect` inside `focused_element`) also return fractions. The CLI converts to CSS pixels internally before dispatching to Chrome.

```
hive-browser screenshot --json                                      → image + cssWidth/cssHeight in meta
hive-browser interact --action left_click --coordinate x,y --json   → x, y are fractions 0..1
hive-browser interact --action hover --coordinate x,y --json        → fractions
hive-browser interact --action key --coordinate x,y --text k --json → fractions
hive-browser page shadow-query "<selector>" --json → rect           → rect.cx / rect.cy are fractions
```

**Exception for zoomed elements:** pages that use `zoom` or `transform: scale()` on a container (LinkedIn's `#interop-outlet`, some embedded iframes) render in a scaled local coordinate space. `getBoundingClientRect` there may not match CDP's hit space. Prefer `hive-browser page shadow-query` (which handles the math and returns fractions) or visually pick coordinates from a screenshot. Avoid raw `hive-browser evaluate` + `getBoundingClientRect()` for coord lookup — that returns CSS px and will be wrong when fed to a `--coordinate`.

## Screenshot + coordinates is shadow-agnostic — prefer it on shadow-heavy sites

Start with `hive-browser page snapshot` when you need to inspect the page structure or find ordinary controls. If the snapshot does not show the thing you need, shows stale or misleading refs, or cannot prove where a visible target is, take `hive-browser screenshot` and use the screenshot + coordinate path. This is especially useful on sites that use Shadow DOM heavily.

Why:

- **CDP hit testing walks shadow roots natively.** `hive-browser interact --action left_click --coordinate x,y --json` routes through Chrome's native hit tester, which traverses open shadow roots automatically. You don't need to know the shadow structure.
- **Keyboard dispatch follows focus** into shadow roots. After a click focuses an input (even one three shadow levels deep), `hive-browser interact --action key ... --json` with no `--selector` dispatches keys to `document.activeElement`'s computed focus target.
- **Screenshots render the real layout** regardless of DOM implementation.

Whereas `wait_for_selector` and a `selector`-targeted `left_click` / `type` all use `document.querySelector` under the hood, which **stops at shadow boundaries**. They cannot see elements inside shadow roots. For shadow-DOM inputs, use a `type` action with no selector after focusing via a `coordinate` click.

### Recommended workflow on shadow-heavy sites

1. `hive-browser screenshot --json` → JPEG. **The image is attached to your context automatically on your next turn — do NOT `attach_file` / read the `saved_to` path; that is redundant and wasteful.** The result JSON carries a `saved_to` path (read it ONLY if, in a later turn, no image actually appeared); meta includes `cssWidth`/`cssHeight` for reference.
2. Identify the target visually → estimate its proportional position `[fx, fy]` where each is in `0..1`.
3. `hive-browser interact --action left_click --coordinate fx,fy --json` → the CLI converts to CSS px and dispatches; CDP native hit testing focuses the element. **The result includes `focused_element: {tag, id, role, contenteditable, rect, inFrame?, ...}`** — use it to verify you actually focused what you intended. `rect` is in fractions (same space as your input). When focus is inside a same-origin iframe, the descriptor reports the inner element and adds `inFrame: [...]` breadcrumbs.
4. `hive-browser interact --action type --text "..." --json` with no `--selector` → inserts text into `document.activeElement` (traverses into same-origin iframes automatically). Shadow roots, iframes, Lexical, Draft.js, ProseMirror all just work. Pass `--selector` instead when you have a reliable CSS selector for a light-DOM element.
5. Verify via `hive-browser screenshot` OR `hive-browser evaluate` reading a known-reachable marker (e.g. check that the Send button's `aria-disabled` flipped to `false`).

### The click→type loop (canonical pattern)

1. Run `hive-browser interact --action left_click --coordinate x,y --json` to click the target element.
2. Check the `focused_element` field in the result — it tells you what actually received focus (tag, id, role, contenteditable, rect).
3. If the focused element is editable, run `hive-browser interact --action type --text "..." --json` to insert text. Verify the text took effect — prefer checking the underlying `.value` / `innerText` via `hive-browser evaluate` or confirming the submit button enabled. A screenshot alone can mislead: narrow input boxes visually clip long text, so only a portion may appear on screen even though the full string was accepted.
4. If it is NOT editable, your click landed on the wrong thing — refine coordinates and retry. Do NOT reach for `hive-browser evaluate` + `execCommand('insertText')` or shadow-root traversals. The problem is the click target, not the typing method.

A `--selector`-based `left_click` also returns `focused_element`, so the same check works whether you clicked by selector or coordinate.

### Empirically verified (2026-04-11)

Tested against `https://www.reddit.com/r/programming/` whose search input lives at:

```
document > reddit-search-large [shadow]
         > faceplate-search-input#search-input [shadow]
         > input[name="q"]
```

### Shadow-piercing selectors

When you DO want a selector-based approach and know the shadow structure, `hive-browser page shadow-query` supports `>>>` shadow-piercing syntax:

```
hive-browser page shadow-query "reddit-search-large >>> #search-input" --json
hive-browser page shadow-query "#interop-outlet >>> #ember37 >>> p" --json
```

Returns the element's rect as **fractions of the viewport** (feed `rect.cx` / `rect.cy` straight into a `--coordinate`). Remember: a `type` action's `--selector` and `--wait-for-selector` do **not** support `>>>` — only `page shadow-query` does.

## Navigation and waiting

### The basics

```
hive-browser navigate <url> --wait-until load --json   # load | domcontentloaded | networkidle
hive-browser interact --action wait --wait-for-selector "h1" --timeout-ms 2000 --json
hive-browser interact --action wait --wait-for-text "Some text" --timeout-ms 2000 --json
hive-browser reload --json
hive-browser evaluate --js 'history.back()' --json     # back/forward via history API
```

All return real URLs and titles. On a fast page `navigate --wait-until load` returns in sub-second. A `wait` action with `--wait-for-selector` / `--wait-for-text` typically resolves in single-digit milliseconds on elements already in the DOM.

### Timing expectations (measured against real sites)

| Site                     | Navigate load time |
| ------------------------ | ------------------ |
| wikipedia.org            | 200–500 ms         |
| reddit.com               | 1.5–2 s            |
| x.com/twitter            | 1.2–1.6 s          |
| linkedin.com (logged in) | 4–5 s              |


### After navigate, always let SPA hydrate

Even after `--wait-until load`, React/Vue SPAs often render their real chrome in a second pass. Add `await sleep(2)` to `await sleep(3)` before querying for site-specific elements. Otherwise a `wait` action will fail on elements that do exist moments later.

### Reading pages efficiently

- **Prefer `hive-browser page snapshot` over `hive-browser page text "body"`** — returns a compact ~1–5 KB accessibility tree vs 100+ KB of raw HTML.
- State-changing `hive-browser interact` actions (`left_click`, `type`, `scroll`) wait 0.5 s for the page to settle after a successful action, then attach a fresh accessibility snapshot under the `snapshot` key of their result. Use it to decide your next action — do NOT run `hive-browser page snapshot` separately after every action. Tune the capture via `--auto-snapshot-mode`: `simple` (the default — trims unnamed structural nodes), `default` (full tree), `interactive` (only controls — tightest token footprint), or `off` to skip the capture entirely (useful when batching several interactions and you don't need the intermediate trees). Run `hive-browser page snapshot` explicitly only when you need a newer view or a different mode than what was auto-captured.
- Complex pages (LinkedIn, Twitter/X, SPAs with virtual scrolling) can have DOMs that don't match what's visually rendered — snapshot refs may be stale, missing, or misaligned with visible layout. Try the available snapshot first; when the target is not present in that snapshot or visual position matters, switch to `hive-browser screenshot` to orient yourself.
- Only fall back to `hive-browser page text` for extracting specific small elements by CSS selector.

## Typing and keyboard input

### ALWAYS click before typing into rich-text editors

**The single most common "looks like it worked but send button stays disabled" failure.** If you're typing into a modern editor (X/Twitter's Draft.js compose, LinkedIn's post composer, Reddit's comment box, Gmail compose, Slack, Discord, Notion, Monaco, any `contenteditable`), **click the input area first** — a `left_click` action with a `coordinate` or a `selector` — **before you type**.

Why this is necessary:

- **React / Vue controlled components** don't trust JS-sourced `.focus()`. React uses event delegation and watches for _native_ pointer/focus events — a `click` dispatched via CDP fires the real `pointerdown`/`pointerup`/`click`/`focus` sequence that React listens to, and updates its internal state. A JS-only `.focus()` sets `document.activeElement` but the framework's controlled state doesn't see it.
- **Draft.js** (X/Twitter compose) and **Lexical** (Gmail, LinkedIn DMs) use contenteditable divs with immutable editor state. They only enter "edit mode" after a real click on the editor surface. Typing at them without clicking routes keys to `document.body` or gets silently discarded.
- **Send/submit buttons are bound to framework state**, not DOM state. They're typically `disabled={!hasRealContent}` where `hasRealContent` is computed from React/Vue/Svelte state. The input field can have characters in the DOM but the button stays disabled because the framework never saw a real input event.

The symptom is always the same: **you type, the characters appear visually, and the send button doesn't enable**. The agent then clicks send anyway, nothing happens, and it thinks the post failed.

### Safe "click-then-type-then-verify" pattern

1. **Focus** the real element via a real click (not JS `.focus()`). Use `hive-browser page shadow-query "<selector>" --json` to get coordinates, then `hive-browser interact --action left_click --coordinate cx,cy --json`. Wait ~0.5 s for the editor to open and focus to settle.

2. **Type** the text with `hive-browser interact --action type --text "..." --json` — pass `--selector` for light-DOM inputs, or omit it for shadow-DOM / already-focused inputs. It uses CDP `Input.insertText` by default, the most reliable method for rich editors (Lexical, Draft.js, ProseMirror). Wait ~500 ms for framework state to commit.

3. **Verify** the submit button is enabled before clicking it. Use `hive-browser evaluate` to check the button's `disabled` or `aria-disabled` attribute. Do NOT trust that typing worked — always check state.

   **Partial visibility is fine.** Small single-line inputs, chat boxes with fixed width, and search fields commonly clip or truncate long text visually — only the tail or head may be shown on screen. Don't treat that as failure. What matters is that the framework accepted the input: the submit button enabled, or `element.value` / `innerText` read via `hive-browser evaluate` contains the full string. If the visible pixels don't match what you typed but the button is enabled and the underlying value is correct, typing succeeded — proceed.

4. **Only click send if the button is enabled.** If the button is still disabled, try the recovery dance: click the textarea again, press `End`, press a space, press `Backspace` — this forces React to recompute `hasRealContent`. Then re-check the button state.

### Why the `type` action uses `Input.insertText` by default

`Input.insertText` commits text as if IME just committed it, bypassing the keyboard event pipeline. It works on every rich editor tested — Lexical (LinkedIn DMs, Gmail), Draft.js (X compose), ProseMirror (Reddit), Monaco, plain `contenteditable` — and is what Playwright uses under the hood.

Per-character `Input.dispatchKeyEvent` looks equivalent but fails on editors that route insertion through their own `beforeinput` state machine: the keys arrive, no text appears. This left LinkedIn's composer empty (Send disabled) in the 2026-04-11 run.

For per-keystroke dispatch (autocomplete testing, key-event-driven code editors), pass `--no-use-insert-text` to fall back to the `keyDown/keyUp` path. Pacing is fixed at 1ms.

### Neutralizing `beforeunload` draft dialogs

When a composer has unsent text and you try to navigate away or close the tab, sites like LinkedIn pop a native "You have an unsent message, leave?" confirm dialog via `window.onbeforeunload`. Your automation hangs waiting on the dialog — `hive-browser tab close` and `hive-browser navigate` both time out.

**Strip the handler via `hive-browser evaluate` before navigating** (heredoc into `--js -` keeps the quote-heavy script intact; `--js @file.js` works too):

```
hive-browser evaluate --json --js - <<'JS'
(function(){
  window.onbeforeunload = null;
  window.addEventListener('beforeunload', function(e){
    e.stopImmediatePropagation();
  }, true);
  return true;
})()
JS
# Now hive-browser navigate / tab close work without hitting a confirm
```

Always include an equivalent cleanup block in any script that types into a compose UI — without it, a script crash mid-type leaves the tab in an unusable state with the draft modal blocking every subsequent automation call.

### Verified site-specific quirks

| Site                                                 | Editor                                                 | Workaround                                                                                                                                                                                                                             |
| ---------------------------------------------------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **X / Twitter** compose                              | Draft.js                                               | Click `[data-testid='tweetTextarea_0']` first, then a `type` action (default `--use-insert-text` handles Draft.js cleanly). First 1-2 chars may be eaten on the per-char fallback — accept truncation or prepend a throwaway char. Verify `[data-testid='tweetButton']` has `disabled: false` before clicking. |
| **LinkedIn** (messaging, feed compose, invites)      | Lexical / contenteditable (in `#interop-outlet`)       | Use the LinkedIn SDK — composer flows live in `hive.linkedin-core` (primitives) and `hive.linkedin-messaging` (send/reply). If debugging primitives: `hive-browser page shadow-query` for the rect, click by `--coordinate` to focus, then `type` with no `--selector` (a `--selector`-based `type` can't reach shadow). |
| **Reddit** comment/post box                          | ProseMirror                                            | Click the textarea, wait 0.5s for the toolbar to mount, then type. Submit is `button[slot="submit-button"]` inside a shreddit-composer.                                                                                                |
| **Gmail** compose                                    | Lexical                                                | Click the body first. Gmail has a visible `div[contenteditable=true][aria-label*='Message Body']` after opening a compose window.                                                                                                      |
| **Slack** message box                                | contenteditable                                        | Click first, then type. Send is a paper-plane button with `data-qa='texty_send_button'`.                                                                                                                                               |
| **Discord**                                          | Slate                                                  | Click first. Discord's send is implicit on Enter (no button), so just press Enter after typing.                                                                                                                                        |
| **Monaco** editors (GitHub code review, CodeSandbox) | Monaco                                                 | Click first, then a `type` action with `--no-use-insert-text` to force per-keystroke dispatch. Monaco listens for `textarea` input events on a hidden textarea — requires focus to be on that textarea.                               |

### Plain text into a real input

For plain `<input>` and `<textarea>` elements with no framework wrapper (forms on static sites, simple search bars that pass a selector string straight through), `hive-browser interact --action type --selector "..." --text "..." --json` is sufficient — the bridge's internal `focus()` call does the right thing. But when in doubt, click first. It's cheap insurance.

```
hive-browser interact --action type --selector "<selector>" --text "<text>" --json
```

- Sends `keyDown` (with `key`, `code`, `text` fields populated) → `keyUp` per character (or a single `Input.insertText` by default)
- Fires real `keydown` / `keypress` / `input` / `keyup` events — frameworks that branch on `event.key` or `event.code` see the right values
- Matches what Playwright and Puppeteer send

Works on real `<input>`, `<textarea>`, and `contenteditable` elements. For shadow-DOM inputs, see the "shadow-heavy sites" section above — a `selector`-based `type` can't see past shadow boundaries; use a `type` action with no selector after a `coordinate` click focuses the element.

### Keyboard shortcuts (Ctrl+A, Shift+Tab, Cmd+Enter)

```
hive-browser interact --action key --text "ctrl+a" --json        # Ctrl+A — select all
hive-browser interact --action key --text "Backspace" --json     # clear selected text
hive-browser interact --action key --text "meta+Enter" --json    # Cmd+Enter (mac) — submit
hive-browser interact --action key --text "shift+Tab" --json     # Shift+Tab — reverse focus
```

Modifiers can be joined into `--text` with `+`, or passed separately in the `--modifiers` flag (e.g. `--modifiers ctrl`). Accepted modifier names (case-insensitive): `"alt"`, `"ctrl"` / `"control"`, `"meta"` / `"cmd"`, `"shift"`.

Behind the scenes this dispatches the modifier's own `keyDown` first, then the main key with `code` and `windowsVirtualKeyCode` populated (so Chrome's shortcut dispatcher recognises it), then releases modifiers in reverse order. Without the `code` + `windowsVirtualKeyCode` fields Chrome routes the event to the DOM without firing shortcuts — which is what plain string keys get.

### Special keys

Recognized without modifiers: `Enter`, `Tab`, `Escape`, `Backspace`, `Delete`, `ArrowUp/Down/Left/Right`, `Home`, `End`, `PageUp`, `PageDown`. Use `repeat` to press a key several times in one call.

## Screenshots

```
hive-browser screenshot --json                                       # viewport, 800 px wide JPEG
hive-browser screenshot --full-page --json                           # full scrollable page (overview only)
hive-browser screenshot --selector "#header" --json                  # clip to element's rect
hive-browser interact --action screenshot --intent "..." --json      # same capture, via the interact command
hive-browser interact --action zoom --region x0,y0,x1,y1 --json      # high-res capture of one rectangle
```

Returns a JPEG (quality 75, ~50–120 KB) at 800 px wide, saved to disk; the result carries its `saved_to` path. The framework attaches the image inline on your **next turn** automatically — so do **not** also `attach_file` it. If the image does not appear inline next turn, read the `saved_to` path (the file/Read tool renders images) as a fallback. The pixel width is purely a bandwidth choice; all coordinates are fractions of the viewport and are invariant to image size. Metadata includes `imageWidth` (800), `cssWidth`, `cssHeight` (for reference), and `physicalScale`. The image is annotated with a highlight rectangle/dot showing the last interaction (click, hover, type) if one happened on this tab.

Use `--action zoom` with a fractional `--region x0,y0,x1,y1` when a control is too small to read on a full screenshot — it captures just that rectangle at a higher resolution. Zoom is for *reading*: a position read off a zoom image is relative to the crop, not the viewport. To click something, use a normal screenshot or `hive-browser page shadow-query` for the exact rect. (The zoom result carries a `crop_box` mapping the crop back to viewport fractions — on text-only models the vision-fallback caption is remapped through it automatically.)

The highlight overlay stays visible on the page for **10 seconds** after each interaction, then fades. Before a screenshot is likely, make sure your click / hover / type happens <10 s before the screenshot.

## Scrolling

- `hive-browser interact --action scroll --scroll-direction down --scroll-amount 2000 --json`. Use large amounts (~2000+) when loading more content — sites like Twitter and LinkedIn have lazy loading for paging.
- The scroll result includes a snapshot automatically — no need to run `hive-browser page snapshot` separately.
- Never re-navigate to the same URL after scrolling — this resets your scroll position and loses loaded content.

## Batching actions

- You can call multiple tools in a single turn — they execute in parallel. ALWAYS batch independent actions together. Examples: fill multiple form fields in one turn, navigate + snapshot in one turn, click + scroll if targeting different elements.
- When batching, set `--auto-snapshot-mode off` on all but the last action to avoid redundant snapshots.
- Aim for 3–5 tool calls per turn minimum. One tool call per turn is wasteful.

## Tab management

**Close tabs as soon as you are done with them** — not only at the end of the task. After reading or extracting data from a tab, close it immediately.

- Finished reading/extracting from a tab? `hive-browser tab close <T> --json`
- Completed a multi-tab workflow? List your tabs with `hive-browser tab list --json` and close each one you own with `hive-browser tab close <T> --json`
- More than 3 tabs open? Stop and close finished ones before opening more
- Popup appeared that you didn't need? Close it immediately

`hive-browser tab list --json` returns an `origin` field for each tab:

- `"agent"` — you opened it; you own it; close it when done
- `"popup"` — opened by a link or script; close after extracting what you need
- `"startup"` or `"user"` — leave these alone unless the task requires it

Never accumulate tabs. Treat every tab you open as a resource you must free.

The bridge automatically evicts per-tab state (`_cdp_attached`, `_interaction_highlights`) when a tab is closed, so you can't leak stale annotations or attached-debugger flags.

## Site-specific selectors (verified 2026-04-11)

### LinkedIn

For send/scan flows use the LinkedIn SDK (`hive.linkedin-core` + `hive.linkedin-discovery` / `hive.linkedin-messaging` / `hive.linkedin-connect`). The selectors below are for ad-hoc browsing only.

| Target              | Selector                                              |
| ------------------- | ----------------------------------------------------- |
| Global search input | `input[data-testid='typeahead-input']`                |
| Own profile link    | `a[href*='linkedin.com/in/']`                         |
| Messaging overlay   | `#interop-outlet >>> [aria-label]` (use shadow_query) |

LinkedIn enforces **strict Trusted Types CSP**. Any script you inject via `hive-browser evaluate` that uses `innerHTML = "<...>"` will be **silently dropped** — the wrapper element gets added but its content is empty, no console error. Always use `createElement` + `appendChild` + `setAttribute` for DOM injection on LinkedIn. `style.cssText`, `textContent`, and `.value` assignments are fine (they don't go through the Trusted Types sink).

### Reddit (new reddit / shreddit)

| Target                | Selector                                                                     |
| --------------------- | ---------------------------------------------------------------------------- |
| Search input (shadow) | `reddit-search-large >>> #search-input` (rect only; type via click-to-focus) |
| Reddit logo (home)    | `#reddit-logo`                                                               |
| Subreddit posts       | `shreddit-post` custom elements                                              |
| Create post button    | `a[href*='/submit']`                                                         |

Reddit's search input lives **two shadow levels deep** inside `reddit-search-large > faceplate-search-input`. You cannot reach it with a `selector`-based `type`. The working pattern:

1. `hive-browser page shadow-query "reddit-search-large >>> #search-input" --json` → rect
2. `hive-browser interact --action left_click --coordinate rect.cx,rect.cy --json` → click lands on the real shadow input via native hit testing; input becomes focused
3. `hive-browser interact --action type --text "query" --json` with no `--selector` → dispatches to focused element via `Input.insertText`
4. Verify by reading `.value` via `hive-browser evaluate` walking the shadow path

### X / Twitter

| Target                     | Selector                                      |
| -------------------------- | --------------------------------------------- |
| Main search input          | `input[data-testid='SearchBox_Search_Input']` |
| Home nav link              | `a[data-testid='AppTabBar_Home_Link']`        |
| Post text area (compose)   | `[data-testid='tweetTextarea_0']`             |
| Reply buttons on feed      | `[data-testid='reply']`                       |
| Post / Tweet submit button | `[data-testid='tweetButton']`                 |
| Caret (⋯) menu on a post   | `[data-testid='caret']`                       |
| Confirmation sheet button  | `[data-testid='confirmationSheetConfirm']`    |

**X uses Draft.js for the compose text editor**, which does NOT accept synthetic input reliably from the per-keystroke path. Working workaround: `hive-browser interact --action type --selector '[data-testid="tweetTextarea_0"]' --text "..." --json` — the default (`--use-insert-text`) commits via CDP `Input.insertText`, which Draft.js accepts cleanly. If you ever fall back to `--no-use-insert-text`, the first 1–2 characters may get eaten — accept truncation or prepend a throwaway character. After typing, check `[data-testid="tweetButton"]` has `disabled: false` before clicking submit.

After submitting, press Escape to close the composer.

## File uploads — use `hive-browser upload`, never click the upload button

**Clicking an `<input type="file">` or the button that triggers one (X's photo button, LinkedIn's attach button, Gmail's paperclip) opens Chrome's native OS file picker. That dialog is rendered by the operating system, NOT the page, so CDP cannot see it, cannot interact with it, and the automation wedges.** This is the single most common way to lock up a browser session on any "compose with media" flow.

**The only correct pattern:** run `hive-browser upload "<selector>" --file <path> --json`. It uses the CDP `DOM.setFileInputFiles` method, which sets the files directly on the input element's internal state as if the user had picked them — no OS dialog ever opens. Repeat `--file` to attach several files.

```
# WRONG — opens the native file picker, agent gets stuck
hive-browser interact --action left_click --coordinate photo_x,photo_y --json   # ❌

# RIGHT — sets the file programmatically, no dialog
hive-browser upload "input[type='file']" \
    --file /absolute/path/to/image.png \
    --json
```

**Finding the file input.** On most modern SPAs the visible "Add photo" / "Attach" button is a styled `<button>` or `<label>`, and the real `<input type="file">` is hidden (often `display:none` or `opacity:0`, positioned offscreen, wrapped in a `<label for="...">`, or injected on click). Use `hive-browser evaluate` to enumerate ALL file inputs on the page first:

```
hive-browser evaluate --json --js - <<'JS'
(function(){
  const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
  return inputs.map(el => ({
    name: el.name || '',
    accept: el.accept || '',
    multiple: el.multiple,
    id: el.id || '',
    inViewport: (() => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    })(),
  }));
})();
JS
```

Then pass the most specific selector that uniquely identifies the right input (e.g. `input[type='file'][accept*='image']` for a photo-only upload). `hive-browser upload` doesn't care if the input is hidden or offscreen — `DOM.setFileInputFiles` works on any valid file input node, visible or not.

**X / LinkedIn / Twitter pattern.** On X (`x.com/compose/post`), the photo upload input is `input[data-testid='fileInput']` — hidden, reachable via `hive-browser upload`. On LinkedIn feed compose, look for `input[type='file'][accept*='image']` inside the post-creation modal after clicking "Add media" (clicking the Add-media button reveals the input but does NOT open the dialog; only clicking the SECOND layer — the "From computer" entry — would trigger the picker. Stop at the first layer, find the input, run `hive-browser upload`).

**Verification after upload.** `DOM.setFileInputFiles` dispatches a `change` event on the input but NOT the `click` / `focus` events that some sites gate their UI on. Always verify the upload actually took effect by screenshotting the composer (the uploaded image should appear as a preview) or by checking for a "preview" / "remove" element that only exists post-upload. If verification fails, the site may be reading the file via some other bridge — fall back to reading the file bytes and pasting them via the clipboard (`navigator.clipboard.write` with a `ClipboardItem`) through `hive-browser evaluate`.

**If a native file picker DOES open** (you clicked the wrong thing): there is no recovery via CDP. Press Escape via `hive-browser interact --action key --text "Escape" --json` immediately — this dismisses the OS dialog in Chrome on Linux/macOS. Then find the actual `<input type='file'>` and use `hive-browser upload`.

## Common pitfalls

- **Typing into a rich-text editor without clicking first → send button stays disabled.** Draft.js (X), Lexical (Gmail, LinkedIn DMs), ProseMirror (Reddit), and React-controlled `contenteditable` elements only register input as "real" when the element received a native focus event — JS-sourced `.focus()` is not enough. The `type` action does this automatically via a real CDP pointer click before inserting text when given a selector, but always verify the submit button's `disabled` state before clicking send. See the "ALWAYS click before typing" section above.
- **Using per-character `keyDown` on Lexical / Draft.js editors → keys dispatch but text never appears.** Those editors intercept `beforeinput` and route insertion through their own state machine; raw keyDown events are silently dropped. The `type` action uses `Input.insertText` by default (the CDP IME-commit method) which these editors accept cleanly. Only set `--no-use-insert-text` when you explicitly need per-keystroke dispatch.
- **Leaving a composer with text then trying to navigate → `beforeunload` dialog hangs the bridge.** LinkedIn and several other sites pop a native "unsent message" confirm. `hive-browser navigate` and `hive-browser tab close` both time out against this. Always strip `window.onbeforeunload = null` via `hive-browser evaluate` before any navigation after typing in a composer, or wrap your logic in a script that runs the cleanup block on exit.
- **Click landed in the wrong region (sidebar / header instead of target).** Check `focused_element` in the click response — it's ground truth for what actually got focused, including the `inFrame` breadcrumb when focus ends up inside a same-origin iframe. If it isn't the target (e.g. `className: "msg-conversation-listitem__link"` when you meant to hit a composer), adjust the fraction and retry. Coordinates you pass are fractions of the viewport; the CLI multiplies by `cssWidth` / `cssHeight` internally, so a wrong result means your estimated proportion was off — not that any scale went sideways.
- **Accidentally passing pixels as a `--coordinate`.** The CLI rejects any coord outside `[-0.1, 1.5]` with a clear error. If you see that error, you passed a pixel (like 815) instead of a fraction (like 0.475). Use `hive-browser page shadow-query` to get exact fractional cx/cy, or read proportions off `hive-browser screenshot`.
- **Calling `--wait-for-selector` on a shadow element.** It'll always time out. Use `hive-browser page shadow-query` or the screenshot + coordinate strategy.
- **Relying on `innerHTML` in injected scripts on LinkedIn.** Silently discarded. Use `createElement` + `appendChild`.
- **Not waiting for SPA hydration.** `--wait-until load` fires before React/Vue rendering on many sites. Add a 2–3 s sleep before querying for chrome elements.
- **Using a `selector`-based `type` on LinkedIn DMs or any shadow-DOM input.** Won't find the element. Click by `coordinate` to focus, then a `type` action with no selector.
- **Clicking a "Photo" / "Attach" / "Upload" button to pick a file.** This opens Chrome's NATIVE OS file picker, which is rendered outside the web page and cannot be interacted with via CDP. Your automation will hang staring at an unreachable dialog. ALWAYS use `hive-browser upload "<selector>" --file <path> --json` against the underlying `<input type='file'>` element — see the "File uploads" section above for the full pattern. This is the single most common way to wedge a browser session on compose-with-media flows (X/LinkedIn/Gmail).
- **Keyboard shortcuts without the `code` field.** Chrome's shortcut dispatcher ignores keyboard events that lack a `code` or `windowsVirtualKeyCode`. The `key` action populates these automatically; raw `Input.dispatchKeyEvent` calls from `hive-browser evaluate` may not.
- **Taking a screenshot more than 10s after the last interaction** and expecting the highlight to still be visible. The overlay fades after 10s. Take the screenshot sooner, or re-trigger the interaction.
- **Expecting `hive-browser navigate` to return when you specified `--wait-until networkidle` on a busy site.** networkidle is approximate — some sites keep a websocket or analytics beacon open forever. Use `"load"` or `"domcontentloaded"` for reliable timing.

## Dead CDP sessions and auto-recovery

If Chrome detaches the debugger for its own reasons (tab closed, user opened DevTools manually, cross-origin navigation, `chrome://` page loaded), the bridge detects the "target closed" / "not attached" error on the next call and **automatically reattaches + retries once**. You don't need to handle this yourself.

If reattach also fails, you'll get the underlying CDP error string — that's a real problem, usually the tab is gone.

## `hive-browser evaluate` is a last-resort escape hatch

**Before using `hive-browser evaluate`, try these first — in this order:**

1. **`hive-browser screenshot` + a `--coordinate` click** — works on every site regardless of shadow DOM, iframes, obfuscated classes. This is the default path for "click a thing you can see."
2. **`hive-browser interact --action type --text "..."`** — for typing into ANY input/contenteditable, including Lexical and Draft.js. Handles click-focus-insert with built-in retries. Do **not** call `document.execCommand('insertText')` via evaluate; this action already does it correctly.
3. **`hive-browser page shadow-query "<selector>"`** — including `>>>` shadow-piercing syntax — for selector-based lookups across shadow roots.
4. **`hive-browser page text`** — for reading element text by selector (use `hive-browser evaluate` for attributes / DOM state).
5. **`hive-browser page snapshot`** — for dumping the accessibility tree of the page.

If all five of those fit your goal, **do not use `hive-browser evaluate`.** Each evaluate call is a small round-trip of ~30-100 tokens of JS plus a JSON response; five of them burn more context than a single screenshot-and-coordinate does, with less reliability.

### Anti-patterns — stop immediately if you catch yourself doing these

- **Trying multiple `querySelectorAll` variants when the first returned `[]`.** Different selectors on the same page rarely work if the first guess failed — modern SPAs obfuscate class names at build time. After one empty result, switch to `hive-browser screenshot` + a `--coordinate` click. Do not write `.artdeco-list__item`, then `[data-test-incoming-invitation-card]`, then `[class*="invitation"]` — you are already on the wrong path.
- **Writing `walk(root)` recursive shadow-DOM traversal functions.** Use `hive-browser page shadow-query` — it traverses at the CDP level (native C++), not by re-running a recursive JS function every call.
- **Calling `document.execCommand('insertText', ...)` to type into a contenteditable.** Use `hive-browser interact --action type --text "..."`. The high-level action handles the exact same Lexical/Draft.js case but with click-focus-retry logic built in.
- **Accessing `iframe.contentDocument`.** Rarely works (cross-origin, late hydration) and when it does, the code is brittle. Use `hive-browser screenshot` to see the iframe, then a `--coordinate` click to interact.
- **Using `innerHTML = "<...>"` on a Trusted Types site (LinkedIn, GitHub).** The assignment is silently dropped. Use `createElement` + `appendChild` if you must inject DOM — but first, ask whether you really need to.
- **Triggering React/Vue state via synthetic `dispatchEvent`.** Frameworks watch for real browser events. Use `hive-browser interact` `left_click` / `key` / `type` actions — all go through CDP's native event pipeline.

### Legitimate uses (when nothing semantic fits)

- Reading a computed style, `window.innerWidth/Height`, `document.scrollingElement.scrollTop`, or other layout values the tools don't expose.
- Firing a one-shot site-specific API call (analytics beacon, feature-flag toggle).
- Stripping `onbeforeunload` before navigating away from a page with an unsent draft (LinkedIn, Gmail).
- Detecting whether a specific shadow-root host exists before a follow-up screenshot.

In all of these cases the script is SHORT (< 10 lines) and the result is CONSUMED (read, then acted on), not further probed.

## Login & auth walls

- If you see a "Log in" or "Sign up" prompt, report the auth wall to user immediately — do NOT attempt to log in.
- Check for cookie consent banners and dismiss them if they block content.

## Error recovery

- If a tool fails, retry once with the same approach.
- If it fails a second time, STOP retrying and switch approach.
- If `hive-browser page snapshot` fails, try `hive-browser page text` with a specific small selector as fallback.
- If `hive-browser open` fails or page seems stale, `hive-browser stop --json`, then `hive-browser open <url> --json` again to recreate a fresh context.

## Verified workflows

These sequences have been empirically verified against real production sites on 2026-04-11.

### Search on X and read the live dropdown

```
hive-browser navigate "https://x.com/explore" --wait-until load --json
# Wait for SPA hydration
sleep 3
hive-browser interact --action wait --wait-for-selector "input[data-testid='SearchBox_Search_Input']" --timeout-ms 5000 --json
hive-browser page shadow-query "input[data-testid='SearchBox_Search_Input']" --json   # → rect
hive-browser interact --action left_click --coordinate rect.cx,rect.cy --json
hive-browser interact --action type --selector "input[data-testid='SearchBox_Search_Input']" --text "openai" --clear-first --json
# Screenshot now shows live search suggestions
hive-browser screenshot --json
hive-browser interact --action key --selector "input[data-testid='SearchBox_Search_Input']" --text "Escape" --json
```

### Search Reddit (shadow DOM)

```
hive-browser navigate "https://www.reddit.com/r/programming/" --wait-until load --json
sleep 2
# Shadow-pierce the nested search input
hive-browser page shadow-query "reddit-search-large >>> #search-input" --json   # → rect
hive-browser interact --action left_click --coordinate rect.cx,rect.cy --json
# Typing can't use --selector (shadow); a type action with no selector hits the focused input
hive-browser interact --action type --text "python" --json
hive-browser screenshot --json
hive-browser interact --action key --text "Escape" --json
```

## Debugging checklist when a click / type "didn't work"

1. **Send button stays disabled after typing?** Two possible causes. (a) You didn't click the input first, so React never saw a native focus event. A `--selector`-based `type` clicks automatically — but if you're using raw `Input.dispatchKeyEvent`, click first yourself. (b) You're using per-character `keyDown` on a Lexical / Draft.js editor, and those editors dropped the keys because they listen for `beforeinput` with a specific shape. Use the `type` action (which uses `Input.insertText` by default) or, at a lower level, call CDP `Input.insertText` directly. Always `hive-browser evaluate` the submit button's `disabled` / `aria-disabled` state before clicking send; if still disabled after those fixes, the framework never saw real input.
2. **Did the selector match anything?** Run `hive-browser page shadow-query "<selector>" --json` — if it returns `visible=False` or zero rect, the element isn't laid out yet. Wait longer or use a different selector.
3. **Is the element inside a shadow root?** Try `hive-browser page shadow-query "<path>" --json`. If your selector is light-DOM only, switch to the screenshot + coordinate strategy.
4. **Did the click hit something on top of the element?** Register a temporary event listener via `hive-browser evaluate` on the target element, click, then read `window.__hits` to see what actually received the click. If something else is intercepting (overlay, modal, floating button), dismiss it first.
5. **Did the `type` action find the element but fail to insert text?** Some editors (Draft.js on X, ProseMirror on some sites, Monaco) reject the default `Input.insertText` path or the bulk per-char dispatch. Stick with the default `--use-insert-text` first; if that still fails, pass `--no-use-insert-text` to fall back to the per-keystroke `keyDown/keyUp` path.
6. **Is this a keyboard shortcut that doesn't fire?** Make sure you're using `hive-browser interact --action key --text "..." --modifiers ... --json` — not raw `hive-browser evaluate` with `dispatchEvent`. Chrome ignores shortcut key events that lack `code` and `windowsVirtualKeyCode`.
7. **Did the navigation actually complete?** Check the return value of `hive-browser navigate` — it returns a real `url` and `title`. An empty title usually means a blank page or a hung load.
8. **Is your screenshot stale?** The highlight overlay stays for 10 s; if the screenshot was taken later, the annotation is gone but the click was real. Check the telemetry of the `left_click` action to see the coordinates that were actually sent.
