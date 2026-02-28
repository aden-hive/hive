# Agent File Templates

Complete code templates for each file in a Hive agent package.

## config.py

```python
"""Runtime configuration."""

import json
from dataclasses import dataclass, field
from pathlib import Path


def _load_preferred_model() -> str:
    """Load preferred model from ~/.hive/configuration.json."""
    config_path = Path.home() / ".hive" / "configuration.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
            llm = config.get("llm", {})
            if llm.get("provider") and llm.get("model"):
                return f"{llm['provider']}/{llm['model']}"
        except Exception:
            pass
    return "anthropic/claude-sonnet-4-20250514"


@dataclass
class RuntimeConfig:
    model: str = field(default_factory=_load_preferred_model)
    temperature: float = 0.7
    max_tokens: int = 40000
    api_key: str | None = None
    api_base: str | None = None


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "My Agent Name"
    version: str = "1.0.0"
    description: str = "What this agent does."
    intro_message: str = "Welcome! What would you like me to do?"


metadata = AgentMetadata()
```

## nodes/__init__.py

```python
"""Node definitions for My Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Gather requirements from the user",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,  # Unlimited for forever-alive
    input_keys=["topic"],
    output_keys=["brief"],
    success_criteria="The brief is specific and actionable.",
    system_prompt="""\
You are an intake specialist.

**STEP 1 — Read and respond (text only, NO tool calls):**
1. Read the topic provided
2. If vague, ask 1-2 clarifying questions
3. If clear, confirm your understanding

**STEP 2 — After the user confirms, call set_output:**
- set_output("brief", "Clear description of what to do")
""",
    tools=[],
)

# Node 2: Worker (autonomous)
worker_node = NodeSpec(
    id="worker",
    name="Worker",
    description="Do the main work",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["brief", "feedback"],
    output_keys=["results"],
    nullable_output_keys=["feedback"],  # Only on feedback edge
    success_criteria="Results are complete and accurate.",
    system_prompt="""\
You are a worker agent. Given a brief, do the work.

If feedback is provided, this is a follow-up — address the feedback.

Work in phases:
1. Use tools to gather/process data
2. Analyze results
3. Call set_output for each key in a SEPARATE turn:
   - set_output("results", "structured results")
""",
    tools=["web_search", "web_scrape", "save_data", "load_data", "list_data_files"],
)

# Node 3: Review (client-facing)
review_node = NodeSpec(
    id="review",
    name="Review",
    description="Present results for user approval",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["results", "brief"],
    output_keys=["next_action", "feedback"],
    nullable_output_keys=["feedback"],
    success_criteria="User has reviewed and decided next steps.",
    system_prompt="""\
Present the results to the user.

**STEP 1 — Present (text only, NO tool calls):**
1. Summary of work done
2. Key results
3. Ask: satisfied, or want changes?

**STEP 2 — After user responds, call set_output:**
- set_output("next_action", "new_topic")   — if starting fresh
- set_output("next_action", "revise")      — if changes needed
- set_output("feedback", "what to change") — only if revising
""",
    tools=[],
)

__all__ = ["intake_node", "worker_node", "review_node"]
```

## agent.py

