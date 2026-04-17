---
name: hive.browser-automation
description: Required before any browser_* tool call. Teaches the screenshot + browser_click_coordinate workflow that reaches shadow-DOM inputs selectors can't see, the CSS-pixel coordinate rule (not physical px), rich-text editor quirks ("send button stays disabled" failures), and CSP gotchas. Covers Chrome via CDP through the GCU Beeline extension. Skipping this causes repeated failures on LinkedIn / Reddit / X. Verified against real production sites 2026-04-11.
metadata:
  author: hive
  type: default-skill
  version: "2.0"
  verified: 2026-04-11
---

# GCU Browser Automation

All GCU browser tools drive a real Chrome instance through the Beeline extension and Chrome DevTools Protocol (CDP). That means clicks, keystrokes, and screenshots are processed by the actual browser's native hit testing, focus, and layout engines — **not** a synthetic event layer. Understanding this unlocks strategies that make hard sites easy.

## Coordinates

Every browser tool that takes or returns coordinates operates in **fractions of the viewport (0..1 for both axes)**. Read a target's proportional position off `browser_screenshot` — "this button is about 35% from the left and 20% from the top" → pass `(0.35, 0.20)`. Rect-returning tools (`browser_get_rect`, `browser_shadow_query`, and the `rect` inside `focused_element`) also return fractions. The tools convert to CSS pixels internally before dispatching to Chrome.

```
browser_screenshot()                  → image + cssWidth/cssHeight in meta
browser_click_coordinate(x, y)        → x, y are fractions 0..1
browser_hover_coordinate(x, y)        → fractions
browser_press_at(x, y, key)           → fractions
browser_get_rect(selector) → rect     → rect.cx / rect.cy are fractions
browser_shadow_query(...)  → rect     → same
```

**Why fractions:** every vision model (Claude ~1.15 MP target, GPT-4o 512-px tiles, Gemini, local VLMs) resizes or tiles images differently before the model sees the pixels. Proportions survive every such transform; pixel coordinates only "work" per-model and silently break when you swap backends. Four-decimal precision (`0.0001` ≈ 0.17 CSS px on a 1717-wide viewport) is more than enough for the tightest targets.

