"""
Graph export and documentation MCP tools.

Handles exporting validated agent graphs to disk with documentation.
"""

import json
from datetime import datetime
from pathlib import Path

from framework.mcp.session import BuildSession, get_session


def _generate_readme(session: BuildSession, export_data: dict, all_tools: set) -> str:
    """Generate README.md content for the exported agent."""
    goal = session.goal
    nodes = session.nodes
    edges = session.edges

    # Build execution flow diagram
    flow_parts = []
    current = export_data["graph"]["entry_node"]
    visited = set()

    while current and current not in visited:
        visited.add(current)
        flow_parts.append(current)
        # Find next node
        next_node = None
        for edge in edges:
            if edge.source == current:
                next_node = edge.target
                break
        # Check router routes
        for node in nodes:
            if node.id == current and node.routes:
                route_targets = list(node.routes.values())
                if route_targets:
                    flow_parts.append("{" + " | ".join(route_targets) + "}")
                    next_node = None
                break
        current = next_node

    flow_diagram = " → ".join(flow_parts)

    # Build nodes section
    nodes_section = []
    for i, node in enumerate(nodes, 1):
        node_info = [f"{i}. **{node.id}** ({node.node_type})"]
        node_info.append(f"   - {node.description}")
        if node.input_keys:
            node_info.append(f"   - Reads: `{', '.join(node.input_keys)}`")
        if node.output_keys:
            node_info.append(f"   - Writes: `{', '.join(node.output_keys)}`")
        if node.tools:
            node_info.append(f"   - Tools: `{', '.join(node.tools)}`")
        if node.routes:
            routes_str = ", ".join([f"{k}→{v}" for k, v in node.routes.items()])
            node_info.append(f"   - Routes: {routes_str}")
        nodes_section.append("\n".join(node_info))

    # Build success criteria section
    criteria_section = []
    for criterion in goal.success_criteria:
        crit_dict = (
            criterion.model_dump() if hasattr(criterion, "model_dump") else criterion.__dict__
        )
        criteria_section.append(
            f"**{crit_dict.get('description', 'N/A')}** (weight {crit_dict.get('weight', 1.0)})\n"
            f"- Metric: {crit_dict.get('metric', 'N/A')}\n"
            f"- Target: {crit_dict.get('target', 'N/A')}"
        )

    # Build constraints section
    constraints_section = []
    for constraint in goal.constraints:
        const_dict = (
            constraint.model_dump() if hasattr(constraint, "model_dump") else constraint.__dict__
        )
        desc = const_dict.get("description", "N/A")
        ctype = const_dict.get("constraint_type", "hard")
        cat = const_dict.get("category", "N/A")
        constraints_section.append(f"**{desc}** ({ctype})\n- Category: {cat}")

    readme = f"""# {goal.name}

**Version**: 1.0.0
**Type**: Multi-node agent
**Created**: {datetime.now().strftime("%Y-%m-%d")}

## Overview

{goal.description}

## Architecture

### Execution Flow

```
{flow_diagram}
```

### Nodes ({len(nodes)} total)

{chr(10).join(nodes_section)}

### Edges ({len(edges)} total)

"""

    for edge in edges:
        cond = edge.condition.value if hasattr(edge.condition, "value") else edge.condition
        readme += f"- `{edge.source}` → `{edge.target}` (condition: {cond})\n"

    readme += f"""

## Goal Criteria

### Success Criteria

{chr(10).join(criteria_section)}

### Constraints

{chr(10).join(constraints_section) if constraints_section else "None defined"}

## Required Tools

{chr(10).join(f"- `{tool}`" for tool in sorted(all_tools)) if all_tools else "No tools required"}

{"## MCP Tool Sources" if session.mcp_servers else ""}

{
        chr(10).join(
            f'''### {s["name"]} ({s["transport"]})
{s.get("description", "")}

**Configuration:**
'''
            + (
                f'''- Command: `{s.get("command")}`
- Args: `{s.get("args")}`
- Working Directory: `{s.get("cwd")}`'''
                if s["transport"] == "stdio"
                else f'''- URL: `{s.get("url")}`'''
            )
            for s in session.mcp_servers
        )
        if session.mcp_servers
        else ""
    }

{
        "Tools from these MCP servers are automatically loaded when the agent runs."
        if session.mcp_servers
        else ""
    }

## Usage

### Basic Usage

```python
from framework.runner import AgentRunner

# Load the agent
runner = AgentRunner.load("exports/{session.name}")

# Run with input
result = await runner.run({{"input_key": "value"}})

# Access results
print(result.output)
print(result.status)
```

### Input Schema

The agent's entry node `{export_data["graph"]["entry_node"]}` requires:
"""

    entry_node_obj = next((n for n in nodes if n.id == export_data["graph"]["entry_node"]), None)
    if entry_node_obj:
        for input_key in entry_node_obj.input_keys:
            readme += f"- `{input_key}` (required)\n"

    readme += f"""

### Output Schema

Terminal nodes: {", ".join(f"`{t}`" for t in export_data["graph"]["terminal_nodes"])}

## Version History

- **1.0.0** ({datetime.now().strftime("%Y-%m-%d")}): Initial release
  - {len(nodes)} nodes, {len(edges)} edges
  - Goal: {goal.name}
"""

    return readme


