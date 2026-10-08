# Browser Automation Guide

## When to Use Browser Nodes

Use browser nodes (with `tools: {policy: "all"}`) when:
- The task requires interacting with web pages (clicking, typing, navigating)
- No API is available for the target service
- The user is already logged in to the target site

## What Browser Nodes Are

- Regular `event_loop` nodes that drive the browser from the terminal via `terminal_exec`
- Set `tools: {policy: "all"}` (or at least enable `terminal_exec`) so the node can run `hive-browser` commands
- Wire into the graph with edges like any other node
- No special node_type needed

## Available Browser Commands

The browser is driven from the terminal. Run `hive-browser <command> ... --json` via `terminal_exec` — always pass `--json` so the node gets structured output:
- `hive-browser setup` / `hive-browser status` / `hive-browser stop` — bring the browser up, check it, or tear it down.
- `hive-browser open <url>` and `hive-browser navigate <url>` — both lazy-create the browser context, so a single `hive-browser open <url> --json` covers the cold path. To recover from a stale context, run `hive-browser stop --json` then `hive-browser open <url> --json` again. Pass `--browser-profile <label>` to `open` to target a specific Chrome account.
- `hive-browser interact --action A ...` — the unified interaction command. One `--action` selects `left_click` / `right_click` / `middle_click` / `double_click` / `triple_click` / `hover` / `type` / `key` / `scroll` / `drag` / `screenshot` / `zoom` / `wait`. Each action targets a CSS `--selector` or a fractional `--coordinate x,y`.
- `hive-browser select "S" --value V` — dropdown `<select>` option(s)
- `hive-browser page snapshot` — compact accessibility-tree read (structured)
<!-- vision-only -->
- `hive-browser screenshot --intent "I"` — visual capture (saved JPEG, auto-attached to the session; the command returns a `saved_to` path)
<!-- /vision-only -->
- `hive-browser page shadow-query "S"` — locate an element / get its rect (shadow-piercing via `>>>`)
- `hive-browser evaluate --js '<JS>'` — run JavaScript (for large or quote-heavy JS use `--js @file` or `--js -`)
- `hive-browser tab list` / `hive-browser tab activate <T>` / `hive-browser tab close <T>` — tab management and cleanup

## Pick the right reading tool

**`hive-browser page snapshot`** — compact accessibility tree of interactive elements. Fast, cheap, good for static or form-heavy pages where the DOM matches what's visually rendered (documentation, simple dashboards, search results, settings pages).

**`hive-browser screenshot --intent "..."`** — visual capture + metadata (`cssWidth`, `devicePixelRatio`, scale fields). Use this when `hive-browser page snapshot` does not show the thing you need, when refs look stale, or when visual position/layout matters. This often happens on complex SPAs — LinkedIn, Twitter/X, Reddit, Gmail, Notion, Slack, Discord — and on sites using shadow DOM, virtual scrolling, React reconciliation, or dynamic layout.

Neither command is "preferred" universally — they're for different jobs. Start with snapshot for page structure and ordinary controls; use screenshot as the fallback when snapshot can't find or verify the visible target. Activate the `browser-automation` skill for the full decision tree.

## Coordinate rule

Every browser command that takes or returns coordinates operates in **fractions of the viewport (0..1 for both axes)**. Read a target's proportional position off `hive-browser screenshot --intent "..."` ("~35% from the left, ~20% from the top" → `0.35,0.20`) and pass it as `--coordinate 0.35,0.20` on a `hive-browser interact --action left_click` / `hover` / `key` command. `hive-browser page shadow-query "S"` returns `rect.cx` / `rect.cy` as fractions. The command multiplies by `cssWidth` / `cssHeight` internally — no scale awareness required. Fractions are used because every vision model (Claude, GPT-4o, Gemini, local VLMs) resizes/tiles images differently; proportions are invariant. Avoid raw `getBoundingClientRect()` via `hive-browser evaluate` for coord lookup; use `hive-browser page shadow-query` instead.

## System prompt tips for browser nodes

```
1. Start with `hive-browser page snapshot --json` (run in the terminal) or the snapshot
   returned by the latest interaction.
2. If the target is missing, ambiguous, stale, or visibly present but absent from the tree,
   run `hive-browser screenshot --intent "..." --json` to orient and then click by
   fractional coordinates.
3. Before typing into a rich-text editor (X compose, LinkedIn DM, Gmail, Reddit),
   click the input area first with `hive-browser interact --action left_click ... --json`
   so React / Draft.js / Lexical register a native focus event, then
   `hive-browser interact --action type --text "..." --json` — omit `--selector` for
   shadow-DOM inputs to type into the focused element, or pass `--selector` for
   light-DOM inputs.
4. Run `hive-browser interact --action wait --duration 2-3 --json` after navigation for
   SPA hydration.
5. If you hit an auth wall, call set_output with an error and move on.
6. Keep terminal commands per turn <= 10 for reliability.
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
  "system_prompt": "Navigate to the search URL by running `hive-browser navigate <search_url> --wait-until load --json` in the terminal. Wait 3s for SPA hydration. Use the returned snapshot to look for result cards first. If the cards are missing, stale, or visually present but absent from the tree, run `hive-browser screenshot --intent \"orient on result cards\" --json` to orient; paginate through results by scrolling and use screenshots only when the snapshot cannot find or verify the visible cards..."
}
```

Connected via regular edges:
```
search-setup -> scan-profiles -> process-results
```

## Further detail

For rich-text editor quirks (Lexical, Draft.js, ProseMirror), shadow-DOM shortcuts, `beforeunload` dialog neutralization, Trusted Types CSP on LinkedIn, keyboard shortcut dispatch, and per-site selector tables — **activate the `browser-automation` skill**. That skill has the full verified guidance and is refreshed against real production sites.
