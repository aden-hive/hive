"""Browser automation best-practices prompt.

This module provides ``GCU_BROWSER_SYSTEM_PROMPT`` — a canonical set of
browser automation guidelines that can be included in any node's system
prompt that uses browser tools from the gcu-tools MCP server.

Browser tools are registered via the global MCP registry (gcu-tools).
Nodes that need browser access declare ``tools: {policy: "all"}`` in their
agent.json config.

Note: the canonical source of truth for browser automation guidance is
the ``browser-automation`` default skill at
``core/framework/skills/_default_skills/browser-automation/SKILL.md``.
Activate that skill for the full decision tree. This module holds a
compact subset suitable for direct inlining into a node's system prompt
when a skill activation is not desired.
"""

GCU_BROWSER_SYSTEM_PROMPT = """\
# Browser Automation Best Practices

Follow these rules for reliable, efficient browser interaction.

## Pick the right reading tool

- **`browser_snapshot`** — compact accessibility tree. Fast, cheap, good
  for static / text-heavy pages where the DOM matches what's visually
  rendered (docs, forms, search results, settings pages).
- **`browser_screenshot`** — visual capture + scale metadata. Use on any
  complex SPA (LinkedIn, X / Twitter, Reddit, Gmail, Notion, Slack,
  Discord) and on any site using shadow DOM or virtual scrolling. On
  those pages, snapshot refs go stale in seconds, shadow contents
  aren't in the AX tree, and virtual-scrolled elements disappear from
  the tree entirely — screenshots are the only reliable way to orient.

Neither tool is "preferred" universally — they're for different jobs.
Default to snapshot on static pages, screenshot on SPAs and
shadow-heavy sites. Interaction tools (click/type/fill/scroll) return
a snapshot automatically, so don't call `browser_snapshot` separately
after an interaction unless you need a fresh view.

Only fall back to `browser_get_text` for extracting small elements by
CSS selector.

## Coordinates

`browser_screenshot` delivers the image at the CSS viewport's own
dimensions, so a pixel you read off the screenshot is the same number
you pass to `browser_click_coordinate` / `browser_hover_coordinate` /
`browser_press_at`. `browser_get_rect` and `browser_shadow_query` also
return CSS px — feed `rect.css.cx` / `rect.css.cy` straight through.
No scale factors to remember.

Never multiply `getBoundingClientRect()` by `devicePixelRatio` — it's
already in the right unit.

## Rich-text editors (X, LinkedIn DMs, Gmail, Reddit, Slack, Discord)

Click the input area first with `browser_click_coordinate` or
`browser_click(selector)` BEFORE typing. React / Draft.js / Lexical /
ProseMirror only register input as "real" after a native pointer-
sourced focus event; JS `.focus()` is not enough. Without a real click
first, the editor stays empty and the send button stays disabled.

`browser_type` now does this automatically — it clicks the element,
then inserts text via CDP `Input.insertText` (IME-commit style), which
rich editors accept cleanly. Before clicking send, verify the submit
button's `disabled` / `aria-disabled` state via `browser_evaluate`.

## Shadow DOM

Sites like LinkedIn messaging (`#interop-outlet`), Reddit (faceplate
Web Components), and some X elements live inside shadow roots.
`document.querySelector` and `wait_for_selector` do **not** see into
shadow roots. But `browser_click_coordinate` **does** — CDP hit
testing walks shadow roots natively, so coordinate-based operations
reach shadow elements transparently.

**Shadow-heavy site workflow:**
1. `browser_screenshot()` → visual image
2. Identify target visually → pixel `(x, y)` read straight off the image
3. `browser_click_coordinate(x, y)` → lands via native hit test; inputs
   get focused regardless of shadow depth
4. Type via `browser_type_focused` (no selector needed — types into the
   already-focused element), or `browser_type` if you have a selector

For selector-style access when you know the shadow path:
`browser_shadow_query("#interop-outlet >>> #msg-overlay >>> p")` —
returns a CSS-px rect you can feed directly to click tools.

## Navigation & waiting

- `browser_navigate(wait_until="load")` returns when the page fires
  load. On SPAs (LinkedIn especially — 4–5 seconds), add a 2–3 s sleep
  after to let React/Vue hydrate before querying for chrome elements.
- Never re-navigate to the same URL after scrolling — resets scroll.
- Use `timeout_ms=20000` for heavy SPAs.
- `wait_for_selector` / `wait_for_text` resolve in milliseconds when
  the element is already in the DOM — no need to sleep if you can
  express the wait condition.

## Keyboard shortcuts

`browser_press("a", modifiers=["ctrl"])` for Ctrl+A. Accepted
modifiers: `"alt"`, `"ctrl"`/`"control"`, `"meta"`/`"cmd"`,
`"shift"`. The tool dispatches the modifier key first, then the main
key with `code` and `windowsVirtualKeyCode` populated (Chrome's
shortcut dispatcher requires both), then releases in reverse order.

## Scrolling

- Use large amounts (~2000 px) for lazy-loaded sites (X, LinkedIn).
- Scroll result includes a snapshot — don't call `browser_snapshot`
  separately.

## Batching

- Multiple tool calls per turn execute in parallel. Batch independent
  actions together: fill multiple fields, navigate + snapshot,
  different-target click + scroll.
- Set `auto_snapshot=false` on all but the last when batching.
- Aim for 3–5 tool calls per turn minimum.

## Tab management

Close tabs as soon as you're done with them — not only at the end of
the task. `browser_close(target_id=...)` for one, `browser_close_finished()`
for a full cleanup. Never accumulate more than 3 open tabs.
`browser_tabs` reports an `origin` field: `"agent"` (you own it, close
when done), `"popup"` (close after extracting), `"startup"`/`"user"`
(leave alone).

## Login & auth walls

Report the auth wall and stop — do NOT attempt to log in. Dismiss
cookie consent banners if they block content.

## Error recovery

- Retry once on failure, then switch approach.
- If `browser_snapshot` fails, try `browser_get_text` with a narrow
  selector as fallback.
- If `browser_open` fails or the page seems stale, `browser_stop` →
  `browser_start` → retry.

## `browser_evaluate`

Use for reading state inside a shadow root that standard tools don't
handle, for one-shot site-specific actions, or to measure layout the
tools don't expose. Do NOT use it on a strict-CSP site (LinkedIn,
some X surfaces) with `innerHTML` — Trusted Types silently drops the
assignment. Always use `createElement` + `appendChild` + `setAttribute`
for DOM injection on those sites. `style.cssText`, `textContent`, and
`.value` assignments are fine.
"""