```python
"""Agent graph construction for My Agent."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import intake_node, worker_node, review_node

# Goal definition
goal = Goal(
    id="my-agent-goal",
    name="My Agent Goal",
    description="What this agent achieves.",
    success_criteria=[
        SuccessCriterion(id="sc-1", description="...", metric="...", target="...", weight=0.5),
        SuccessCriterion(id="sc-2", description="...", metric="...", target="...", weight=0.5),
    ],
    constraints=[
        Constraint(id="c-1", description="...", constraint_type="hard", category="quality"),
    ],
)

# Node list
nodes = [intake_node, worker_node, review_node]

# Edge definitions
edges = [
    EdgeSpec(id="intake-to-worker", source="intake", target="worker",
             condition=EdgeCondition.ON_SUCCESS, priority=1),
    EdgeSpec(id="worker-to-review", source="worker", target="review",
             condition=EdgeCondition.ON_SUCCESS, priority=1),
    # Feedback loop
    EdgeSpec(id="review-to-worker", source="review", target="worker",
             condition=EdgeCondition.CONDITIONAL,
             condition_expr="str(next_action).lower() == 'revise'", priority=2),
    # Loop back for new topic
    EdgeSpec(id="review-to-intake", source="review", target="intake",
             condition=EdgeCondition.CONDITIONAL,
             condition_expr="str(next_action).lower() == 'new_topic'", priority=1),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = []  # Forever-alive

# Module-level vars read by AgentRunner.load()
conversation_mode = "continuous"
identity_prompt = "You are a helpful agent."
loop_config = {"max_iterations": 100, "max_tool_calls_per_turn": 20, "max_history_tokens": 32000}


class MyAgent:
    def __init__(self, config=None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.entry_points = entry_points
        self.pause_nodes = pause_nodes
        self.terminal_nodes = terminal_nodes
        self._graph = None
        self._agent_runtime = None
        self._tool_registry = None
        self._storage_path = None

    def _build_graph(self):
        return GraphSpec(
            id="my-agent-graph",
            goal_id=self.goal.id,
            version="1.0.0",
            entry_node=self.entry_node,
            entry_points=self.entry_points,
            terminal_nodes=self.terminal_nodes,
            pause_nodes=self.pause_nodes,
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
            loop_config=loop_config,
            conversation_mode=conversation_mode,
            identity_prompt=identity_prompt,
        )

    def _setup(self):
        self._storage_path = Path.home() / ".hive" / "agents" / "my_agent"
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._tool_registry = ToolRegistry()
        mcp_config = Path(__file__).parent / "mcp_servers.json"
        if mcp_config.exists():
            self._tool_registry.load_mcp_config(mcp_config)
        llm = LiteLLMProvider(model=self.config.model, api_key=self.config.api_key, api_base=self.config.api_base)
        tools = list(self._tool_registry.get_tools().values())
        tool_executor = self._tool_registry.get_executor()
        self._graph = self._build_graph()
        self._agent_runtime = create_agent_runtime(
            graph=self._graph, goal=self.goal, storage_path=self._storage_path,
            entry_points=[EntryPointSpec(id="default", name="Default", entry_node=self.entry_node,
                                         trigger_type="manual", isolation_level="shared")],
            llm=llm, tools=tools, tool_executor=tool_executor,
            checkpoint_config=CheckpointConfig(enabled=True, checkpoint_on_node_complete=True,
                                                checkpoint_max_age_days=7, async_checkpoint=True),
        )

    async def start(self):
        if self._agent_runtime is None:
            self._setup()
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

    async def stop(self):
        if self._agent_runtime and self._agent_runtime.is_running:
            await self._agent_runtime.stop()
        self._agent_runtime = None

    async def trigger_and_wait(self, entry_point="default", input_data=None, timeout=None, session_state=None):
        if self._agent_runtime is None:
            raise RuntimeError("Agent not started. Call start() first.")
        return await self._agent_runtime.trigger_and_wait(
            entry_point_id=entry_point, input_data=input_data or {}, session_state=session_state)

    async def run(self, context, session_state=None):
        await self.start()
        try:
            result = await self.trigger_and_wait("default", context, session_state=session_state)
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self):
        return {
            "name": metadata.name, "version": metadata.version, "description": metadata.description,
            "goal": {"name": self.goal.name, "description": self.goal.description},
            "nodes": [n.id for n in self.nodes], "edges": [e.id for e in self.edges],
            "entry_node": self.entry_node, "entry_points": self.entry_points,
            "terminal_nodes": self.terminal_nodes,
            "client_facing_nodes": [n.id for n in self.nodes if n.client_facing],
        }

    def validate(self):
        errors, warnings = [], []
        node_ids = {n.id for n in self.nodes}
        for e in self.edges:
            if e.source not in node_ids: errors.append(f"Edge {e.id}: source '{e.source}' not found")
            if e.target not in node_ids: errors.append(f"Edge {e.id}: target '{e.target}' not found")
        if self.entry_node not in node_ids: errors.append(f"Entry node '{self.entry_node}' not found")
        for t in self.terminal_nodes:
            if t not in node_ids: errors.append(f"Terminal node '{t}' not found")
        for ep_id, nid in self.entry_points.items():
            if nid not in node_ids: errors.append(f"Entry point '{ep_id}' references unknown node '{nid}'")
        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


default_agent = MyAgent()
```

