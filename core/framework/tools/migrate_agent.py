"""Migrate a Python-based agent export to declarative agent.yaml.

Usage::

    uv run python -m framework.tools.migrate_agent exports/lead_enrichment_agent

Reads agent.py, nodes/__init__.py, config.py, and mcp_servers.json from the
given directory and writes an ``agent.yaml`` file that is equivalent.  The
original Python files are left untouched.

After migration, verify with::

    uv run python -c "
    from framework.loader.agent_loader import load_agent_config
    import yaml, pathlib
    data = yaml.safe_load(pathlib.Path('exports/lead_enrichment_agent/agent.yaml').read_text())
    graph, goal = load_agent_config(data)
    print(f'OK: {len(graph.nodes)} nodes, {len(graph.edges)} edges')
    "
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _import_module_from_path(module_name: str, file_path: Path) -> Any:
    """Import a Python file as a module."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _node_to_dict(node: Any) -> dict:
    """Convert a NodeSpec instance to a YAML-friendly dict."""
    d: dict[str, Any] = {"id": node.id}
    if node.name and node.name != node.id:
        d["name"] = node.name
    if node.description:
        d["description"] = node.description
    if node.node_type != "event_loop":
        d["node_type"] = node.node_type
    if node.client_facing:
        d["client_facing"] = True
    if node.max_node_visits != 1:
        d["max_node_visits"] = node.max_node_visits

    if node.input_keys:
        d["input_keys"] = list(node.input_keys)
    if node.output_keys:
        d["output_keys"] = list(node.output_keys)
    if node.nullable_output_keys:
        d["nullable_output_keys"] = list(node.nullable_output_keys)

    # Tools
    tools_list = list(node.tools) if node.tools else []
    if tools_list:
        d["tools"] = {"policy": "explicit", "allowed": tools_list}
    elif node.node_type == "gcu":
        d["tools"] = {"policy": "all"}
    else:
        d["tools"] = {"policy": "none"}

    if node.sub_agents:
        d["sub_agents"] = list(node.sub_agents)
    if node.success_criteria:
        d["success_criteria"] = node.success_criteria
    if getattr(node, "failure_criteria", None):
        d["failure_criteria"] = node.failure_criteria
    if getattr(node, "max_retries", None):
        d["max_retries"] = node.max_retries
    if getattr(node, "skip_judge", False):
        d["skip_judge"] = True
    if getattr(node, "max_iterations", 30) != 30:
        d["max_iterations"] = node.max_iterations

    if node.system_prompt:
        d["system_prompt"] = node.system_prompt

    return d


def _edge_to_dict(edge: Any) -> dict:
    """Convert an EdgeSpec instance to a YAML-friendly dict."""
    d: dict[str, Any] = {
        "from_node": edge.source,
        "to_node": edge.target,
    }
    cond = str(edge.condition.value) if hasattr(edge.condition, "value") else str(edge.condition)
    if cond != "on_success":
        d["condition"] = cond
    if edge.condition_expr:
        d["condition"] = "conditional"
        d["condition_expr"] = edge.condition_expr
    if edge.priority and edge.priority != 1:
        d["priority"] = edge.priority
    if edge.input_mapping:
        d["input_mapping"] = dict(edge.input_mapping)
    return d


