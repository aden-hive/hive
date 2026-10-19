"""Wiring smoke test for the queen → fork → colony flow.

Verifies that the agent loader picks a colony's ``worker.json`` (the real
worker spec) rather than its ``metadata.json`` provenance file. Runs
entirely against a temp directory — no LLM, no queen identity hook.
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# AgentLoader skips metadata.json when picking a worker config
# ---------------------------------------------------------------------------


def test_agent_loader_picks_worker_json_not_metadata_json(tmp_path):
    """AgentLoader.load must select worker.json from a colony, not metadata.json.

    Regression: ``metadata.json`` sorts before ``worker.json`` alphabetically;
    if it isn't excluded, the loader treats colony provenance as a worker spec
    and the worker spawns under the wrong storage path with no goal/tools.
    """
    from framework.loader.agent_loader import AgentLoader

    colony_dir = tmp_path / "colonies" / "honeycomb"
    colony_dir.mkdir(parents=True)
    (colony_dir / "data").mkdir()

    # Colony provenance (must NOT be picked)
    (colony_dir / "metadata.json").write_text(
        json.dumps(
            {
                "colony_name": "honeycomb",
                "queen_name": "queen_finance_fundraising",
                "queen_session_id": "session_xxx",
                "workers": {"worker": {"task": "trade"}},
            }
        ),
        encoding="utf-8",
    )

    # Real worker config
    (colony_dir / "worker.json").write_text(
        json.dumps(
            {
                "name": "worker",
                "version": "1.0.0",
                "description": "trader",
                "goal": {"description": "trade honeycomb", "success_criteria": [], "constraints": []},
                "system_prompt": "be a careful trader",
                "tools": ["read_file", "search_files"],
                "loop_config": {"max_iterations": 50},
            }
        ),
        encoding="utf-8",
    )

    runner = AgentLoader.load(
        colony_dir,
        interactive=False,
        skip_credential_validation=True,
    )

    # Picked the right config: name comes from worker.json
    assert runner.graph.nodes[0].id == "worker"
    assert runner.goal.description == "trade honeycomb"
    assert "read_file" in runner.graph.nodes[0].tools
