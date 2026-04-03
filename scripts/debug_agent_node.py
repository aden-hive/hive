#!/usr/bin/env python
"""Run a single exported agent node as a one-node debug graph.

Examples:
    uv run scripts/debug_agent_node.py exports/reddit_star_growth_agent --list-nodes
    uv run scripts/debug_agent_node.py exports/reddit_star_growth_agent --node load_contacted_users --task '{"repo_url":"https://github.com/acme/repo"}'
    uv run scripts/debug_agent_node.py exports/reddit_star_growth_agent/nodes/__init__.py --node load_contacted_users --input-file /tmp/payload.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import GraphSpec
from framework.runtime.agent_runtime import create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec
from framework.runner.runner import AgentRunner


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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one exported agent node as a one-node terminal debug graph."
    )
    parser.add_argument(
        "agent_path",
        help="Export directory or file path (for example exports/my_agent or exports/my_agent/nodes/__init__.py).",
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
        "--mock",
        action="store_true",
        help="Use mock LLM responses instead of a real model.",
    )
    parser.add_argument(
        "--skip-credential-validation",
        action="store_true",
        help="Skip load-time credential validation.",
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
        result = await runtime.trigger_and_wait("default", input_data)

        print(
            json.dumps(
                {
                    "agent_path": str(agent_path),
                    "node_id": node_id,
                    "storage_path": str(storage_path),
                    "success": result.success if result is not None else False,
                    "output": result.output if result is not None else {},
                    "error": result.error if result is not None else "Execution did not complete",
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