## agent.py — Async Entry Points Variant

When an agent needs timers, webhooks, or event-driven triggers, add
`async_entry_points` and optionally `runtime_config` as module-level variables.
These are IN ADDITION to the standard variables above.

```python
# Additional imports for async entry points
from framework.graph.edge import GraphSpec, AsyncEntryPointSpec
from framework.runtime.agent_runtime import (
    AgentRuntime, AgentRuntimeConfig, create_agent_runtime,
)

# ... (goal, nodes, edges, entry_node, entry_points, etc. as above) ...

# Async entry points — event-driven triggers
async_entry_points = [
    # Timer with cron: daily at 9am
    AsyncEntryPointSpec(
        id="daily-check",
        name="Daily Check",
        entry_node="process-node",
        trigger_type="timer",
        trigger_config={"cron": "0 9 * * *"},
        isolation_level="shared",
        max_concurrent=1,
    ),
    # Timer with fixed interval: every 20 minutes
    AsyncEntryPointSpec(
        id="scheduled-check",
        name="Scheduled Check",
        entry_node="process-node",
        trigger_type="timer",
        trigger_config={"interval_minutes": 20, "run_immediately": False},
        isolation_level="shared",
        max_concurrent=1,
    ),
    # Event: reacts to webhook events
    AsyncEntryPointSpec(
        id="webhook-event",
        name="Webhook Event Handler",
        entry_node="process-node",
        trigger_type="event",
        trigger_config={"event_types": ["webhook_received"]},
        isolation_level="shared",
        max_concurrent=10,
    ),
]

# Webhook server config (only needed if using webhooks)
runtime_config = AgentRuntimeConfig(
    webhook_host="127.0.0.1",
    webhook_port=8080,
    webhook_routes=[
        {
            "source_id": "my-source",
            "path": "/webhooks/my-source",
            "methods": ["POST"],
        },
    ],
)
```

**Key rules for async entry points:**
- `async_entry_points` is a list of `AsyncEntryPointSpec` (NOT `EntryPointSpec`)
- `runtime_config` is `AgentRuntimeConfig` (NOT `RuntimeConfig` from config.py)
- Valid trigger_types: `timer`, `event`, `webhook`, `manual`, `api`
- Valid isolation_levels: `isolated`, `shared`, `synchronized`
- Timer trigger_config (cron): `{"cron": "0 9 * * *"}` — standard 5-field cron expression
- Timer trigger_config (interval): `{"interval_minutes": float, "run_immediately": bool}`
- Event trigger_config: `{"event_types": ["webhook_received"], "filter_stream": "...", "filter_node": "..."}`
- Use `isolation_level="shared"` for async entry points that need to read
  the primary session's memory (e.g., user-configured rules)
- The `_build_graph()` method passes `async_entry_points` to GraphSpec
- Reference: `exports/gmail_inbox_guardian/agent.py`

## __init__.py

**CRITICAL:** The runner imports the package (`__init__.py`) and reads ALL module-level
variables via `getattr()`. Every variable defined in `agent.py` that the runner needs
MUST be re-exported here. Missing exports cause silent failures (variables default to
`None` or `{}`), leading to "must define goal, nodes, edges" errors or graph validation
failures like "node X is unreachable".

```python
"""My Agent — description."""

from .agent import (
    MyAgent,
    default_agent,
    goal,
    nodes,
    edges,
    entry_node,
    entry_points,
    pause_nodes,
    terminal_nodes,
    conversation_mode,
    identity_prompt,
    loop_config,
)
from .config import default_config, metadata

__all__ = [
    "MyAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "entry_node",
    "entry_points",
    "pause_nodes",
    "terminal_nodes",
    "conversation_mode",
    "identity_prompt",
    "loop_config",
    "default_config",
    "metadata",
]
```

**If the agent uses async entry points**, also import and export:
```python
from .agent import (
    ...,
    async_entry_points,
    runtime_config,  # Only if using webhooks
)

__all__ = [
    ...,
    "async_entry_points",
    "runtime_config",
]
```

## __main__.py

