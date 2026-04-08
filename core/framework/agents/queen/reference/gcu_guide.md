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
- `browser_start`, `browser_open` -- launch/navigate
- `browser_click`, `browser_fill`, `browser_type` -- interact
- `browser_snapshot` -- read page content (preferred over screenshot)
- `browser_screenshot` -- visual capture
- `browser_scroll`, `browser_wait` -- navigation helpers
- `browser_evaluate` -- run JavaScript

## System Prompt Tips for Browser Nodes

```
1. Use browser_snapshot() to read page content (NOT browser_get_text)
2. Use browser_wait(seconds=2-3) after navigation for page load
3. If you hit an auth wall, call set_output with an error and move on
4. Keep tool calls per turn <= 10 for reliability
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
  "system_prompt": "Navigate to the search URL, paginate through results..."
}
```

Connected via regular edges:
```
search-setup -> scan-profiles -> process-results
```
