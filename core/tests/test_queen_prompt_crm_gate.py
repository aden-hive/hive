"""The team-CRM instructions reach the queen only in builds that ship the CRM.

This repository doesn't ship ``framework.crm`` or the ``hive-crm`` CLI, so the
queen must not be told to claim, import or release people through them, and
``crm_summary`` must not be in her tool lists. A build that does ship the CRM
gets the passages back, in their original places.
"""

from __future__ import annotations

import importlib

import pytest

import framework.agents.queen.nodes as queen_nodes
import framework.config as config
from framework.tasks.tools import session_tools
from framework.tools import tracker_tools

CRM_MARKERS = ("hive-crm", "crm_summary", "CLAIM task")


def _prompt_texts(nodes) -> dict[str, str]:
    texts = {name: getattr(nodes, name) for name in nodes.__all__ if name.startswith("_queen")}
    texts["queen_node"] = nodes.queen_node.system_prompt
    return texts


def test_this_build_has_no_crm():
    assert config.CRM_IN_THIS_BUILD is False


def test_queen_prompts_skip_the_crm_without_it():
    for name, text in _prompt_texts(queen_nodes).items():
        for marker in CRM_MARKERS:
            assert marker not in text, f"{marker!r} in {name}"
    assert "crm_summary" not in queen_nodes.ALL_QUEEN_TOOLS
    # The delegation loop still reads as one numbered list.
    colony = queen_nodes._queen_behavior_colony
    assert colony.index("fan it out.") < colony.index("1. **Tracker table.**") < colony.index("Read ``hive.worker-delegation``")


def test_tool_descriptions_skip_the_crm_without_it():
    assert "CRM" not in session_tools._CREATE_DESC
    assert "## When to use this tool" in session_tools._CREATE_DESC
    assert "hive-crm" not in tracker_tools._SCOPE_PARAM["description"]


def test_prompts_point_at_the_hive_browser_cli():
    for name, text in _prompt_texts(queen_nodes).items():
        assert "gcu-tools" not in text, name
        assert "``browser_*``" not in text, name


@pytest.fixture
def nodes_with_crm(monkeypatch):
    monkeypatch.setattr(config, "CRM_IN_THIS_BUILD", True)
    try:
        yield importlib.reload(queen_nodes)
    finally:
        monkeypatch.undo()
        importlib.reload(queen_nodes)


def test_a_build_with_the_crm_keeps_its_passages(nodes_with_crm):
    nodes = nodes_with_crm
    assert "crm_summary" in nodes._QUEEN_INDEPENDENT_TOOLS
    assert "crm_summary" in nodes._QUEEN_COLONY_TOOLS
    assert "There is ALSO a shared team CRM" in nodes._queen_role_colony
    assert "**GTM work plans the CRM.**" in nodes.queen_node.system_prompt

    colony = nodes._queen_behavior_colony
    order = [
        "fan it out.",
        "WHEN THE WORK IS GTM",
        "1. **Tracker table.**",
        "5. **Review the outcome.**",
        "6. **Promote to the CRM (GTM only).**",
        "Read ``hive.worker-delegation``",
    ]
    positions = [colony.index(marker) for marker in order]
    assert positions == sorted(positions)