```python
"""CLI entry point for My Agent."""

import asyncio, json, logging, sys
import click
from .agent import default_agent, MyAgent


def setup_logging(verbose=False, debug=False):
    if debug: level, fmt = logging.DEBUG, "%(asctime)s %(name)s: %(message)s"
    elif verbose: level, fmt = logging.INFO, "%(message)s"
    else: level, fmt = logging.WARNING, "%(levelname)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """My Agent — description."""
    pass


@cli.command()
@click.option("--topic", "-t", required=True)
@click.option("--verbose", "-v", is_flag=True)
def run(topic, verbose):
    """Execute the agent."""
    setup_logging(verbose=verbose)
    result = asyncio.run(default_agent.run({"topic": topic}))
    click.echo(json.dumps({"success": result.success, "output": result.output}, indent=2, default=str))
    sys.exit(0 if result.success else 1)


@cli.command()
def tui():
    """Launch TUI dashboard."""
    from pathlib import Path
    from framework.tui.app import AdenTUI
    from framework.llm import LiteLLMProvider
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.agent_runtime import create_agent_runtime
    from framework.runtime.execution_stream import EntryPointSpec

    async def run_tui():
        agent = MyAgent()
        agent._tool_registry = ToolRegistry()
        storage = Path.home() / ".hive" / "agents" / "my_agent"
        storage.mkdir(parents=True, exist_ok=True)
        mcp_cfg = Path(__file__).parent / "mcp_servers.json"
        if mcp_cfg.exists(): agent._tool_registry.load_mcp_config(mcp_cfg)
        llm = LiteLLMProvider(model=agent.config.model, api_key=agent.config.api_key, api_base=agent.config.api_base)
        runtime = create_agent_runtime(
            graph=agent._build_graph(), goal=agent.goal, storage_path=storage,
            entry_points=[EntryPointSpec(id="start", name="Start", entry_node="intake", trigger_type="manual", isolation_level="isolated")],
            llm=llm, tools=list(agent._tool_registry.get_tools().values()), tool_executor=agent._tool_registry.get_executor())
        await runtime.start()
        try:
            app = AdenTUI(runtime)
            await app.run_async()
        finally:
            await runtime.stop()
    asyncio.run(run_tui())


@cli.command()
def info():
    """Show agent info."""
    data = default_agent.info()
    click.echo(f"Agent: {data['name']}\nVersion: {data['version']}\nDescription: {data['description']}")
    click.echo(f"Nodes: {', '.join(data['nodes'])}\nClient-facing: {', '.join(data['client_facing_nodes'])}")


@cli.command()
def validate():
    """Validate agent structure."""
    v = default_agent.validate()
    if v["valid"]: click.echo("Agent is valid")
    else:
        click.echo("Errors:")
        for e in v["errors"]: click.echo(f"  {e}")
    sys.exit(0 if v["valid"] else 1)


if __name__ == "__main__":
    cli()
```

## mcp_servers.json

```json
{
  "hive-tools": {
    "transport": "stdio",
    "command": "uv",
    "args": ["run", "python", "mcp_server.py", "--stdio"],
    "cwd": "../../tools",
    "description": "Hive tools MCP server"
  }
}
```

**CRITICAL FORMAT RULES:**
- NO `"mcpServers"` wrapper (flat dict, not nested)
- `cwd` MUST be `"../../tools"` (relative from `exports/AGENT_NAME/` to `tools/`)
- `command` MUST be `"uv"` with `"args": ["run", "python", ...]` (NOT bare `"python"`)

## tests/conftest.py

```python
"""Test fixtures."""

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parents[3]
for _p in ["exports", "core"]:
    _path = str(_repo_root / _p)
    if _path not in sys.path:
        sys.path.insert(0, _path)

AGENT_PATH = str(Path(__file__).resolve().parents[1])


@pytest.fixture(scope="session")
def agent_module():
    """Import the agent package for structural validation."""
    import importlib
    return importlib.import_module(Path(AGENT_PATH).name)


@pytest.fixture(scope="session")
def runner_loaded():
    """Load the agent through AgentRunner (structural only, no LLM needed)."""
    from framework.runner.runner import AgentRunner
    return AgentRunner.load(AGENT_PATH)
```

## entry_points Format

MUST be: `{"start": "first-node-id"}`
NOT: `{"first-node-id": ["input_keys"]}` (WRONG)
NOT: `{"first-node-id"}` (WRONG — this is a set)
