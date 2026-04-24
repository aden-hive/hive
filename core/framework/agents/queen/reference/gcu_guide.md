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

**`browser_screenshot`** — visual capture + metadata (`cssWidth`, `devicePixelRatio`, scale fields). Use this when `browser_snapshot` does not show the thing you need, when refs look stale, or when visual position/layout matters. This often happens on complex SPAs — LinkedIn, Twitter/X, Reddit, Gmail, Notion, Slack, Discord — and on sites using shadow DOM, virtual scrolling, React reconciliation, or dynamic layout.

Neither tool is "preferred" universally — they're for different jobs. Start with snapshot for page structure and ordinary controls; use screenshot as the fallback when snapshot can't find or verify the visible target. Activate the `browser-automation` skill for the full decision tree.

## Coordinate rule

Every browser tool that takes or returns coordinates operates in **fractions of the viewport (0..1 for both axes)**. Read a target's proportional position off `browser_screenshot` ("~35% from the left, ~20% from the top" → `(0.35, 0.20)`) and pass that to `browser_click_coordinate` / `browser_hover_coordinate` / `browser_press_at`. `browser_get_rect` and `browser_shadow_query` return `rect.cx` / `rect.cy` as fractions. The tools multiply by `cssWidth` / `cssHeight` internally — no scale awareness required. Fractions are used because every vision model (Claude, GPT-4o, Gemini, local VLMs) resizes/tiles images differently; proportions are invariant. Avoid raw `getBoundingClientRect()` via `browser_evaluate` for coord lookup; use `browser_get_rect` instead.

## System prompt tips for browser nodes

```
1. Start with browser_snapshot or the snapshot returned by the latest interaction.
2. If the target is missing, ambiguous, stale, or visibly present but absent from the tree,
   use browser_screenshot to orient and then click by fractional coordinates.
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
  "system_prompt": "Navigate to the search URL via browser_navigate(wait_until='load', timeout_ms=20000). Wait 3s for SPA hydration. Use the returned snapshot to look for result cards first. If the cards are missing, stale, or visually present but absent from the tree, use browser_screenshot to orient; paginate through results by scrolling and use screenshots only when the snapshot cannot find or verify the visible cards..."
}
```

Connected via regular edges:
```
search-setup -> scan-profiles -> process-results
```

## Further detail

For rich-text editor quirks (Lexical, Draft.js, ProseMirror), shadow-DOM shortcuts, `beforeunload` dialog neutralization, Trusted Types CSP on LinkedIn, keyboard shortcut dispatch, and per-site selector tables — **activate the `browser-automation` skill**. That skill has the full verified guidance and is refreshed against real production sites.
