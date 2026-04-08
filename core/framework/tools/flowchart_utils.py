"""Flowchart utilities for generating and persisting flowchart.json files.

Extracted from queen_lifecycle_tools so that non-Queen code paths
(e.g., AgentRunner.load) can generate flowcharts for legacy agents
that lack a flowchart.json.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FLOWCHART_FILENAME = "flowchart.json"

# ── Flowchart type catalogue (9 types) ───────────────────────────────────────
FLOWCHART_TYPES = {
    "start": {"shape": "stadium", "color": "#8aad3f"},  # spring pollen
    "terminal": {"shape": "stadium", "color": "#b5453a"},  # propolis red
    "process": {"shape": "rectangle", "color": "#b5a575"},  # warm wheat
    "decision": {"shape": "diamond", "color": "#d89d26"},  # royal honey
    "io": {"shape": "parallelogram", "color": "#d06818"},  # burnt orange
    "document": {"shape": "document", "color": "#c4b830"},  # goldenrod
    "database": {"shape": "cylinder", "color": "#508878"},  # sage teal
    "subprocess": {"shape": "subroutine", "color": "#887a48"},  # propolis gold
    "browser": {"shape": "hexagon", "color": "#cc8850"},  # honey copper
}

# Backward-compat remap: old type names → canonical type
FLOWCHART_REMAP: dict[str, str] = {
    "delay": "process",
    "manual_operation": "process",
    "preparation": "process",
    "merge": "process",
    "alternate_process": "process",
    "connector": "process",
    "offpage_connector": "process",
    "extract": "process",
    "sort": "process",
    "collate": "process",
    "summing_junction": "process",
    "or": "process",
    "comment": "process",
    "display": "io",
    "manual_input": "io",
    "multi_document": "document",
    "stored_data": "database",
    "internal_storage": "database",
}


# ── File persistence ─────────────────────────────────────────────────────────


def save_flowchart_file(
    agent_path: Path | str | None,
    original_draft: dict,
    flowchart_map: dict[str, list[str]] | None,
) -> None:
    """Persist the flowchart to the agent's folder."""
    if agent_path is None:
        return
    p = Path(agent_path)
    if not p.is_dir():
        return
    try:
        target = p / FLOWCHART_FILENAME
        target.write_text(
            json.dumps(
                {"original_draft": original_draft, "flowchart_map": flowchart_map},
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.debug("Flowchart saved to %s", target)
    except Exception:
        logger.warning("Failed to save flowchart to %s", p, exc_info=True)


def load_flowchart_file(
    agent_path: Path | str | None,
) -> tuple[dict | None, dict[str, list[str]] | None]:
    """Load flowchart from the agent's folder. Returns (original_draft, flowchart_map)."""
    if agent_path is None:
        return None, None
    target = Path(agent_path) / FLOWCHART_FILENAME
    if not target.is_file():
        return None, None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data.get("original_draft"), data.get("flowchart_map")
    except Exception:
        logger.warning("Failed to load flowchart from %s", target, exc_info=True)
        return None, None


# ── Node classification ──────────────────────────────────────────────────────


def classify_flowchart_node(
    node: dict,
    index: int,
    total: int,
    edges: list[dict],
    terminal_ids: set[str],
) -> str:
    """Auto-detect the ISO 5807 flowchart type for a draft node.

    Priority: explicit override > structural detection > heuristic > default.
    """
    # Explicit override from the queen
    explicit = node.get("flowchart_type", "").strip()
    if explicit and explicit in FLOWCHART_TYPES:
        return explicit
    if explicit and explicit in FLOWCHART_REMAP:
        return FLOWCHART_REMAP[explicit]

    node_id = node["id"]
    node_tools = set(node.get("tools") or [])
    desc = (node.get("description") or "").lower()

    # GCU / browser automation nodes → hexagon
    if False:  # gcu removed
        return "browser"

    # Entry node (first node or no incoming edges) → start terminator
    incoming = {e["target"] for e in edges}
    if index == 0 or (node_id not in incoming and index == 0):
        return "start"

    # Terminal node → end terminator
    if node_id in terminal_ids:
        return "terminal"

    # Decision node: has outgoing edges with branching conditions → diamond
    outgoing = [e for e in edges if e["source"] == node_id]
    if len(outgoing) >= 2:
        conditions = {e.get("condition", "on_success") for e in outgoing}
        if len(conditions) > 1 or conditions - {"on_success"}:
            return "decision"

    # Sub-agent / subprocess nodes → subroutine (double-bordered rect)
    if node.get("sub_agents"):
        return "subprocess"

    # Database / data store nodes → cylinder
    db_tool_hints = {
        "query_database",
        "sql_query",
        "read_table",
        "write_table",
        "save_data",
        "load_data",
    }
    db_desc_hints = {"database", "data store", "storage", "persist", "cache"}
    if node_tools & db_tool_hints or any(h in desc for h in db_desc_hints):
        return "database"

    # Document generation nodes → document shape
    doc_tool_hints = {
        "generate_report",
        "create_document",
        "write_report",
        "render_template",
        "export_pdf",
    }
    doc_desc_hints = {"report", "document", "summary", "write up", "writeup"}
    if node_tools & doc_tool_hints or any(h in desc for h in doc_desc_hints):
        return "document"

    # I/O nodes: external data ingestion or delivery → parallelogram
    io_tool_hints = {
        "serve_file_to_user",
        "send_email",
        "post_message",
        "upload_file",
        "download_file",
        "fetch_url",
        "post_to_slack",
        "send_notification",
        "display_results",
    }
    io_desc_hints = {"deliver", "send", "output", "notify", "publish"}
    if node_tools & io_tool_hints or any(h in desc for h in io_desc_hints):
        return "io"

    # Default: process (rectangle)
    return "process"


# ── Draft synthesis from runtime graph ───────────────────────────────────────


def synthesize_draft_from_runtime(
    runtime_nodes: list,
    runtime_edges: list,
    agent_name: str = "",
    goal_name: str = "",
) -> tuple[dict, dict[str, list[str]]]:
    """Generate a flowchart draft from a loaded runtime graph.

    Used for agents that were never planned through the draft workflow
    (e.g., hand-coded or loaded from "my agents"). Produces a valid
    DraftGraph structure with auto-classified flowchart types.
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids = {n.id for n in runtime_nodes}

    # Build edge dicts first (needed for classification)
    for i, re in enumerate(runtime_edges):
        edges.append(
            {
                "id": f"edge-{i}",
                "source": re.source,
                "target": re.target,
                "condition": str(re.condition.value)
                if hasattr(re.condition, "value")
                else str(re.condition),
                "description": getattr(re, "description", "") or "",
                "label": "",
            }
        )

    # Terminal detection — exclude sub-agent nodes (they are leaf helpers, not endpoints)
    sub_agent_ids: set[str] = set()
    for rn in runtime_nodes:
        for sa_id in getattr(rn, "sub_agents", None) or []:
            sub_agent_ids.add(sa_id)
    sources = {e["source"] for e in edges}
    terminal_ids = node_ids - sources - sub_agent_ids
    if not terminal_ids and runtime_nodes:
        terminal_ids = {runtime_nodes[-1].id}

    # Build node dicts with classification
    total = len(runtime_nodes)
    for i, rn in enumerate(runtime_nodes):
        node: dict = {
            "id": rn.id,
            "name": rn.name,
            "description": rn.description or "",
            "node_type": getattr(rn, "node_type", "event_loop") or "event_loop",
            "tools": list(rn.tools) if rn.tools else [],
            "input_keys": list(rn.input_keys) if rn.input_keys else [],
            "output_keys": list(rn.output_keys) if rn.output_keys else [],
            "success_criteria": getattr(rn, "success_criteria", "") or "",
            "sub_agents": list(rn.sub_agents) if getattr(rn, "sub_agents", None) else [],
        }
        fc_type = classify_flowchart_node(node, i, total, edges, terminal_ids)
        fc_meta = FLOWCHART_TYPES[fc_type]
        node["flowchart_type"] = fc_type
        node["flowchart_shape"] = fc_meta["shape"]
        node["flowchart_color"] = fc_meta["color"]
        nodes.append(node)

    # Add visual edges from parent nodes to their sub_agents.
    # Sub-agents are connected via the sub_agents field, not via EdgeSpec,
    # so they'd appear as disconnected islands without this.
    # Two edges per sub-agent: delegate (parent→sub) and report (sub→parent).
    edge_counter = len(edges)
    for node in nodes:
        for sa_id in node.get("sub_agents") or []:
            if sa_id in node_ids:
                edges.append(
                    {
                        "id": f"edge-subagent-{edge_counter}",
                        "source": node["id"],
                        "target": sa_id,
                        "condition": "always",
                        "description": "sub-agent delegation",
                        "label": "delegate",
                    }
                )
                edge_counter += 1
                edges.append(
                    {
                        "id": f"edge-subagent-{edge_counter}",
                        "source": sa_id,
                        "target": node["id"],
                        "condition": "always",
                        "description": "sub-agent report back",
                        "label": "report",
                    }
                )
                edge_counter += 1

    # Group sub-agent nodes under their parent in the flowchart map
    # (mirrors what _dissolve_planning_nodes does for planned drafts)
    sub_agent_ids_final: set[str] = set()
    for node in nodes:
        for sa_id in node.get("sub_agents") or []:
            if sa_id in node_ids:
                sub_agent_ids_final.add(sa_id)

    fmap: dict[str, list[str]] = {}
    for node in nodes:
        nid = node["id"]
        if nid in sub_agent_ids_final:
            continue  # skip — will be included via parent
        absorbed = [nid]
        for sa_id in node.get("sub_agents") or []:
            if sa_id in node_ids:
                absorbed.append(sa_id)
        fmap[nid] = absorbed

    draft = {
        "agent_name": agent_name,
        "goal": goal_name,
        "description": "",
        "success_criteria": [],
        "constraints": [],
        "nodes": nodes,
        "edges": edges,
        "entry_node": nodes[0]["id"] if nodes else "",
        "terminal_nodes": sorted(terminal_ids),
        "flowchart_legend": {
            fc_type: {"shape": meta["shape"], "color": meta["color"]}
            for fc_type, meta in FLOWCHART_TYPES.items()
        },
    }

    return draft, fmap


# ── Fallback generation entry point ──────────────────────────────────────────


def generate_fallback_flowchart(
    graph: Any,
    goal: Any,
    agent_path: Path,
) -> None:
    """Generate flowchart.json from a runtime GraphSpec if none exists.

    This is a no-op if flowchart.json already exists. On failure, logs a
    warning but never raises — agent loading must not be blocked by
    flowchart generation.
    """
    try:
        existing_draft, _ = load_flowchart_file(agent_path)
        if existing_draft is not None:
            return  # already have one

        draft, fmap = synthesize_draft_from_runtime(
            runtime_nodes=list(graph.nodes),
            runtime_edges=list(graph.edges),
            agent_name=agent_path.name,
            goal_name=goal.name if goal else "",
        )

        # Enrich with Goal metadata
        if goal:
            draft["goal"] = goal.description or goal.name or ""
            draft["success_criteria"] = [sc.description for sc in (goal.success_criteria or [])]
            draft["constraints"] = [c.description for c in (goal.constraints or [])]

        # Use entry_node/terminal_nodes from GraphSpec if available
        if graph.entry_node:
            draft["entry_node"] = graph.entry_node
        if graph.terminal_nodes:
            draft["terminal_nodes"] = list(graph.terminal_nodes)

        save_flowchart_file(agent_path, draft, fmap)
        logger.info("Generated fallback flowchart.json for %s", agent_path.name)
    except Exception:
        logger.warning(
            "Failed to generate fallback flowchart for %s",
            agent_path,
            exc_info=True,
        )
