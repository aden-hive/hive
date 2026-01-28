"""
Graph construction MCP tools.

Handles node and edge CRUD operations for building the agent graph.
"""

import json
from typing import Annotated

from framework.graph import EdgeCondition, EdgeSpec, NodeSpec
from framework.mcp.session import get_session, save_session
from framework.mcp.validation.validators import validate_tool_credentials


def register(mcp):
    """Register graph construction tools on the MCP server."""

    @mcp.tool()
    def add_node(
        node_id: Annotated[str, "Unique identifier for the node"],
        name: Annotated[str, "Human-readable name"],
        description: Annotated[str, "What this node does"],
        node_type: Annotated[str, "Type: llm_generate, llm_tool_use, router, or function"],
        input_keys: Annotated[str, "JSON array of keys this node reads from shared memory"],
        output_keys: Annotated[str, "JSON array of keys this node writes to shared memory"],
        system_prompt: Annotated[str, "Instructions for LLM nodes"] = "",
        tools: Annotated[str, "JSON array of tool names for llm_tool_use nodes"] = "[]",
        routes: Annotated[
            str, "JSON object mapping conditions to target node IDs for router nodes"
        ] = "{}",
    ) -> str:
        """Add a node to the agent graph. Nodes process inputs and produce outputs."""
        session = get_session()

        # Parse JSON inputs
        try:
            input_keys_list = json.loads(input_keys)
            output_keys_list = json.loads(output_keys)
            tools_list = json.loads(tools)
            routes_dict = json.loads(routes)
        except json.JSONDecodeError as e:
            return json.dumps(
                {
                    "valid": False,
                    "errors": [f"Invalid JSON input: {e}"],
                    "warnings": [],
                }
            )

        # Validate credentials for tools BEFORE adding the node
        cred_error = validate_tool_credentials(tools_list)
        if cred_error:
            return json.dumps(cred_error)

        # Check for duplicate
        if any(n.id == node_id for n in session.nodes):
            return json.dumps({"valid": False, "errors": [f"Node '{node_id}' already exists"]})

        node = NodeSpec(
            id=node_id,
            name=name,
            description=description,
            node_type=node_type,
            input_keys=input_keys_list,
            output_keys=output_keys_list,
            system_prompt=system_prompt or None,
            tools=tools_list,
            routes=routes_dict,
        )

        session.nodes.append(node)

        # Validate
        errors = []
        warnings = []

        if not node_id:
            errors.append("Node must have an id")
        if not name:
            errors.append("Node must have a name")
        if node_type == "llm_tool_use" and not tools_list:
            errors.append(f"Node '{node_id}' of type llm_tool_use must specify tools")
        if node_type == "router" and not routes_dict:
            errors.append(f"Router node '{node_id}' must specify routes")
        if node_type in ("llm_generate", "llm_tool_use") and not system_prompt:
            warnings.append(f"LLM node '{node_id}' should have a system_prompt")

        save_session(session)

        return json.dumps(
            {
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings,
                "node": node.model_dump(),
                "total_nodes": len(session.nodes),
                "approval_required": True,
                "approval_question": {
                    "component_type": "node",
                    "component_name": name,
                    "question": f"Do you approve this {node_type} node: {name}?",
                    "header": "Approve Node",
                    "options": [
                        {
                            "label": "✓ Approve (Recommended)",
                            "description": f"Node '{name}' looks good, continue building",
                        },
                        {
                            "label": "✗ Reject & Modify",
                            "description": "Need to change node configuration",
                        },
                        {
                            "label": "⏸ Pause & Review",
                            "description": "I need more time to review this node",
                        },
                    ],
                },
            },
            default=str,
        )

    @mcp.tool()
    def add_edge(
        edge_id: Annotated[str, "Unique identifier for the edge"],
        source: Annotated[str, "Source node ID"],
        target: Annotated[str, "Target node ID"],
        condition: Annotated[
            str, "When to traverse: always, on_success, on_failure, conditional"
        ] = "on_success",
        condition_expr: Annotated[str, "Python expression for conditional edges"] = "",
        priority: Annotated[int, "Priority when multiple edges match (higher = first)"] = 0,
    ) -> str:
        """Connect two nodes with an edge. Edges define how execution flows between nodes."""
        session = get_session()

        # Check for duplicate
        if any(e.id == edge_id for e in session.edges):
            return json.dumps({"valid": False, "errors": [f"Edge '{edge_id}' already exists"]})

        # Map condition string to enum
        condition_map = {
            "always": EdgeCondition.ALWAYS,
            "on_success": EdgeCondition.ON_SUCCESS,
            "on_failure": EdgeCondition.ON_FAILURE,
            "conditional": EdgeCondition.CONDITIONAL,
            "llm_decide": EdgeCondition.LLM_DECIDE,
        }
        edge_condition = condition_map.get(condition, EdgeCondition.ON_SUCCESS)

        edge = EdgeSpec(
            id=edge_id,
            source=source,
            target=target,
            condition=edge_condition,
            condition_expr=condition_expr or None,
            priority=priority,
        )

        session.edges.append(edge)

        # Validate
        errors = []

        if not any(n.id == source for n in session.nodes):
            errors.append(f"Source node '{source}' not found")
        if not any(n.id == target for n in session.nodes):
            errors.append(f"Target node '{target}' not found")
        if edge_condition == EdgeCondition.CONDITIONAL and not condition_expr:
            errors.append(f"Conditional edge '{edge_id}' needs condition_expr")

        save_session(session)

        return json.dumps(
            {
                "valid": len(errors) == 0,
                "errors": errors,
                "edge": edge.model_dump(),
                "total_edges": len(session.edges),
                "approval_required": True,
                "approval_question": {
                    "component_type": "edge",
                    "component_name": f"{source} → {target}",
                    "question": f"Do you approve this edge: {source} → {target}?",
                    "header": "Approve Edge",
                    "options": [
                        {
                            "label": "✓ Approve (Recommended)",
                            "description": "Edge connection looks good",
                        },
                        {
                            "label": "✗ Reject & Modify",
                            "description": "Need to change edge condition or targets",
                        },
                        {
                            "label": "⏸ Pause & Review",
                            "description": "I need more time to review this edge",
                        },
                    ],
                },
            },
            default=str,
        )

    @mcp.tool()
    def update_node(
        node_id: Annotated[str, "ID of the node to update"],
        name: Annotated[str, "Updated human-readable name"] = "",
        description: Annotated[str, "Updated description"] = "",
        node_type: Annotated[
            str, "Updated type: llm_generate, llm_tool_use, router, or function"
        ] = "",
        input_keys: Annotated[str, "Updated JSON array of input keys"] = "",
        output_keys: Annotated[str, "Updated JSON array of output keys"] = "",
        system_prompt: Annotated[str, "Updated instructions for LLM nodes"] = "",
        tools: Annotated[str, "Updated JSON array of tool names"] = "",
        routes: Annotated[str, "Updated JSON object mapping conditions to target node IDs"] = "",
    ) -> str:
        """Update an existing node in the agent graph. Only provided fields will be updated."""
        session = get_session()

        # Find the node
        node = None
        for n in session.nodes:
            if n.id == node_id:
                node = n
                break

        if not node:
            return json.dumps({"valid": False, "errors": [f"Node '{node_id}' not found"]})

        # Parse JSON inputs with error handling
        try:
            input_keys_list = json.loads(input_keys) if input_keys else None
            output_keys_list = json.loads(output_keys) if output_keys else None
            tools_list = json.loads(tools) if tools else None
            routes_dict = json.loads(routes) if routes else None
        except json.JSONDecodeError as e:
            return json.dumps(
                {
                    "valid": False,
                    "errors": [f"Invalid JSON input: {e}"],
                    "warnings": [],
                }
            )

        # Validate credentials for new tools BEFORE updating
        if tools_list:
            cred_error = validate_tool_credentials(tools_list)
            if cred_error:
                return json.dumps(cred_error)

        # Update fields if provided
        if name:
            node.name = name
        if description:
            node.description = description
        if node_type:
            node.node_type = node_type
        if input_keys_list is not None:
            node.input_keys = input_keys_list
        if output_keys_list is not None:
            node.output_keys = output_keys_list
        if system_prompt:
            node.system_prompt = system_prompt
        if tools_list is not None:
            node.tools = tools_list
        if routes_dict is not None:
            node.routes = routes_dict

        # Validate
        errors = []
        warnings = []

        if node.node_type == "llm_tool_use" and not node.tools:
            errors.append(f"Node '{node_id}' of type llm_tool_use must specify tools")
        if node.node_type == "router" and not node.routes:
            errors.append(f"Router node '{node_id}' must specify routes")
        if node.node_type in ("llm_generate", "llm_tool_use") and not node.system_prompt:
            warnings.append(f"LLM node '{node_id}' should have a system_prompt")

        save_session(session)

        return json.dumps(
            {
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings,
                "node": node.model_dump(),
                "total_nodes": len(session.nodes),
                "approval_required": True,
                "approval_question": {
                    "component_type": "node",
                    "component_name": node.name,
                    "question": f"Do you approve this updated {node.node_type} node: {node.name}?",
                    "header": "Approve Node Update",
                    "options": [
                        {
                            "label": "✓ Approve (Recommended)",
                            "description": f"Updated node '{node.name}' looks good",
                        },
                        {
                            "label": "✗ Reject & Modify",
                            "description": "Need to change node configuration",
                        },
                        {
                            "label": "⏸ Pause & Review",
                            "description": "I need more time to review this update",
                        },
                    ],
                },
            },
            default=str,
        )

    @mcp.tool()
    def delete_node(
        node_id: Annotated[str, "ID of the node to delete"],
    ) -> str:
        """Delete a node from the agent graph. Also removes all edges connected to this node."""
        session = get_session()

        # Find the node
        node_idx = None
        for i, n in enumerate(session.nodes):
            if n.id == node_id:
                node_idx = i
                break

        if node_idx is None:
            return json.dumps({"valid": False, "errors": [f"Node '{node_id}' not found"]})

        # Remove the node
        removed_node = session.nodes.pop(node_idx)

        # Remove all edges connected to this node
        removed_edges = [e.id for e in session.edges if e.source == node_id or e.target == node_id]
        session.edges = [
            e for e in session.edges if not (e.source == node_id or e.target == node_id)
        ]

        save_session(session)

        return json.dumps(
            {
                "valid": True,
                "deleted_node": removed_node.model_dump(),
                "removed_edges": removed_edges,
                "total_nodes": len(session.nodes),
                "total_edges": len(session.edges),
                "message": f"Node '{node_id}' and {len(removed_edges)} connected edge(s) removed",
            },
            default=str,
        )

    @mcp.tool()
    def delete_edge(
        edge_id: Annotated[str, "ID of the edge to delete"],
    ) -> str:
        """Delete an edge from the agent graph."""
        session = get_session()

        # Find the edge
        edge_idx = None
        for i, e in enumerate(session.edges):
            if e.id == edge_id:
                edge_idx = i
                break

        if edge_idx is None:
            return json.dumps({"valid": False, "errors": [f"Edge '{edge_id}' not found"]})

        # Remove the edge
        removed_edge = session.edges.pop(edge_idx)

        save_session(session)

        return json.dumps(
            {
                "valid": True,
                "deleted_edge": removed_edge.model_dump(),
                "total_edges": len(session.edges),
                "message": (
                    f"Edge '{edge_id}' removed: {removed_edge.source} → {removed_edge.target}"
                ),
            },
            default=str,
        )
