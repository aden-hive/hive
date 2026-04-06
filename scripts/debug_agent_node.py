#!/usr/bin/env python
"""Run a single exported agent node as a one-node debug graph.

Examples:
    uv run scripts/debug_agent_node.py exports/reddit_star_growth_agent --list-nodes
    uv run scripts/debug_agent_node.py exports/reddit_star_growth_agent \
        --node load_contacted_users \
        --task '{"repo_url":"https://github.com/acme/repo"}'
    uv run scripts/debug_agent_node.py \
        exports/reddit_star_growth_agent/nodes/__init__.py \
        --node load_contacted_users --input-file /tmp/payload.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from framework.graph.checkpoint_config import CheckpointConfig  # noqa: E402
from framework.graph.edge import GraphSpec  # noqa: E402
from framework.runtime.agent_runtime import create_agent_runtime  # noqa: E402
from framework.runtime.execution_stream import EntryPointSpec  # noqa: E402
from framework.runner.runner import AgentRunner  # noqa: E402


def _configure_event_debug_logging(storage_path: Path) -> None:
    """Redirect optional event debug logs into this run's writable storage.

    Some environments enable HIVE_DEBUG_EVENTS=1 globally, which normally
    writes under ~/.hive/event_logs. For this script we want all artifacts to
    stay inside the chosen debug storage directory so sandboxed runs work.
    """
    raw = os.environ.get("HIVE_DEBUG_EVENTS", "").strip()
    if not raw:
        return

    log_dir = storage_path / "event_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HIVE_DEBUG_EVENTS"] = str(log_dir)

    import framework.runtime.event_bus as event_bus

    event_bus._DEBUG_EVENTS_RAW = str(log_dir)
    event_bus._DEBUG_EVENTS_ENABLED = True
    event_bus._event_log_file = None
    event_bus._event_log_ready = False


def _configure_llm_debug_logging(storage_path: Path) -> None:
    """Keep optional LLM turn logs inside this run's storage directory."""
    llm_log_dir = storage_path / "llm_logs"
    llm_log_dir.mkdir(parents=True, exist_ok=True)

    import framework.runtime.llm_debug_logger as llm_debug_logger

    llm_debug_logger._LLM_DEBUG_DIR = llm_log_dir
    llm_debug_logger._log_file = None
    llm_debug_logger._log_ready = False


def _resolve_agent_path(raw_path: str) -> Path:
    """Resolve an exported agent directory from a file or directory input."""
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (REPO_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()

    if candidate.is_file():
        if candidate.name == "agent.py":
            return candidate.parent
        if candidate.name == "__init__.py" and candidate.parent.name == "nodes":
            return candidate.parent.parent
        if candidate.name == "__init__.py":
            return candidate.parent
        raise ValueError(
            f"Unsupported file path '{candidate}'. Point to an export directory, "
            "agent.py, or nodes/__init__.py."
        )

    if candidate.is_dir():
        if candidate.name == "nodes" and (candidate / "__init__.py").exists():
            return candidate.parent
        if (candidate / "agent.py").exists():
            return candidate

    raise ValueError(
        f"Could not find an exported agent at '{candidate}'. Expected a directory "
        "containing agent.py, agent.py itself, or nodes/__init__.py."
    )


@contextmanager
def _maybe_skip_mcp_registry(skip: bool):
    """Temporarily disable registry-selected MCP server loading for local debug."""
    if not skip:
        yield
        return

    original = AgentRunner._load_registry_mcp_servers

    def _skip_registry(self, agent_path: Path) -> None:
        self._tool_registry.set_mcp_registry_agent_path(None)

    AgentRunner._load_registry_mcp_servers = _skip_registry
    try:
        yield
    finally:
        AgentRunner._load_registry_mcp_servers = original


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one exported agent node as a one-node terminal debug graph."
    )
    parser.add_argument(
        "agent_path",
        help=(
            "Export directory or file path (for example"
            " exports/my_agent or exports/my_agent/nodes/__init__.py)."
        ),
    )
    parser.add_argument(
        "--node",
        help="Node id to run. Defaults to the agent's entry node.",
    )
    parser.add_argument(
        "--list-nodes",
        action="store_true",
        help="List nodes and exit.",
    )
    parser.add_argument(
        "--input-json",
        help="JSON object passed to the node as input_data.",
    )
    parser.add_argument(
        "--input-file",
        help="Path to a JSON file passed to the node as input_data.",
    )
    parser.add_argument(
        "--task",
        help="Convenience shortcut for {'task': <value>} when debugging task-driven nodes.",
    )
    parser.add_argument(
        "--storage-path",
        help="Optional storage directory for the debug run. Defaults to a temp directory.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Seconds to wait for the node run. Use 0 or a negative number to disable.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock LLM responses instead of a real model.",
    )
    parser.add_argument(
        "--skip-credential-validation",
        action="store_true",
        help="Skip load-time credential validation.",
    )
    parser.add_argument(
        "--skip-mcp-registry",
        action="store_true",
        help="Skip registry-selected MCP server loading for offline/local debug runs.",
    )
    return parser.parse_args()


def _load_input(args: argparse.Namespace) -> dict[str, Any]:
    provided = [
        bool(args.input_json),
        bool(args.input_file),
        bool(args.task is not None),
    ]
    if sum(provided) > 1:
        raise ValueError("Use only one of --input-json, --input-file, or --task.")

    if args.input_json:
        payload = json.loads(args.input_json)
    elif args.input_file:
        payload = json.loads(Path(args.input_file).read_text(encoding="utf-8"))
    elif args.task is not None:
        payload = {"task": args.task}
    else:
        payload = {}

    if not isinstance(payload, dict):
        raise ValueError("Input payload must be a JSON object.")
    return payload


