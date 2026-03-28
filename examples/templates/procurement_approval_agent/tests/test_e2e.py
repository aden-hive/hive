"""Basic structure tests for Procurement Approval Agent."""

from procurement_approval_agent.agent import default_agent


def test_graph_has_required_nodes() -> None:
    node_ids = {node.id for node in default_agent.nodes}
    assert "setup-wizard" in node_ids
    assert "intake" in node_ids
    assert "budget-check" in node_ids
    assert "manager-approval" in node_ids
    assert "vendor-check" in node_ids
    assert "po-generator" in node_ids
    assert "integration-check" in node_ids
    assert "quickbooks-sync" in node_ids
    assert "csv-export" in node_ids
    assert "notifications" in node_ids


def test_validation_passes() -> None:
    result = default_agent.validate()
    assert result["valid"] is True