def register(mcp):
    """Register graph export tools on the MCP server."""

    @mcp.tool()
    def export_graph() -> str:
        """
        Export the validated graph as a GraphSpec for GraphExecutor.

        Exports the complete agent definition including nodes, edges, goal,
        and evaluation rules. The GraphExecutor runs the graph with dynamic
        edge traversal and routing logic.

        AUTOMATICALLY WRITES FILES TO DISK:
        - exports/{agent-name}/agent.json - Full agent specification
        - exports/{agent-name}/README.md - Documentation
        """
        from framework.mcp.handlers.evaluation_handler import get_evaluation_rules
        from framework.mcp.validation.validators import validate_graph

        session = get_session()

        # Validate first
        validation = json.loads(validate_graph())
        if not validation["valid"]:
            return json.dumps({"success": False, "errors": validation["errors"]})

        entry_node = validation["entry_node"]
        terminal_nodes = validation["terminal_nodes"]

        # Extract pause/resume configuration from validation
        pause_nodes = validation.get("pause_nodes", [])
        resume_entry_points = validation.get("resume_entry_points", [])

        # Build entry_points dict for pause/resume architecture
        entry_points = {}
        if entry_node:
            entry_points["start"] = entry_node

        # Add resume entry points with {pause_node}_resume naming convention
        if pause_nodes and resume_entry_points:
            pause_to_resume = {}
            for pause_node_id in pause_nodes:
                pause_node = next((n for n in session.nodes if n.id == pause_node_id), None)
                if not pause_node:
                    continue

                for resume_node_id in resume_entry_points:
                    resume_node = next((n for n in session.nodes if n.id == resume_node_id), None)
                    if not resume_node:
                        continue

                    shared_keys = set(pause_node.output_keys) & set(resume_node.input_keys)
                    if shared_keys:
                        pause_to_resume[pause_node_id] = resume_node_id
                        break

            unmatched_pause = [p for p in pause_nodes if p not in pause_to_resume]
            unmatched_resume = [r for r in resume_entry_points if r not in pause_to_resume.values()]
            for pause_id, resume_id in zip(unmatched_pause, unmatched_resume, strict=False):
                pause_to_resume[pause_id] = resume_id

            for pause_id, resume_id in pause_to_resume.items():
                entry_points[f"{pause_id}_resume"] = resume_id

        # Build edges list
        edges_list = [
            {
                "id": edge.id,
                "source": edge.source,
                "target": edge.target,
                "condition": edge.condition.value,
                "condition_expr": edge.condition_expr,
                "priority": edge.priority,
                "input_mapping": edge.input_mapping,
            }
            for edge in session.edges
        ]

        # AUTO-GENERATE EDGES FROM ROUTER ROUTES
        for node in session.nodes:
            if node.node_type == "router" and node.routes:
                for route_name, target_node in node.routes.items():
                    edge_exists = any(
                        e["source"] == node.id and e["target"] == target_node for e in edges_list
                    )
                    if not edge_exists:
                        condition = (
                            "on_failure"
                            if route_name in ["fail", "error", "escalate"]
                            else "on_success"
                        )
                        edges_list.append(
                            {
                                "id": f"{node.id}_to_{target_node}",
                                "source": node.id,
                                "target": target_node,
                                "condition": condition,
                                "condition_expr": None,
                                "priority": 0,
                                "input_mapping": {},
                            }
                        )

        # Build GraphSpec
        graph_spec = {
            "id": f"{session.name}-graph",
            "goal_id": session.goal.id,
            "version": "1.0.0",
            "entry_node": entry_node,
            "entry_points": entry_points,
            "pause_nodes": pause_nodes,
            "terminal_nodes": terminal_nodes,
            "nodes": [node.model_dump() for node in session.nodes],
            "edges": edges_list,
            "max_steps": 100,
            "max_retries_per_node": 3,
            "description": session.goal.description,
            "created_at": datetime.now().isoformat(),
        }

        # Collect all tools referenced by nodes
        all_tools = set()
        for node in session.nodes:
            all_tools.update(node.tools)

        # Build export data
        export_data = {
            "agent": {
                "id": session.name,
                "name": session.goal.name,
                "version": "1.0.0",
                "description": session.goal.description,
            },
            "graph": graph_spec,
            "goal": session.goal.model_dump(),
            "required_tools": list(all_tools),
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "node_count": len(session.nodes),
                "edge_count": len(edges_list),
            },
        }

        # Add enrichment if present in goal
        if hasattr(session.goal, "success_criteria"):
            enriched_criteria = []
            for criterion in session.goal.success_criteria:
                crit_dict = (
                    criterion.model_dump() if hasattr(criterion, "model_dump") else criterion
                )
                enriched_criteria.append(crit_dict)
            export_data["goal"]["success_criteria"] = enriched_criteria

        # === WRITE FILES TO DISK ===
        exports_dir = Path("exports") / session.name
        exports_dir.mkdir(parents=True, exist_ok=True)

        # Write agent.json
        agent_json_path = exports_dir / "agent.json"
        with open(agent_json_path, "w") as f:
            json.dump(export_data, f, indent=2, default=str)

        # Generate README.md
        readme_content = _generate_readme(session, export_data, all_tools)
        readme_path = exports_dir / "README.md"
        with open(readme_path, "w") as f:
            f.write(readme_content)

        # Write mcp_servers.json if MCP servers are configured
        mcp_servers_path = None
        mcp_servers_size = 0
        if session.mcp_servers:
            mcp_config = {"servers": session.mcp_servers}
            mcp_servers_path = exports_dir / "mcp_servers.json"
            with open(mcp_servers_path, "w") as f:
                json.dump(mcp_config, f, indent=2)
            mcp_servers_size = mcp_servers_path.stat().st_size

        # Get file sizes
        agent_json_size = agent_json_path.stat().st_size
        readme_size = readme_path.stat().st_size

        files_written = {
            "agent_json": {
                "path": str(agent_json_path),
                "size_bytes": agent_json_size,
            },
            "readme": {
                "path": str(readme_path),
                "size_bytes": readme_size,
            },
        }

        if mcp_servers_path:
            files_written["mcp_servers"] = {
                "path": str(mcp_servers_path),
                "size_bytes": mcp_servers_size,
            }

        return json.dumps(
            {
                "success": True,
                "agent": export_data["agent"],
                "files_written": files_written,
                "graph": graph_spec,
                "goal": session.goal.model_dump(),
                "evaluation_rules": get_evaluation_rules(),
                "required_tools": list(all_tools),
                "node_count": len(session.nodes),
                "edge_count": len(edges_list),
                "mcp_servers_count": len(session.mcp_servers),
                "note": f"Agent exported to {exports_dir}. Files: agent.json, README.md"
                + (", mcp_servers.json" if session.mcp_servers else ""),
            },
            default=str,
            indent=2,
        )