def _list_nodes(runner: AgentRunner) -> int:
    print(f"Agent: {runner.agent_path}")
    print(f"Entry node: {runner.graph.entry_node}")
    print("Nodes:")
    for node in runner.graph.nodes:
        markers = []
        if node.id == runner.graph.entry_node:
            markers.append("entry")
        if node.id in runner.graph.terminal_nodes:
            markers.append("terminal")
        marker_text = f" [{' '.join(markers)}]" if markers else ""
        inputs = ", ".join(node.input_keys) if node.input_keys else "-"
        outputs = ", ".join(node.output_keys) if node.output_keys else "-"
        print(
            f"  - {node.id}{marker_text}: type={node.node_type}, "
            f"inputs=[{inputs}], outputs=[{outputs}]"
        )
    return 0


def _build_debug_graph(runner: AgentRunner, node_id: str) -> GraphSpec:
    node = runner.graph.get_node(node_id)
    if node is None:
        available = ", ".join(n.id for n in runner.graph.nodes)
        raise ValueError(f"Node '{node_id}' not found. Available nodes: {available}")

    return GraphSpec(
        id=f"{runner.graph.id}-{node_id}-debug",
        goal_id=runner.goal.id,
        version=runner.graph.version,
        entry_node=node_id,
        entry_points={"start": node_id},
        terminal_nodes=[node_id],
        pause_nodes=[],
        nodes=[node],
        edges=[],
        default_model=runner.graph.default_model,
        max_tokens=runner.graph.max_tokens,
        max_steps=1,
        cleanup_llm_model=runner.graph.cleanup_llm_model,
        loop_config=runner.graph.loop_config,
        conversation_mode=runner.graph.conversation_mode,
        identity_prompt=runner.graph.identity_prompt,
    )


def _disarm_tool_registry_cleanup(runner: AgentRunner | None) -> None:
    """Avoid noisy MCP teardown warnings for this short-lived debug CLI.

    The process exits immediately after the run, so the child MCP processes
    lose their stdio parent anyway. Clearing the tracked clients here keeps
    ToolRegistry.__del__ from attempting an extra disconnect path that can
    log cancel-scope warnings on shutdown.
    """
    if runner is None:
        return

    registry = runner._tool_registry
    registry._mcp_clients.clear()
    registry._mcp_client_servers.clear()
    registry._mcp_managed_clients.clear()


async def _run_debug_node(
    args: argparse.Namespace,
) -> tuple[int, AgentRunner | None, tempfile.TemporaryDirectory[str] | None]:
    agent_path = _resolve_agent_path(args.agent_path)
    with _maybe_skip_mcp_registry(args.skip_mcp_registry):
        runner = AgentRunner.load(
            agent_path,
            mock_mode=args.mock,
            interactive=False,
            skip_credential_validation=args.skip_credential_validation,
        )

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    runtime = None
    try:
        if args.list_nodes:
            return _list_nodes(runner), runner, temp_dir

        node_id = args.node or runner.graph.entry_node
        input_data = _load_input(args)

        runner._setup()

        if args.storage_path:
            storage_path = Path(args.storage_path).resolve()
            storage_path.mkdir(parents=True, exist_ok=True)
        else:
            temp_dir = tempfile.TemporaryDirectory(prefix=f"hive-node-debug-{node_id}-")
            storage_path = Path(temp_dir.name)

        _configure_event_debug_logging(storage_path)
        _configure_llm_debug_logging(storage_path)

        graph = _build_debug_graph(runner, node_id)
        runtime = create_agent_runtime(
            graph=graph,
            goal=runner.goal,
            storage_path=storage_path,
            entry_points=[
                EntryPointSpec(
                    id="default",
                    name="Default",
                    entry_node=node_id,
                    trigger_type="manual",
                    isolation_level="isolated",
                )
            ],
            llm=runner._llm,
            tools=list(runner._tool_registry.get_tools().values()),
            tool_executor=runner._tool_registry.get_executor(),
            checkpoint_config=CheckpointConfig(enabled=False),
            graph_id=graph.id,
        )

        await runtime.start()
        timeout = args.timeout if args.timeout and args.timeout > 0 else None
        result = await runtime.trigger_and_wait("default", input_data, timeout=timeout)

        print(
            json.dumps(
                {
                    "agent_path": str(agent_path),
                    "node_id": node_id,
                    "storage_path": str(storage_path),
                    "success": result.success if result is not None else False,
                    "output": result.output if result is not None else {},
                    "error": (
                        result.error
                        if result is not None
                        else (
                            f"Execution timed out after {timeout:.1f}s"
                            if timeout is not None
                            else "Execution did not complete"
                        )
                    ),
                    "path": result.path if result is not None else [],
                    "steps_executed": result.steps_executed if result is not None else 0,
                },
                indent=2,
                default=str,
            )
        )
        return (0 if result is not None and result.success else 1), runner, temp_dir
    finally:
        if runtime is not None and runtime.is_running:
            await runtime.stop()
        _disarm_tool_registry_cleanup(runner)


def main() -> int:
    args = _parse_args()
    runner: AgentRunner | None = None
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        exit_code, runner, temp_dir = asyncio.run(_run_debug_node(args))
        return exit_code
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if runner is not None:
            runner.cleanup()
        if temp_dir is not None:
            temp_dir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
