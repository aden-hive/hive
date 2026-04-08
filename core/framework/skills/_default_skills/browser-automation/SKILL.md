---
name: hive.browser-automation
description: Best practices for browser automation via gcu-tools MCP server (reading pages, navigation, scrolling, tab management, shadow DOM, coordinates).
metadata:
  author: hive
  type: default-skill
---

## Operational Protocol: Browser Automation

Follow these rules for reliable, efficient browser interaction.

### Reading Pages
- ALWAYS prefer `browser_snapshot` over `browser_get_text("body")` -- it returns a compact ~1-5 KB accessibility tree vs 100+ KB of raw HTML.
- Interaction tools (`browser_click`, `browser_type`, `browser_fill`, `browser_scroll`, etc.) return a page snapshot automatically in their result. Use it to decide your next action -- do NOT call `browser_snapshot` separately after every action. Only call `browser_snapshot` when you need a fresh view without performing an action, or after setting `auto_snapshot=false`.
- Do NOT use `browser_screenshot` to read text -- use `browser_snapshot` for that (compact, searchable, fast).
- DO use `browser_screenshot` when you need visual context: charts, images, canvas elements, layout verification, or when the snapshot doesn't capture what you need.
- Only fall back to `browser_get_text` for extracting specific small elements by CSS selector.

### Navigation & Waiting
- `browser_navigate` and `browser_open` already wait for the page to load. Do NOT call `browser_wait` with no arguments after navigation -- it wastes time. Only use `browser_wait` when you need a *specific element* or *text* to appear (pass `selector` or `text`).
- NEVER re-navigate to the same URL after scrolling -- this resets your scroll position and loses loaded content.

### Scrolling
- Use large scroll amounts ~2000 when loading more content -- sites like twitter and linkedin have lazy loading for paging.
- The scroll result includes a snapshot automatically -- no need to call `browser_snapshot` separately.

### Batching Actions
- You can call multiple tools in a single turn -- they execute in parallel. ALWAYS batch independent actions together. Examples: fill multiple form fields in one turn, navigate + snapshot in one turn, click + scroll if targeting different elements.
- When batching, set `auto_snapshot=false` on all but the last action to avoid redundant snapshots.
- Aim for 3-5 tool calls per turn minimum. One tool call per turn is wasteful.

### Error Recovery
- If a tool fails, retry once with the same approach.
- If it fails a second time, STOP retrying and switch approach.
- If `browser_snapshot` fails, try `browser_get_text` with a specific small selector as fallback.
- If `browser_open` fails or page seems stale, `browser_stop`, then `browser_start`, then retry.

### Tab Management
**Close tabs as soon as you are done with them** -- not only at the end of the task. After reading or extracting data from a tab, close it immediately.

- Finished reading/extracting from a tab? `browser_close(target_id=...)`
- Completed a multi-tab workflow? `browser_close_finished()` to clean up all your tabs
- More than 3 tabs open? Stop and close finished ones before opening more
- Popup appeared that you didn't need? Close it immediately

`browser_tabs` returns an `origin` field for each tab:
- `"agent"` -- you opened it; you own it; close it when done
- `"popup"` -- opened by a link or script; close after extracting what you need
- `"startup"` or `"user"` -- leave these alone unless the task requires it

Never accumulate tabs. Treat every tab you open as a resource you must free.

### Shadow DOM & Overlays
Some sites (LinkedIn messaging, etc.) render content inside closed shadow roots invisible to regular DOM queries.

- `browser_shadow_query("#interop-outlet >>> #msg-overlay >>> p")` -- uses `>>>` to pierce shadow roots. Returns `rect` in CSS pixels and `physicalRect` ready for coordinate tools.
- `browser_get_rect(selector="...", pierce_shadow=true)` -- get physical rect for any element including shadow DOM.

### Coordinate System
There are THREE coordinate spaces. Using the wrong one causes clicks/hovers to land in the wrong place.

| Space | Used by | How to get |
|---|---|---|
| Physical pixels | `browser_click_coordinate` | `browser_coords` `physical_x/y` |
| CSS pixels | `getBoundingClientRect()`, `elementFromPoint` | `browser_coords` `css_x/y` |
| Screenshot pixels | What you see in the image | Raw position in screenshot |

**Converting screenshot to physical**: `browser_coords(x, y)` then use `physical_x/y`.
**Converting CSS to physical**: multiply by `window.devicePixelRatio` (typically 1.6 on HiDPI).
**Never** pass raw `getBoundingClientRect()` values to coordinate tools without multiplying by DPR first.

### Login & Auth Walls
- If you see a "Log in" or "Sign up" prompt, report the auth wall immediately -- do NOT attempt to log in.
- Check for cookie consent banners and dismiss them if they block content.

### Efficiency
- Minimize tool calls -- combine actions where possible.
- When a snapshot result is saved to a spillover file, use `run_command` with grep to extract specific data rather than re-reading the full file.
- Call `set_output` in the same turn as your last browser action when possible -- don't waste a turn.
