# Browser Automation Guide

## When to Use Browser Nodes

Use browser nodes (with `tools: {policy: "all"}`) when:
- The task requires interacting with web pages (clicking, typing, navigating)
- No API is available for the target service
- The user is already logged in to the target site

## What Browser Nodes Are

- Regular `event_loop` nodes with browser tools from gcu-tools MCP server
- Set `tools: {policy: "all"}` to give access to all browser tools
- Wire into the graph with edges like any other node
- No special node_type needed

## Available Browser Tools

All tools are prefixed with `browser_`:
- `browser_start`, `browser_open`, `browser_navigate` — launch/navigate
- `browser_click`, `browser_click_coordinate`, `browser_fill`, `browser_type`, `browser_type_focused` — interact
- `browser_press` (with optional `modifiers=["ctrl"]` etc.) — keyboard shortcuts
- `browser_snapshot` — compact accessibility-tree read (structured)
<!-- vision-only -->
- `browser_screenshot` — visual capture (annotated PNG)
<!-- /vision-only -->
- `browser_shadow_query`, `browser_get_rect` — locate elements (shadow-piercing via `>>>`)
- `browser_scroll`, `browser_wait` — navigation helpers
- `browser_evaluate` — run JavaScript
- `browser_close`, `browser_close_finished` — tab cleanup

## Pick the right reading tool

**`browser_snapshot`** — compact accessibility tree of interactive elements. Fast, cheap, good for static or form-heavy pages where the DOM matches what's visually rendered (documentation, simple dashboards, search results, settings pages).

**`browser_screenshot`** — visual capture + metadata (`cssWidth`, `devicePixelRatio`, scale fields). **Use this on any complex SPA** — LinkedIn, Twitter/X, Reddit, Gmail, Notion, Slack, Discord, any site using shadow DOM, virtual scrolling, React reconciliation, or dynamic layout. On these pages, snapshot refs go stale in seconds, shadow contents aren't in the AX tree, and virtual-scrolled elements disappear from the tree entirely. Screenshot is the **only** reliable way to orient yourself.

Neither tool is "preferred" universally — they're for different jobs. Default to snapshot on text-heavy static pages, screenshot on SPAs and anything shadow-DOM-heavy. Activate the `browser-automation` skill for the full decision tree.

## Coordinate rule

Every browser tool that takes or returns coordinates operates in **screenshot pixels** (the 800 px wide JPEG `browser_screenshot` delivers). Read a pixel off the image, pass it straight to `browser_click_coordinate` / `browser_hover_coordinate` / `browser_press_at`. `browser_get_rect` and `browser_shadow_query` return `rect.cx` / `rect.cy` in the same space. The tools translate to CSS px internally — no scale awareness required. Avoid raw `getBoundingClientRect()` via `browser_evaluate` for coord lookup; use `browser_get_rect` instead.

## System prompt tips for browser nodes

```
1. On LinkedIn / X / Reddit / Gmail / any SPA — use browser_screenshot to orient,
   not browser_snapshot. Shadow DOM and virtual scrolling make snapshots unreliable.
2. For static pages (docs, forms, search results), browser_snapshot is fine.
3. Before typing into a rich-text editor (X compose, LinkedIn DM, Gmail, Reddit),
   click the input area first with browser_click_coordinate so React / Draft.js /
   Lexical register a native focus event, then use browser_type_focused(text=...)
   for shadow-DOM inputs or browser_type(selector, text) for light-DOM inputs.
4. Use browser_wait(seconds=2-3) after navigation for SPA hydration.
5. If you hit an auth wall, call set_output with an error and move on.
6. Keep tool calls per turn <= 10 for reliability.
```

## Example

```json
{
  "id": "scan-profiles",
  "name": "Scan LinkedIn Profiles",
  "description": "Navigate LinkedIn search results and collect profile data",
  "tools": {"policy": "all"},
  "input_keys": ["search_url"],
  "output_keys": ["profiles"],
  "system_prompt": "Navigate to the search URL via browser_navigate(wait_until='load', timeout_ms=20000). Wait 3s for SPA hydration. On LinkedIn, use browser_screenshot to see the page — browser_snapshot misses shadow-DOM and virtual-scrolled content. Paginate through results by scrolling and screenshotting; extract each profile card by reading its visible layout..."
}
```

Connected via regular edges:
```
search-setup -> scan-profiles -> process-results
```

## Further detail

For rich-text editor quirks (Lexical, Draft.js, ProseMirror), shadow-DOM shortcuts, `beforeunload` dialog neutralization, Trusted Types CSP on LinkedIn, keyboard shortcut dispatch, and per-site selector tables — **activate the `browser-automation` skill**. That skill has the full verified guidance and is refreshed against real production sites.