def migrate_agent(agent_dir: str | Path) -> dict:
    """Read a Python-based agent export and return the declarative config dict.

    The returned dict can be serialized to YAML or JSON.
    """
    agent_dir = Path(agent_dir).resolve()
    agent_py = agent_dir / "agent.py"
    if not agent_py.exists():
        raise FileNotFoundError(f"No agent.py in {agent_dir}")

    # Make the agent importable as a package (handles relative imports)
    parent = str(agent_dir.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    pkg_name = agent_dir.name
    agent_mod = importlib.import_module(f"{pkg_name}.agent")

    # Extract module-level variables
    goal = getattr(agent_mod, "goal", None)
    nodes = getattr(agent_mod, "nodes", [])
    edges = getattr(agent_mod, "edges", [])
    entry_node = getattr(agent_mod, "entry_node", "")
    terminal_nodes = getattr(agent_mod, "terminal_nodes", [])
    pause_nodes = getattr(agent_mod, "pause_nodes", [])
    conversation_mode = getattr(agent_mod, "conversation_mode", "continuous")
    identity_prompt = getattr(agent_mod, "identity_prompt", "")
    loop_config = getattr(agent_mod, "loop_config", {})

    # Config / metadata
    config_mod = None
    config_py = agent_dir / "config.py"
    if config_py.exists():
        try:
            config_mod = importlib.import_module(f"{pkg_name}.config")
        except ImportError:
            pass
    metadata = getattr(config_mod, "metadata", None)
    default_config = getattr(config_mod, "default_config", None)

    # Agent name
    name = agent_dir.name
    if metadata and hasattr(metadata, "name"):
        name = str(metadata.name).lower().replace(" ", "-")

    # Build config dict
    config: dict[str, Any] = {
        "name": name,
        "version": getattr(metadata, "version", "1.0.0") if metadata else "1.0.0",
    }
    if goal and goal.description:
        config["description"] = goal.description
    if metadata and hasattr(metadata, "intro_message") and metadata.intro_message:
        intro = metadata.intro_message
        if intro and "TODO" not in intro:
            config["metadata"] = {"intro_message": intro}

    # Variables (detect config fields injected into prompts)
    variables: dict[str, str] = {}
    _SKIP_CONFIG = {"model", "temperature", "max_tokens", "api_key", "api_base"}
    if default_config:
        for attr in dir(default_config):
            if attr.startswith("_") or attr in _SKIP_CONFIG:
                continue
            val = getattr(default_config, attr)
            if isinstance(val, str) and val:
                variables[attr] = val
    if variables:
        config["variables"] = variables

    # Goal
    if goal:
        goal_dict: dict[str, Any] = {"description": goal.description}
        if goal.success_criteria:
            goal_dict["success_criteria"] = [sc.description for sc in goal.success_criteria]
        if goal.constraints:
            goal_dict["constraints"] = [c.description for c in goal.constraints]
        config["goal"] = goal_dict

    # Identity / conversation / loop
    if identity_prompt:
        config["identity_prompt"] = identity_prompt
    if conversation_mode and conversation_mode != "continuous":
        config["conversation_mode"] = conversation_mode
    if loop_config:
        config["loop_config"] = dict(loop_config)

    # MCP servers
    mcp_path = agent_dir / "mcp_servers.json"
    if mcp_path.exists():
        with open(mcp_path) as f:
            mcp_data = json.load(f)
        if mcp_data:
            config["mcp_servers"] = [{"name": name} for name in mcp_data]

    # Nodes
    config["nodes"] = [_node_to_dict(n) for n in nodes]

    # Edges
    config["edges"] = [_edge_to_dict(e) for e in edges]

    # Graph structure
    config["entry_node"] = entry_node
    if terminal_nodes:
        config["terminal_nodes"] = terminal_nodes
    if pause_nodes:
        config["pause_nodes"] = pause_nodes

    return config


def write_yaml(config: dict, output_path: Path) -> None:
    """Write config dict to YAML with clean formatting."""
    try:
        import yaml
    except ImportError:
        raise ImportError("PyYAML required: uv pip install pyyaml") from None

    # Custom representer for multiline strings
    def _str_representer(dumper: yaml.Dumper, data: str) -> Any:
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    yaml.add_representer(str, _str_representer)

    with open(output_path, "w") as f:
        yaml.dump(
            config, f,
            default_flow_style=False, sort_keys=False,
            allow_unicode=True, width=120,
        )

    logger.info("Wrote %s", output_path)


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) < 2:
        print("Usage: uv run python -m framework.tools.migrate_agent <agent_dir>")
        sys.exit(1)

    agent_dir = Path(sys.argv[1])
    config = migrate_agent(agent_dir)

    output = agent_dir / "agent.yaml"
    write_yaml(config, output)
    print(f"Wrote {output}")

    n_nodes = len(config["nodes"])
    n_edges = len(config["edges"])
    print(f"\nMigrated {config['name']}: {n_nodes} nodes, {n_edges} edges")
    print("\nVerify with:")
    print(f"  uv run python -m framework.tools.migrate_agent --verify {output}")


if __name__ == "__main__":
    main()
