# GCU Browser Automation Guide

## When to Use GCU Nodes

Use `node_type="gcu"` when:
- The user's workflow requires **navigating real websites** (scraping, form-filling, social media interaction, testing web UIs)
- The task involves **dynamic/JS-rendered pages** that `web_scrape` cannot handle (SPAs, infinite scroll, login-gated content)
- The agent needs to **interact with a website** — clicking, typing, scrolling, selecting, uploading files
- The workflow requires **computer vision** for screen understanding (screenshot capture + vision models)
- Tasks need **deterministic step-by-step browser automation** in headless Chrome

Do NOT use GCU for:
- Static content that `web_scrape` handles fine
- API-accessible data (use the API directly)
- PDF/file processing
- Anything that doesn't require a browser UI

## What GCU Nodes Are

- `node_type="gcu"` — a declarative enhancement over `event_loop`
- Framework auto-prepends browser best-practices system prompt
- Framework auto-includes all browser automation tools from `gcu-tools` MCP server
- Uses **Playwright-based headless Chrome** for reliable, cross-platform automation
- Supports **structured action execution** for deterministic browser workflows
- Includes **screenshot capture** for vision model integration
- Same underlying `EventLoopNode` class — no new imports needed
- `tools=[]` is correct — tools are auto-populated at runtime

## GCU Architecture Pattern  

GCU nodes are **subagents** — invoked via `delegate_to_sub_agent()`, not connected via edges.

- Primary nodes (`event_loop`, client-facing) orchestrate; GCU nodes do browser work
- Parent node declares `sub_agents=["gcu-node-id"]` and calls `delegate_to_sub_agent(agent_id="gcu-node-id", task="...")`
- GCU nodes set `max_node_visits=1` (single execution per delegation), `client_facing=False`
- GCU nodes use `output_keys=["result"]` and return structured JSON via `set_output("result", ...)`

## GCU Node Definition Template

```python
gcu_browser_node = NodeSpec(
    id="gcu-browser-worker",
    name="Browser Worker",
    description="Browser subagent that does X.",
    node_type="gcu",
    client_facing=False,
    max_node_visits=1,
    input_keys=[],
    output_keys=["result"],
    tools=[],  # Auto-populated with all browser tools
    system_prompt="""\
You are a browser agent. Your job: [specific task].

## Workflow
1. browser_start (only if no browser is running yet)
2. browser_open(url=TARGET_URL) — note the returned targetId
3. browser_snapshot to read the page
4. [task-specific steps]
5. set_output("result", JSON)

## Output format
set_output("result", JSON) with:
- [field]: [type and description]
""",
)
```

## Parent Node Template (orchestrating GCU subagents)

```python
orchestrator_node = NodeSpec(
    id="orchestrator",
    ...
    node_type="event_loop",
    sub_agents=["gcu-browser-worker"],
    system_prompt="""\
...
delegate_to_sub_agent(
    agent_id="gcu-browser-worker",
    task="Navigate to [URL]. Do [specific task]. Return JSON with [fields]."
)
...
""",
    tools=[],  # Orchestrator doesn't need browser tools
)
```

## mcp_servers.json with GCU

```json
{
  "hive-tools": { ... },
  "gcu-tools": {
    "transport": "stdio",
    "command": "uv",
    "args": ["run", "python", "-m", "gcu.server", "--stdio"],
    "cwd": "../../tools",
    "description": "GCU tools for browser automation"
  }
}
```

Note: `gcu-tools` is auto-added if any node uses `node_type="gcu"`, but including it explicitly is fine.

## GCU System Prompt Best Practices

Key rules to bake into GCU node prompts:

- Prefer `browser_snapshot` over `browser_get_text("body")` — compact accessibility tree vs 100KB+ raw HTML
- Use `browser_screenshot` for visual context when text extraction isn't sufficient (integrates with vision models)
- Always `browser_wait` after navigation to ensure page loads
- Use large scroll amounts (~2000-5000) for lazy-loaded content
- For spillover files, use `run_command` with grep, not `read_file`
- If auth wall detected, report immediately — don't attempt login
- Keep tool calls per turn ≤10
- Tab isolation: each GCU subagent gets its own isolated browser context automatically
- Follow step-by-step browser plans deterministically using structured actions

## Multiple Concurrent GCU Subagents

When a task can be parallelized across multiple sites or profiles, declare a distinct GCU
node for each and invoke them all in the same LLM turn.  The framework batches all
`delegate_to_sub_agent` calls made in one turn and runs them with `asyncio.gather`, so
they execute concurrently — not sequentially.

**Each GCU subagent automatically gets its own isolated browser context** — no `profile=`
argument is needed in tool calls.  The framework derives a unique profile from the subagent's
node ID and instance counter and injects it via an asyncio `ContextVar` before the subagent
runs.

### Example: three sites in parallel

```python
# Three distinct GCU nodes
gcu_site_a = NodeSpec(id="gcu-site-a", node_type="gcu", ...)
gcu_site_b = NodeSpec(id="gcu-site-b", node_type="gcu", ...)
gcu_site_c = NodeSpec(id="gcu-site-c", node_type="gcu", ...)

orchestrator = NodeSpec(
    id="orchestrator",
    node_type="event_loop",
    sub_agents=["gcu-site-a", "gcu-site-b", "gcu-site-c"],
    system_prompt="""\
Call all three subagents in a single response to run them in parallel:
  delegate_to_sub_agent(agent_id="gcu-site-a", task="Scrape prices from site A")
  delegate_to_sub_agent(agent_id="gcu-site-b", task="Scrape prices from site B")
  delegate_to_sub_agent(agent_id="gcu-site-c", task="Scrape prices from site C")
""",
)
```

**Rules:**
- Use distinct node IDs for each concurrent task — sharing an ID shares the browser context.
- The GCU node prompts do not need to mention `profile=`; isolation is automatic.
- Cleanup is automatic at session end, but GCU nodes can call `browser_stop()` explicitly
  if they want to release resources mid-run.

## GCU Anti-Patterns

- Using `browser_screenshot` to read text (use `browser_snapshot` instead; screenshots are for visual context only)
- Re-navigating after scrolling (resets scroll position)
- Attempting login on auth walls
- Forgetting `target_id` in multi-tab scenarios
- Putting browser tools directly on `event_loop` nodes instead of using GCU subagent pattern
- Making GCU nodes `client_facing=True` (they should be autonomous subagents)
