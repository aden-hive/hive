"""Basic structure tests for Procurement Approval Agent."""

from procurement_approval_agent.agent import default_agent
from procurement_approval_agent.quickbooks_api import QuickBooksAPI, QuickBooksConfig


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


def test_quickbooks_payload_includes_account_ref() -> None:
    api = QuickBooksAPI(
        QuickBooksConfig(
            client_id="client",
            client_secret="secret",
            realm_id="realm",
            refresh_token="refresh",
        )
    )

    payload = api._build_purchase_order_payload(
        {
            "po_number": "PO-TEST-001",
            "vendor": "TechSource LLC",
            "amount": 1200,
            "currency": "USD",
        }
    )

    line_detail = payload["Line"][0]["AccountBasedExpenseLineDetail"]
    assert line_detail["AccountRef"]["value"] == "1"