**Exception for zoomed elements:** pages that use `zoom` or `transform: scale()` on a container (LinkedIn's `#interop-outlet`, some embedded iframes) render in a scaled local coordinate space. `getBoundingClientRect` there may not match CDP's hit space. Prefer `browser_shadow_query` (which handles the math and returns fractions) or visually pick coordinates from a screenshot. Avoid raw `browser_evaluate` + `getBoundingClientRect()` for coord lookup — that returns CSS px and will be wrong when fed to click tools.

## Screenshot + coordinates is shadow-agnostic — prefer it on shadow-heavy sites

On sites that use Shadow DOM heavily (Reddit's faceplate Web Components, LinkedIn's `#interop-outlet` messaging overlay, some X custom elements), **coordinate-based operations reach elements that selector-based tools can't see.**

Why:

- **CDP hit testing walks shadow roots natively.** `browser_click_coordinate(x, y)` routes through Chrome's native hit tester, which traverses open shadow roots automatically. You don't need to know the shadow structure.
- **Keyboard dispatch follows focus** into shadow roots. After a click focuses an input (even one three shadow levels deep), `browser_press(...)` with no selector dispatches keys to `document.activeElement`'s computed focus target.
- **Screenshots render the real layout** regardless of DOM implementation.

Whereas `wait_for_selector`, `browser_click(selector=...)`, `browser_type(selector=...)` all use `document.querySelector` under the hood, which **stops at shadow boundaries**. They cannot see elements inside shadow roots. For shadow-DOM inputs, use `browser_type_focused` after focusing via click-coordinate.

### Recommended workflow on shadow-heavy sites

1. `browser_screenshot()` → JPEG; meta includes `cssWidth`/`cssHeight` for reference.
2. Identify the target visually → estimate its proportional position `(fx, fy)` where each is in `0..1`.
3. `browser_click_coordinate(fx, fy)` → tool converts to CSS px and dispatches; CDP native hit testing focuses the element. **The response includes `focused_element: {tag, id, role, contenteditable, rect, inFrame?, ...}`** — use it to verify you actually focused what you intended. `rect` is in fractions (same space as your input). When focus is inside a same-origin iframe, the descriptor reports the inner element and adds `inFrame: [...]` breadcrumbs.
4. `browser_type_focused(text="...")` → inserts text into `document.activeElement` (traverses into same-origin iframes automatically). Shadow roots, iframes, Lexical, Draft.js, ProseMirror all just work. Use `browser_type(selector, text)` instead when you have a reliable CSS selector for a light-DOM element.
5. Verify via `browser_screenshot` OR `browser_get_attribute` on a known-reachable marker (e.g. check that the Send button's `aria-disabled` flipped to `false`).

### The click→type loop (canonical pattern)

1. Call `browser_click_coordinate(x, y)` to click the target element.
2. Check the `focused_element` field in the response — it tells you what actually received focus (tag, id, role, contenteditable, rect).
3. If the focused element is editable, call `browser_type_focused(text="...")` to insert text. Use tools to verify the text took effect — prefer checking the underlying `.value` / `innerText` via `browser_evaluate` or confirming the submit button enabled. A screenshot alone can mislead: narrow input boxes visually clip long text, so only a portion may appear on screen even though the full string was accepted.
4. If it is NOT editable, your click landed on the wrong thing — refine coordinates and retry. Do NOT reach for `browser_evaluate` + `execCommand('insertText')` or shadow-root traversals. The problem is the click target, not the typing method.

`browser_click` (selector-based) also returns `focused_element`, so the same check works whether you clicked by selector or coordinate.

### Empirically verified (2026-04-11)

Tested against `https://www.reddit.com/r/programming/` whose search input lives at:

```
document > reddit-search-large [shadow]
         > faceplate-search-input#search-input [shadow]
         > input[name="q"]
```

### Shadow-piercing selectors

When you DO want a selector-based approach and know the shadow structure, `browser_shadow_query` and `browser_get_rect` support `>>>` shadow-piercing syntax:

```
browser_shadow_query("reddit-search-large >>> #search-input")
browser_get_rect("#interop-outlet >>> #ember37 >>> p")
```

Returns the element's rect as **fractions of the viewport** (feed `rect.cx` / `rect.cy` directly to click tools). Remember: `browser_type` and `wait_for_selector` do **not** support `>>>` — only shadow_query and get_rect do.

## Navigation and waiting

### The basics

```
browser_navigate(url, wait_until="load")   # "load" | "domcontentloaded" | "networkidle"
browser_wait_for_selector("h1", timeout_ms=2000)
browser_wait_for_text("Some text", timeout_ms=2000)
browser_go_back()
browser_go_forward()
browser_reload()
```

All return real URLs and titles. On a fast page `navigate(wait_until="load")` returns in sub-second. `wait_for_selector` and `wait_for_text` typically resolve in single-digit milliseconds on elements already in the DOM.

### Timing expectations (measured against real sites)

| Site                     | Navigate load time |
| ------------------------ | ------------------ |
| example.com              | 100–400 ms         |
| wikipedia.org            | 200–500 ms         |
| reddit.com               | 1.5–2 s            |
| x.com/twitter            | 1.2–1.6 s          |
| linkedin.com (logged in) | 4–5 s              |

For LinkedIn and other heavy SPAs, rely on `sleep()` after navigation to let the page hydrate.

### After navigate, always let SPA hydrate

Even after `wait_until="load"`, React/Vue SPAs often render their real chrome in a second pass. Add `await sleep(2)` to `await sleep(3)` before querying for site-specific elements. Otherwise `wait_for_selector` will fail on elements that do exist moments later.

### Reading pages efficiently

- **Prefer `browser_snapshot` over `browser_get_text("body")`** — returns a compact ~1–5 KB accessibility tree vs 100+ KB of raw HTML.
- Interaction tools (`browser_click`, `browser_type`, `browser_type_focused`, `browser_fill`, `browser_scroll`, etc.) return a page snapshot automatically in their result. Use it to decide your next action — do NOT call `browser_snapshot` separately after every action. Only call `browser_snapshot` when you need a fresh view without performing an action, or after setting `auto_snapshot=false`.
- Complex pages (LinkedIn, Twitter/X, SPAs with virtual scrolling) have DOMs that don't match what's visually rendered — snapshot refs may be stale, missing, or misaligned with visible layout. On these pages, `browser_screenshot` is the only reliable way to orient yourself.
- Only fall back to `browser_get_text` for extracting specific small elements by CSS selector.

## Typing and keyboard input

### ALWAYS click before typing into rich-text editors

**The single most common "looks like it worked but send button stays disabled" failure.** If you're typing into a modern editor (X/Twitter's Draft.js compose, LinkedIn's post composer, Reddit's comment box, Gmail compose, Slack, Discord, Notion, Monaco, any `contenteditable`), **click the input area first with `browser_click_coordinate` or `browser_click(selector)` before you type**.

Why this is necessary:

- **React / Vue controlled components** don't trust JS-sourced `.focus()`. React uses event delegation and watches for _native_ pointer/focus events — a `click` dispatched via CDP fires the real `pointerdown`/`pointerup`/`click`/`focus` sequence that React listens to, and updates its internal state. A JS-only `.focus()` sets `document.activeElement` but the framework's controlled state doesn't see it.
- **Draft.js** (X/Twitter compose) and **Lexical** (Gmail, LinkedIn DMs) use contenteditable divs with immutable editor state. They only enter "edit mode" after a real click on the editor surface. Typing at them without clicking routes keys to `document.body` or gets silently discarded.
- **Send/submit buttons are bound to framework state**, not DOM state. They're typically `disabled={!hasRealContent}` where `hasRealContent` is computed from React/Vue/Svelte state. The input field can have characters in the DOM but the button stays disabled because the framework never saw a real input event.

The symptom is always the same: **you type, the characters appear visually, and the send button doesn't enable**. The agent then clicks send anyway, nothing happens, and it thinks the post failed.

### Safe "click-then-type-then-verify" pattern

1. **Focus** the real element via a real click (not JS `.focus()`). Use `browser_get_rect(selector)` (or `browser_shadow_query` for shadow sites) to get coordinates, then `browser_click_coordinate(cx, cy)`. Wait ~0.5 s for the editor to open and focus to settle.

2. **Type** the text. Use `browser_type(selector, text)` for light-DOM inputs, or `browser_type_focused(text=...)` for shadow-DOM / already-focused inputs. Both use CDP `Input.insertText` by default, which is the most reliable method for rich editors (Lexical, Draft.js, ProseMirror). Wait ~500 ms for framework state to commit.

3. **Verify** the submit button is enabled before clicking it. Use `browser_evaluate` to check the button's `disabled` or `aria-disabled` attribute. Do NOT trust that typing worked — always check state.

   **Partial visibility is fine.** Small single-line inputs, chat boxes with fixed width, and search fields commonly clip or truncate long text visually — only the tail or head may be shown on screen. Don't treat that as failure. What matters is that the framework accepted the input: the submit button enabled, or `element.value` / `innerText` read via `browser_evaluate` contains the full string. If the visible pixels don't match what you typed but the button is enabled and the underlying value is correct, typing succeeded — proceed.

4. **Only click send if the button is enabled.** If the button is still disabled, try the recovery dance: click the textarea again, press `End`, press a space, press `Backspace` — this forces React to recompute `hasRealContent`. Then re-check the button state.

### Why `browser_type` uses `Input.insertText` by default

CDP has a dedicated method — `Input.insertText` — for committing text into the focused element as if IME just committed it. It **bypasses the keyboard event pipeline entirely** and works cleanly on every rich-text editor tested to date: Lexical (LinkedIn DMs, Gmail), Draft.js (X compose), ProseMirror (Reddit), Monaco, and plain `contenteditable`. Playwright uses this under the hood for `keyboard.type()` on rich editors.

Per-character `Input.dispatchKeyEvent` looks equivalent on paper, but some rich editors listen for `beforeinput` events with a specific shape and route insertion through their own state machine — the raw keys arrive but never get turned into text. That was the exact failure mode that left LinkedIn's message composer empty (and its Send button disabled) during the 2026-04-11 empirical run.

If you need per-keystroke dispatch (autocomplete testing, code editors, animated typing with `delay_ms`), pass `use_insert_text=False` to fall back to the old `keyDown/keyUp` path.

### Neutralizing `beforeunload` draft dialogs

When a composer has unsent text and you try to navigate away or close the tab, sites like LinkedIn pop a native "You have an unsent message, leave?" confirm dialog via `window.onbeforeunload`. Your automation hangs waiting on the dialog — `browser_close_tab` and `browser_navigate` both time out.

**Strip the handler via `browser_evaluate` before navigating:**

```
browser_evaluate("""
    (function(){
      window.onbeforeunload = null;
      window.addEventListener('beforeunload', function(e){
        e.stopImmediatePropagation();
      }, true);
      return true;
    })()
""")
# Now browser_navigate / close_tab work without hitting a confirm
```

Always include an equivalent cleanup block in any script that types into a compose UI — without it, a script crash mid-type leaves the tab in an unusable state with the draft modal blocking every subsequent automation call.

### Verified site-specific quirks

| Site                                                 | Editor                                                 | Workaround                                                                                                                                                                                                                             |
| ---------------------------------------------------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **X / Twitter** compose                              | Draft.js                                               | Click `[data-testid='tweetTextarea_0']` first, then type with `delay_ms=20`. First 1-2 chars may be eaten — accept truncation or prepend a throwaway char. Verify `[data-testid='tweetButton']` has `disabled: false` before clicking. |
| **LinkedIn** messaging                               | contenteditable (inside `#interop-outlet` shadow root) | Use `browser_shadow_query` to find the rect, click-coordinate to focus, then `browser_type_focused(text=...)` (selector-based `browser_type` can't reach shadow). Send button is `.msg-form__send-button`.                             |
| **LinkedIn** feed post composer                      | Quill/LinkedIn custom                                  | Click the "Start a post" trigger first, wait 1s for modal, click the textarea, type.                                                                                                                                                   |
| **Reddit** comment/post box                          | ProseMirror                                            | Click the textarea, wait 0.5s for the toolbar to mount, then type. Submit is `button[slot="submit-button"]` inside a shreddit-composer.                                                                                                |
| **Gmail** compose                                    | Lexical                                                | Click the body first. Gmail has a visible `div[contenteditable=true][aria-label*='Message Body']` after opening a compose window.                                                                                                      |
| **Slack** message box                                | contenteditable                                        | Click first, then type. Send is a paper-plane button with `data-qa='texty_send_button'`.                                                                                                                                               |
| **Discord**                                          | Slate                                                  | Click first. Discord's send is implicit on Enter (no button), so just press Enter after typing.                                                                                                                                        |
| **Monaco** editors (GitHub code review, CodeSandbox) | Monaco                                                 | Click first, type with `delay_ms=10`. Monaco listens for `textarea` input events on a hidden textarea — requires focus to be on that textarea.                                                                                         |

### Plain text into a real input

For plain `<input>` and `<textarea>` elements with no framework wrapper (forms on static sites, simple search bars that pass a selector string straight through), `browser_type(selector, text)` is sufficient — the bridge's internal `focus()` call does the right thing. But when in doubt, click first. It's cheap insurance.

```
browser_type(selector, text)
```

- Sends `keyDown` (with `key`, `code`, `text` fields populated) → `keyUp` per character (or a single `Input.insertText` by default)
- Fires real `keydown` / `keypress` / `input` / `keyup` events — frameworks that branch on `event.key` or `event.code` see the right values
- Matches what Playwright and Puppeteer send

Works on real `<input>`, `<textarea>`, and `contenteditable` elements. For shadow-DOM inputs, see the "shadow-heavy sites" section above — `browser_type(selector=)` can't see past shadow boundaries; use `browser_type_focused` after click-coordinate focus.

### Keyboard shortcuts (Ctrl+A, Shift+Tab, Cmd+Enter)

```
browser_press("a", modifiers=["ctrl"])         # Ctrl+A — select all
browser_press("Backspace")                      # clear selected text
browser_press("Enter", modifiers=["meta"])     # Cmd+Enter (mac) — submit
browser_press("Tab", modifiers=["shift"])      # Shift+Tab — reverse focus
```

Accepted modifier names (case-insensitive): `"alt"`, `"ctrl"` / `"control"`, `"meta"` / `"cmd"`, `"shift"`.

Behind the scenes this dispatches the modifier's own `keyDown` first, then the main key with `code` and `windowsVirtualKeyCode` populated (so Chrome's shortcut dispatcher recognises it), then releases modifiers in reverse order. Without the `code` + `windowsVirtualKeyCode` fields Chrome routes the event to the DOM without firing shortcuts — which is what plain string keys get.

### Special keys

Recognized without modifiers: `Enter`, `Tab`, `Escape`, `Backspace`, `Delete`, `ArrowUp/Down/Left/Right`, `Home`, `End`, `PageUp`, `PageDown`.

## Screenshots

```
browser_screenshot()                    # viewport, 800 px wide JPEG
browser_screenshot(full_page=True)      # full scrollable page (overview only — don't click off a full-page shot)
browser_screenshot(selector="#header")  # clip to element's rect
```

Returns a JPEG (quality 75, ~50–120 KB) at 800 px wide. The pixel width is purely a bandwidth choice; all tool coordinates are fractions of the viewport and are invariant to image size. Metadata includes `imageWidth` (800), `cssWidth`, `cssHeight` (for reference), and `physicalScale`. The image is annotated with a highlight rectangle/dot showing the last interaction (click, hover, type) if one happened on this tab.

The highlight overlay stays visible on the page for **10 seconds** after each interaction, then fades. Before a screenshot is likely, make sure your click / hover / type happens <10 s before the screenshot.

## Scrolling

- Use large scroll amounts (~2000) when loading more content — sites like Twitter and LinkedIn have lazy loading for paging.
- The scroll result includes a snapshot automatically — no need to call `browser_snapshot` separately.
- Never re-navigate to the same URL after scrolling — this resets your scroll position and loses loaded content.

## Batching actions

- You can call multiple tools in a single turn — they execute in parallel. ALWAYS batch independent actions together. Examples: fill multiple form fields in one turn, navigate + snapshot in one turn, click + scroll if targeting different elements.
- When batching, set `auto_snapshot=false` on all but the last action to avoid redundant snapshots.
- Aim for 3–5 tool calls per turn minimum. One tool call per turn is wasteful.

## Tab management

**Close tabs as soon as you are done with them** — not only at the end of the task. After reading or extracting data from a tab, close it immediately.

- Finished reading/extracting from a tab? `browser_close(target_id=...)`
- Completed a multi-tab workflow? `browser_close_finished()` to clean up all your tabs
- More than 3 tabs open? Stop and close finished ones before opening more
- Popup appeared that you didn't need? Close it immediately

`browser_tabs` returns an `origin` field for each tab:

- `"agent"` — you opened it; you own it; close it when done
- `"popup"` — opened by a link or script; close after extracting what you need
- `"startup"` or `"user"` — leave these alone unless the task requires it

Never accumulate tabs. Treat every tab you open as a resource you must free.

The bridge automatically evicts per-tab state (`_cdp_attached`, `_interaction_highlights`) when a tab is closed, so you can't leak stale annotations or attached-debugger flags.

## Site-specific selectors (verified 2026-04-11)

### LinkedIn

| Target              | Selector                                              |
| ------------------- | ----------------------------------------------------- |
| Global search input | `input[data-testid='typeahead-input']`                |
| Own profile link    | `a[href*='linkedin.com/in/']`                         |
| Messaging overlay   | `#interop-outlet >>> [aria-label]` (use shadow_query) |

LinkedIn enforces **strict Trusted Types CSP**. Any script you inject via `browser_evaluate` that uses `innerHTML = "<...>"` will be **silently dropped** — the wrapper element gets added but its content is empty, no console error. Always use `createElement` + `appendChild` + `setAttribute` for DOM injection on LinkedIn. `style.cssText`, `textContent`, and `.value` assignments are fine (they don't go through the Trusted Types sink).

### Reddit (new reddit / shreddit)

| Target                | Selector                                                                     |
| --------------------- | ---------------------------------------------------------------------------- |
| Search input (shadow) | `reddit-search-large >>> #search-input` (rect only; type via click-to-focus) |
| Reddit logo (home)    | `#reddit-logo`                                                               |
| Subreddit posts       | `shreddit-post` custom elements                                              |
| Create post button    | `a[href*='/submit']`                                                         |

Reddit's search input lives **two shadow levels deep** inside `reddit-search-large > faceplate-search-input`. You cannot reach it with `browser_type(selector=)`. The working pattern:

1. `browser_shadow_query("reddit-search-large >>> #search-input")` → rect
2. `browser_click_coordinate(rect.cx, rect.cy)` → click lands on the real shadow input via native hit testing; input becomes focused
3. `browser_type_focused(text="query")` → dispatches to focused element via `Input.insertText`
4. Verify by reading `.value` via `browser_evaluate` walking the shadow path

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

**X uses Draft.js for the compose text editor**, which does NOT accept synthetic input reliably. Working workaround: `browser_type(selector='[data-testid="tweetTextarea_0"]', text="...", delay_ms=20)`. The delay gives Draft.js time to process each keystroke. The first 1–2 characters may still get eaten — accept minor truncation or prepend a throwaway character. After typing, check `[data-testid="tweetButton"]` has `disabled: false` before clicking submit.

After submitting, press Escape to close the composer.

## File uploads — use `browser_upload`, never click the upload button

**Clicking an `<input type="file">` or the button that triggers one (X's photo button, LinkedIn's attach button, Gmail's paperclip) opens Chrome's native OS file picker. That dialog is rendered by the operating system, NOT the page, so CDP cannot see it, cannot interact with it, and the automation wedges.** This is the single most common way to lock up a browser session on any "compose with media" flow.

**The only correct pattern:** call `browser_upload(selector, file_paths)`. It uses the CDP `DOM.setFileInputFiles` method, which sets the files directly on the input element's internal state as if the user had picked them — no OS dialog ever opens.

```
# WRONG — opens the native file picker, agent gets stuck
browser_click_coordinate(photo_button_x, photo_button_y)   # ❌

# RIGHT — sets the file programmatically, no dialog
browser_upload(
    selector="input[type='file']",          # the underlying file input
    file_paths=["/absolute/path/to/image.png"],
)
```

**Finding the file input.** On most modern SPAs the visible "Add photo" / "Attach" button is a styled `<button>` or `<label>`, and the real `<input type="file">` is hidden (often `display:none` or `opacity:0`, positioned offscreen, wrapped in a `<label for="...">`, or injected on click). Use `browser_evaluate` to enumerate ALL file inputs on the page first:

```python
browser_evaluate("""
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
""")
```

Then pass the most specific selector that uniquely identifies the right input (e.g. `input[type='file'][accept*='image']` for a photo-only upload). `browser_upload` doesn't care if the input is hidden or offscreen — `DOM.setFileInputFiles` works on any valid file input node, visible or not.

**X / LinkedIn / Twitter pattern.** On X (`x.com/compose/post`), the photo upload input is `input[data-testid='fileInput']` — hidden, reachable via `browser_upload`. On LinkedIn feed compose, look for `input[type='file'][accept*='image']` inside the post-creation modal after clicking "Add media" (clicking the Add-media button reveals the input but does NOT open the dialog; only clicking the SECOND layer — the "From computer" entry — would trigger the picker. Stop at the first layer, find the input, call `browser_upload`).

**Verification after upload.** `DOM.setFileInputFiles` dispatches a `change` event on the input but NOT the `click` / `focus` events that some sites gate their UI on. Always verify the upload actually took effect by screenshotting the composer (the uploaded image should appear as a preview) or by checking for a "preview" / "remove" element that only exists post-upload. If verification fails, the site may be reading the file via some other bridge — fall back to reading the file bytes and pasting them via the clipboard (`navigator.clipboard.write` with a `ClipboardItem`) through `browser_evaluate`.

**If a native file picker DOES open** (you clicked the wrong thing): there is no recovery via CDP. Press Escape via `browser_press("Escape")` immediately — this dismisses the OS dialog in Chrome on Linux/macOS. Then find the actual `<input type='file'>` and use `browser_upload`.

## Common pitfalls

- **Typing into a rich-text editor without clicking first → send button stays disabled.** Draft.js (X), Lexical (Gmail, LinkedIn DMs), ProseMirror (Reddit), and React-controlled `contenteditable` elements only register input as "real" when the element received a native focus event — JS-sourced `.focus()` is not enough. `browser_type` now does this automatically via a real CDP pointer click before inserting text, but always verify the submit button's `disabled` state before clicking send. See the "ALWAYS click before typing" section above.
- **Using per-character `keyDown` on Lexical / Draft.js editors → keys dispatch but text never appears.** Those editors intercept `beforeinput` and route insertion through their own state machine; raw keyDown events are silently dropped. `browser_type` now uses `Input.insertText` by default (the CDP IME-commit method) which these editors accept cleanly. Only set `use_insert_text=False` when you explicitly need per-keystroke dispatch.
- **Leaving a composer with text then trying to navigate → `beforeunload` dialog hangs the bridge.** LinkedIn and several other sites pop a native "unsent message" confirm. `browser_navigate` and `close_tab` both time out against this. Always strip `window.onbeforeunload = null` via `browser_evaluate` before any navigation after typing in a composer, or wrap your logic in a `try/finally` that runs the cleanup block.
- **Click landed in the wrong region (sidebar / header instead of target).** Check `focused_element` in the click response — it's ground truth for what actually got focused, including the `inFrame` breadcrumb when focus ends up inside a same-origin iframe. If it isn't the target (e.g. `className: "msg-conversation-listitem__link"` when you meant to hit a composer), adjust the fraction and retry. Coordinates you pass are fractions of the viewport; the tool multiplies by `cssWidth` / `cssHeight` internally, so a wrong result means your estimated proportion was off — not that any scale went sideways.
- **Accidentally passing pixels to click / hover / press_at.** The tools reject any coord outside `[-0.1, 1.5]` with a clear error. If you see that error, you passed a pixel (like 815) instead of a fraction (like 0.475). Use `browser_get_rect` to get exact fractional cx/cy, or read proportions off `browser_screenshot`.
- **Calling `wait_for_selector` on a shadow element.** It'll always time out. Use `browser_shadow_query` or the screenshot + coordinate strategy.
- **Relying on `innerHTML` in injected scripts on LinkedIn.** Silently discarded. Use `createElement` + `appendChild`.
- **Not waiting for SPA hydration.** `wait_until="load"` fires before React/Vue rendering on many sites. Add a 2–3 s sleep before querying for chrome elements.
- **Using `browser_type(selector)` on LinkedIn DMs or any shadow-DOM input.** Won't find the element. Use `browser_click_coordinate` to focus, then `browser_type_focused(text=...)` to type.
- **Clicking a "Photo" / "Attach" / "Upload" button to pick a file.** This opens Chrome's NATIVE OS file picker, which is rendered outside the web page and cannot be interacted with via CDP. Your automation will hang staring at an unreachable dialog. ALWAYS use `browser_upload(selector, file_paths)` against the underlying `<input type='file'>` element — see the "File uploads" section above for the full pattern. This is the single most common way to wedge a browser session on compose-with-media flows (X/LinkedIn/Gmail).
- **Keyboard shortcuts without the `code` field.** Chrome's shortcut dispatcher ignores keyboard events that lack a `code` or `windowsVirtualKeyCode`. `browser_press(..., modifiers=[...])` populates these automatically; raw `Input.dispatchKeyEvent` calls from `browser_evaluate` may not.
- **Taking a screenshot more than 10s after the last interaction** and expecting the highlight to still be visible. The overlay fades after 10s. Take the screenshot sooner, or re-trigger the interaction.
- **Expecting `browser_navigate` to return when you specified `wait_until="networkidle"` on a busy site.** networkidle is approximate — some sites keep a websocket or analytics beacon open forever. Use `"load"` or `"domcontentloaded"` for reliable timing.

## Dead CDP sessions and auto-recovery

If Chrome detaches the debugger for its own reasons (tab closed, user opened DevTools manually, cross-origin navigation, `chrome://` page loaded), the bridge detects the "target closed" / "not attached" error on the next call and **automatically reattaches + retries once**. You don't need to handle this yourself.

If reattach also fails, you'll get the underlying CDP error string — that's a real problem, usually the tab is gone.

## `browser_evaluate` is a last-resort escape hatch

**Before using `browser_evaluate`, try these first — in this order:**

1. **`browser_screenshot` + `browser_click_coordinate`** — works on every site regardless of shadow DOM, iframes, obfuscated classes. This is the default path for "click a thing you can see."
2. **`browser_type(use_insert_text=True, text=...)`** — for typing into ANY input/contenteditable, including Lexical and Draft.js. Handles click-focus-insert with built-in retries. Do **not** call `document.execCommand('insertText')` via evaluate; this tool already does it correctly.
3. **`browser_shadow_query`** or **`browser_get_rect(selector)`** with the `>>>` shadow-piercing syntax — for selector-based lookups across shadow roots.
4. **`browser_get_text` / `browser_get_attribute`** — for reading element state by selector.
5. **`browser_snapshot`** — for dumping the accessibility tree of the page.

If all five of those fit your goal, **do not use `browser_evaluate`.** Each evaluate call is a small LLM round-trip of ~30-100 tokens of JS plus a JSON response; five of them burn more context than a single screenshot-and-coordinate does, with less reliability.

### Anti-patterns — stop immediately if you catch yourself doing these

- **Trying multiple `querySelectorAll` variants when the first returned `[]`.** Different selectors on the same page rarely work if the first guess failed — modern SPAs obfuscate class names at build time. After one empty result, switch to `browser_screenshot` + `browser_click_coordinate`. Do not write `.artdeco-list__item`, then `[data-test-incoming-invitation-card]`, then `[class*="invitation"]` — you are already on the wrong path.
- **Writing `walk(root)` recursive shadow-DOM traversal functions.** Use `browser_shadow_query` — it traverses at the CDP level (native C++), not by re-running a recursive JS function every call.
- **Calling `document.execCommand('insertText', ...)` to type into a contenteditable.** Use `browser_type(use_insert_text=True, text='...')`. The high-level tool handles the exact same Lexical/Draft.js case but with click-focus-retry logic built in.
- **Accessing `iframe.contentDocument`.** Rarely works (cross-origin, late hydration) and when it does, the code is brittle. Use `browser_screenshot` to see the iframe, then `browser_click_coordinate` to interact.
- **Using `innerHTML = "<...>"` on a Trusted Types site (LinkedIn, GitHub).** The assignment is silently dropped. Use `createElement` + `appendChild` if you must inject DOM — but first, ask whether you really need to.
- **Triggering React/Vue state via synthetic `dispatchEvent`.** Frameworks watch for real browser events. Use `browser_click_coordinate`, `browser_press`, or `browser_type` — all go through CDP's native event pipeline.

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
- If `browser_snapshot` fails, try `browser_get_text` with a specific small selector as fallback.
- If `browser_open` fails or page seems stale, `browser_stop`, then `browser_start`, then retry.

## Verified workflows

These sequences have been empirically verified against real production sites on 2026-04-11.

### Search on X and read the live dropdown

```
browser_navigate("https://x.com/explore", wait_until="load")
# Wait for SPA hydration
sleep(3)
browser_wait_for_selector("input[data-testid='SearchBox_Search_Input']", timeout_ms=5000)
rect = browser_get_rect("input[data-testid='SearchBox_Search_Input']")
browser_click_coordinate(rect.cx, rect.cy)
browser_type("input[data-testid='SearchBox_Search_Input']", "openai", clear_first=True)
# Screenshot now shows live search suggestions
browser_screenshot()
browser_press("Escape", selector="input[data-testid='SearchBox_Search_Input']")
```

### Search Reddit (shadow DOM)

```
browser_navigate("https://www.reddit.com/r/programming/", wait_until="load")
sleep(2)
# Shadow-pierce the nested search input
sq = browser_shadow_query("reddit-search-large >>> #search-input")
browser_click_coordinate(sq.rect.cx, sq.rect.cy)
# Typing can't use selector (shadow); use browser_type_focused on the focused input
browser_type_focused(text="python")
browser_screenshot()
browser_press("Escape")
```

### Search LinkedIn and dismiss without submitting

```
browser_navigate("https://www.linkedin.com/feed/", wait_until="load")
sleep(3)
browser_wait_for_selector("input[data-testid='typeahead-input']", timeout_ms=5000)
rect = browser_get_rect("input[data-testid='typeahead-input']")
browser_click_coordinate(rect.cx, rect.cy)
browser_type("input[data-testid='typeahead-input']", "anthropic", clear_first=True)
# Dropdown shows real live suggestions
browser_screenshot()
browser_press("Escape", selector="input[data-testid='typeahead-input']")
```

## Debugging checklist when a click / type "didn't work"

1. **Send button stays disabled after typing?** Two possible causes. (a) You didn't click the input first, so React never saw a native focus event. `browser_type` now clicks automatically — but if you're using raw `Input.dispatchKeyEvent`, click first yourself. (b) You're using per-character `keyDown` on a Lexical / Draft.js editor, and those editors dropped the keys because they listen for `beforeinput` with a specific shape. Switch to `browser_type(selector, text)` (which now uses `Input.insertText` by default) or, at a lower level, call CDP `Input.insertText` directly. Always `browser_evaluate` the submit button's `disabled` / `aria-disabled` state before clicking send; if still disabled after those fixes, the framework never saw real input.
2. **Did the selector match anything?** Run `browser_get_rect(selector)` — if it returns `visible=False` or zero rect, the element isn't laid out yet. Wait longer or use a different selector.
3. **Is the element inside a shadow root?** Try `browser_shadow_query(path)`. If your selector is light-DOM only, switch to the screenshot + coordinate strategy.
4. **Did the click hit something on top of the element?** Register a temporary event listener via `browser_evaluate` on the target element, click, then read `window.__hits` to see what actually received the click. If something else is intercepting (overlay, modal, floating button), dismiss it first.
5. **Did `type_text` find the element but fail to insert text?** Some editors (Draft.js on X, ProseMirror on some sites, Monaco) require a small `delay_ms` between keystrokes. Try `delay_ms=20`.
6. **Is this a keyboard shortcut that doesn't fire?** Make sure you're using `browser_press(key, modifiers=[...])` — not raw `browser_evaluate` with `dispatchEvent`. Chrome ignores shortcut key events that lack `code` and `windowsVirtualKeyCode`.
7. **Did the navigation actually complete?** Check the return value of `browser_navigate` — it now returns a real `url` and `title`. An empty title usually means a blank page or a hung load.
8. **Is your screenshot stale?** The highlight overlay stays for 10 s; if the screenshot was taken later, the annotation is gone but the click was real. Check the logs of `browser_click_coordinate` to see the coordinates that were actually sent.
