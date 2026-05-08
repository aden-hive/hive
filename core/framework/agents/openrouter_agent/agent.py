"""OpenRouter agent — free open-source model chat with web search and memory.

Follows the exact same structure as credential_tester/agent.py.

Module-level variables read by AgentRunner.load() / TUI / hive run:
    goal, nodes, edges
    entry_node, entry_points, terminal_nodes, pause_nodes
    conversation_mode, identity_prompt, loop_config
    default_skills, skip_credential_validation
    requires_account_selection, configure_for_account, list_connected_accounts
    metadata, default_config

Programmatic class used by __main__.py:
    OpenRouterAgent — select_model(), start(), stop(), run()

Features implemented:
  Feature 1: Session memory (session_memory.py, read fresh at runtime)
  Feature 2: Model picker (configure_for_account / list_connected_accounts)
  Feature 3: Web search + file tools (NodeSpec.tools in nodes.py)
  Feature 4: Default skills (hive.note-taking, hive.task-decomposition)
  Feature 5: Fallback chain (inside OpenRouterProvider in openrouter.py)

Key fix: nodes = [build_chat_node(memory=False)] at module level.
Memory is NOT read at import time. It is read fresh inside _build_graph()
at runtime when memory=True is passed. This matches the pattern used by
credential_tester where the module-level NodeSpec uses a static prompt
and configure_for_account() replaces it at runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from framework.config import get_max_context_tokens
from framework.graph import Goal, SuccessCriterion
from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.llm.openrouter import FREE_MODELS, OpenRouterProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config
from .nodes import build_chat_node
from .session_memory import consolidate_memory, seed_if_missing

if TYPE_CHECKING:
    from framework.runner import AgentRunner

# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------

goal = Goal(
    id="openrouter-assistant",
    name="OpenRouter Assistant",
    description=(
        "Answer user questions and complete tasks using a free open-source model via OpenRouter."
    ),
    success_criteria=[
        SuccessCriterion(
            id="response-generated",
            description="At least one response was produced",
            metric="custom",
            target="any",
            weight=1.0,
        ),
    ],
    constraints=[],
)

# ---------------------------------------------------------------------------
# Feature 2: Model picker helpers
# Mirrors list_connected_accounts / configure_for_account in credential_tester
# ---------------------------------------------------------------------------


def list_connected_accounts() -> list[dict]:
    """Return free model list as 'accounts' for the TUI picker.

    AgentRunner calls this when requires_account_selection=True.
    Each dict must have 'provider' and 'alias' — TUI shows provider/alias.
    We store the full model_id in the dict so configure_for_account can use it.
    """
    return [
        {
            "provider": "openrouter",
            "alias": alias,
            "model_id": model_id,
            "identity": {"model": model_id},
            "source": "openrouter",
        }
        for alias, model_id in FREE_MODELS.items()
    ]


def configure_for_account(runner: AgentRunner, account: dict) -> None:
    """Scope the chat node to the selected model.

    Called by AgentRunner after the user picks a model in the TUI picker.
    Replaces (not appends to) the system prompt so repeated selections
    don't accumulate duplicate model lines.

    Mirrors _configure_aden_node in credential_tester/agent.py exactly:
    mutates node.system_prompt and node.tools in place, then updates
    runner.intro_message.
    """
    model_id = account.get("model_id") or account.get("alias", default_config.model)
    alias = account.get("alias", model_id)

    # Build a fresh node spec with memory=True so the memory file is
    # read at selection time (after the session is already starting).
    fresh_node = build_chat_node(memory=True)

    for node in runner.graph.nodes:
        if node.id == "chat":
            # REPLACE — not append — so re-selection doesn't duplicate
            node.system_prompt = (
                fresh_node.system_prompt
                + f"\n\n# Selected model\n\nYou are running as: {model_id}\n"
            )
            node.tools = fresh_node.tools
            break

    runner.intro_message = (
        f"Running on {alias} ({model_id}). "
        "Ask me anything — I can answer questions, search the web, and read files."
    )


# ---------------------------------------------------------------------------
# Module-level variables (read by AgentRunner.load)
# ---------------------------------------------------------------------------

# Feature 4: Enable default skills
default_skills = {
    "hive.note-taking": {"enabled": True},
    "hive.task-decomposition": {"enabled": True},
    "hive.quality-monitor": {"enabled": False},  # off — adds latency on free models
}

skip_credential_validation = True
# No Hive credential needed — only OPENROUTER_API_KEY is required.

# Feature 2: Show model picker in TUI before the session starts.
requires_account_selection = True

# NOTE: memory=False here — module is imported before the session starts.
# Memory is injected fresh at runtime inside _build_graph() and
# configure_for_account() which both call build_chat_node(memory=True).
nodes = [build_chat_node(memory=False)]
edges = []

entry_node = "chat"
entry_points = {"start": "chat"}
pause_nodes = []
terminal_nodes = ["chat"]

conversation_mode = "continuous"
identity_prompt = (
    "You are a helpful AI assistant powered by a free open-source model via OpenRouter. "
    "You can search the web, read files, and remember context from past sessions."
)
loop_config = {
    "max_iterations": 999_999,
    "max_tool_calls_per_turn": 10,
}

# ---------------------------------------------------------------------------
# Programmatic agent class (used by __main__.py and tests)
# ---------------------------------------------------------------------------


class OpenRouterAgent:
    """Programmatic interface to the OpenRouter agent.

    Usage:
        agent = OpenRouterAgent()
        agent.select_model("openai/gpt-oss-120b:free")  # optional
        await agent.start()
        result = await agent.run(user_message="Hello!")
        await agent.stop()
    """

    def __init__(self, config=None):
        self.config = config or default_config
        self._model: str = self.config.model
        self._agent_runtime: AgentRuntime | None = None
        self._tool_registry: ToolRegistry | None = None
        self._storage_path: Path | None = None
        self._conversation_history: list[dict] = []

    def select_model(self, model: str) -> None:
        """Set the model before calling start().

        Accepts either a full OpenRouter model ID or a short alias
        from FREE_MODELS (e.g. 'qwen3-14b').
        """
        from framework.llm.openrouter import _resolve_model

        self._model = _resolve_model(model)

    def list_models(self) -> dict[str, str]:
        """Return alias -> full model ID mapping."""
        return dict(FREE_MODELS)

    def _build_graph(self) -> GraphSpec:
        """Build graph with memory=True — reads ~/.hive at runtime, not import."""
        chat_node = build_chat_node(memory=True)

        return GraphSpec(
            id="openrouter-agent-graph",
            goal_id=goal.id,
            version="1.0.0",
            entry_node="chat",
            entry_points={"start": "chat"},
            terminal_nodes=["chat"],
            pause_nodes=[],
            nodes=[chat_node],
            edges=[],
            default_model=self._model,
            max_tokens=self.config.max_tokens,
            loop_config={
                "max_iterations": 999_999,
                "max_tool_calls_per_turn": 10,
                "max_context_tokens": get_max_context_tokens(),
            },
            conversation_mode="continuous",
            identity_prompt=identity_prompt,
        )

    def _setup(self) -> None:
        seed_if_missing()

        self._storage_path = Path.home() / ".hive" / "agents" / "openrouter_agent"
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            self._tool_registry.load_mcp_config(mcp_config_path)

        # Feature 5: fallback chain is inside OpenRouterProvider
        llm = OpenRouterProvider(
            model=self._model,
            api_key=self.config.api_key,
            use_fallback=True,
        )

        tool_executor = self._tool_registry.get_executor()
        tools = list(self._tool_registry.get_tools().values())

        graph = self._build_graph()

        # Exact same create_agent_runtime call pattern as credential_tester
        self._agent_runtime = create_agent_runtime(
            graph=graph,
            goal=goal,
            storage_path=self._storage_path,
            entry_points=[
                EntryPointSpec(
                    id="start",
                    name="Chat",
                    entry_node="chat",
                    trigger_type="manual",
                    isolation_level="shared",
                ),
            ],
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            checkpoint_config=CheckpointConfig(enabled=True),
            graph_id="openrouter_agent",
        )

    async def start(self) -> None:
        """Set up and start the agent runtime."""
        if self._agent_runtime is None:
            self._setup()
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

    async def stop(self) -> None:
        """Stop the agent runtime.

        Feature 1: Consolidates session memory on stop so the next
        session can read what was discussed in this one.
        """
        if self._agent_runtime and self._agent_runtime.is_running:
            if self._conversation_history:
                llm = OpenRouterProvider(
                    model=self._model,
                    api_key=self.config.api_key,
                )
                await consolidate_memory(self._conversation_history, llm)

            await self._agent_runtime.stop()

        self._agent_runtime = None

    async def run(self, user_message: str = "") -> ExecutionResult:
        """Trigger one turn and wait for the result.

        Tracks conversation history for memory consolidation on stop().
        """
        await self.start()

        result = await self._agent_runtime.trigger_and_wait(
            entry_point_id="start",
            input_data={"user_message": user_message} if user_message else {},
        )

        if user_message:
            self._conversation_history.append({"role": "user", "content": user_message})
        if result and result.success and result.output.get("response"):
            self._conversation_history.append(
                {"role": "assistant", "content": result.output["response"]}
            )

        return result or ExecutionResult(success=False, error="Execution timeout")
