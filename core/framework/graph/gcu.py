"""GCU (browser automation) node type constants.

A ``gcu`` node is an ``event_loop`` node with two automatic enhancements:
1. A canonical browser best-practices system prompt is prepended.
2. All tools from the GCU MCP server are auto-included.

No new ``NodeProtocol`` subclass — the ``gcu`` type is purely a declarative
signal processed by the runner and executor at setup time.
"""

# ---------------------------------------------------------------------------
# MCP server identity
# ---------------------------------------------------------------------------

GCU_SERVER_NAME = "gcu-tools"
"""Name used to identify the GCU MCP server in ``mcp_servers.json``."""

GCU_MCP_SERVER_CONFIG: dict = {
    "name": GCU_SERVER_NAME,
    "transport": "stdio",
    "command": "uv",
    "args": ["run", "python", "-m", "gcu.server", "--stdio"],
    "cwd": "../../tools",
    "description": "GCU tools for browser automation",
}
"""Default stdio config for the GCU MCP server (relative to exports/<agent>/)."""

# ---------------------------------------------------------------------------
# Browser best-practices system prompt
# ---------------------------------------------------------------------------

GCU_BROWSER_SYSTEM_PROMPT = """\
# Browser Automation Best Practices

Follow these rules for reliable, efficient browser interaction.

## Reading Pages
- ALWAYS prefer `browser_snapshot` over `browser_get_text("body")`
  — it returns a compact ~1-5 KB accessibility tree vs 100+ KB of raw HTML.
- Use `browser_snapshot_aria` when you need full ARIA properties
  for detailed element inspection.
- Do NOT use `browser_screenshot` for reading text content
  — it produces huge base64 images with no searchable text.
- Only fall back to `browser_get_text` for extracting specific
  small elements by CSS selector.

## Navigation & Waiting
- Always call `browser_wait` after navigation actions
  (`browser_open`, `browser_navigate`, `browser_click` on links)
  to let the page load.
- NEVER re-navigate to the same URL after scrolling
  — this resets your scroll position and loses loaded content.

## Scrolling
- Use large scroll amounts ~2000 when loading more content
  — sites like twitter and linkedin have lazy loading for paging.
- After scrolling, take a new `browser_snapshot` to see updated content.

## Error Recovery
- If a tool fails, retry once with the same approach.
- If it fails a second time, STOP retrying and switch approach.
- If `browser_snapshot` fails → try `browser_get_text` with a
  specific small selector as fallback.
- If `browser_open` fails or page seems stale → `browser_stop`,
  then `browser_start`, then retry.

## Tab Management
- Use `browser_tabs` to list open tabs when managing multiple pages.
- Pass `target_id` to tools when operating on a specific tab.
- Open background tabs with `browser_open(url=..., background=true)`
  to avoid losing your current context.
- Close tabs you no longer need with `browser_close` to free resources.

## Login & Auth Walls
- If you see a "Log in" or "Sign up" prompt instead of expected
  content, report the auth wall immediately — do NOT attempt to log in.
- Check for cookie consent banners and dismiss them if they block content.

## Efficiency
- Minimize tool calls — combine actions where possible.
- When a snapshot result is saved to a spillover file, use
  `run_command` with grep to extract specific data rather than
  re-reading the full file.
- Call `set_output` in the same turn as your last browser action
  when possible — don't waste a turn.
"""
