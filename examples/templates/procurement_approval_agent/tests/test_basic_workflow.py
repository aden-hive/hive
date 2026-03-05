"""Basic end-to-end workflow test for Procurement Approval Agent."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from procurement_approval_agent.agent import ProcurementApprovalAgent, default_agent


def _setup_test_data() -> None:
    """Create sample budget DB and approved vendor CSV for test runs."""
    agent_dir = Path(__file__).resolve().parents[1]
    data_dir = agent_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    db_path = data_dir / "budget_tracking.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS department_budget (
                department TEXT PRIMARY KEY,
                allocated REAL NOT NULL,
                spent REAL NOT NULL
            )
            """
        )
        conn.executemany(
            "INSERT OR REPLACE INTO department_budget (department, allocated, spent) VALUES (?, ?, ?)",
            [
                ("engineering", 50000, 18000),
                ("finance", 30000, 12000),
                ("operations", 40000, 25000),
            ],
        )
        conn.commit()

    vendors_csv = data_dir / "approved_vendors.csv"
    vendors_csv.write_text(
        "vendor_name\nAcme Supplies\nTechSource LLC\nNorthwind Office Systems\nGlobal Industrial\n",
        encoding="utf-8",
    )
    qb_mock_path = data_dir / "qb_mock_responses.json"
    if qb_mock_path.exists():
        qb_mock_path.unlink()


def _set_qb_creds(enabled: bool) -> None:
    if enabled:
        os.environ["QUICKBOOKS_CLIENT_ID"] = "mock-client-id"
        os.environ["QUICKBOOKS_CLIENT_SECRET"] = "mock-client-secret"
        os.environ["QUICKBOOKS_REALM_ID"] = "mock-realm-id"
    else:
        os.environ.pop("QUICKBOOKS_CLIENT_ID", None)
        os.environ.pop("QUICKBOOKS_CLIENT_SECRET", None)
        os.environ.pop("QUICKBOOKS_REALM_ID", None)


def _run_workflow(mock_qb: bool) -> tuple[dict, Path]:
    context = {
        "item": "Laptop",
        "cost": 1200,
        "department": "engineering",
        "requester": "alice@company.com",
        "justification": "Need new laptop for ML development work",
        "vendor": "TechSource LLC",
    }
    result = asyncio.run(default_agent.run(context, mock_mode=True, mock_qb=mock_qb))
    assert result.success is True
    assert isinstance(result.output, dict)
    qb_mock_path = Path(__file__).resolve().parents[1] / "data" / "qb_mock_responses.json"
    return result.output, qb_mock_path


def test_full_workflow_api_path_mock_mode() -> None:
    _setup_test_data()
    _set_qb_creds(enabled=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        previous_storage_root = os.environ.get("HIVE_AGENT_STORAGE_ROOT")
        os.environ["HIVE_AGENT_STORAGE_ROOT"] = tmpdir
        try:
            output, qb_mock_path = _run_workflow(mock_qb=True)

            assert output.get("budget_status") == "auto_approved"
            assert output.get("vendor_approved") is True
            assert output.get("po_number", "").startswith("PO-")
            assert output.get("validated_request", {}).get("item") == "Laptop"
            assert output.get("validated_request", {}).get("requester") == "alice@company.com"
            assert float(output.get("validated_request", {}).get("cost", 0)) == 1200.0
            assert output.get("sync_method") == "api"
            assert output.get("qb_po_id", "").startswith("QB-")
            assert output.get("sync_status") == "mock_synced"
            assert len(output.get("po_files_created", [])) == 3
            assert len(output.get("notifications_created", [])) == 3
            assert qb_mock_path.exists() is True
            qb_records = json.loads(qb_mock_path.read_text(encoding="utf-8"))
            assert isinstance(qb_records, list) and len(qb_records) >= 1
            assert qb_records[-1]["response"]["qb_po_id"].startswith("QB-")
        finally:
            if previous_storage_root is None:
                os.environ.pop("HIVE_AGENT_STORAGE_ROOT", None)
            else:
                os.environ["HIVE_AGENT_STORAGE_ROOT"] = previous_storage_root
            _set_qb_creds(enabled=False)


def test_full_workflow_csv_fallback_mock_mode() -> None:
    _setup_test_data()
    _set_qb_creds(enabled=False)
    with tempfile.TemporaryDirectory() as tmpdir:
        previous_storage_root = os.environ.get("HIVE_AGENT_STORAGE_ROOT")
        os.environ["HIVE_AGENT_STORAGE_ROOT"] = tmpdir
        try:
            output, qb_mock_path = _run_workflow(mock_qb=True)

            assert output.get("sync_method") == "csv"
            assert output.get("validated_request", {}).get("item") == "Laptop"
            assert output.get("validated_request", {}).get("requester") == "alice@company.com"
            assert float(output.get("validated_request", {}).get("cost", 0)) == 1200.0
            assert output.get("csv_file_path", "").endswith("_qb_manual_import.csv")
            assert output.get("import_instructions", "").endswith("_qb_import_instructions.md")
            assert output.get("qb_po_id") in (None, "")
            assert qb_mock_path.exists() is False

            data_dir = Path(__file__).resolve().parents[1] / "data"
            assert (data_dir / output["csv_file_path"].replace("data/", "")).exists() is True
            assert (data_dir / output["import_instructions"].replace("data/", "")).exists() is True
        finally:
            if previous_storage_root is None:
                os.environ.pop("HIVE_AGENT_STORAGE_ROOT", None)
            else:
                os.environ["HIVE_AGENT_STORAGE_ROOT"] = previous_storage_root


def test_setup_wizard_runs_on_first_execution() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _set_qb_creds(enabled=False)
        previous_storage_root = os.environ.get("HIVE_AGENT_STORAGE_ROOT")
        os.environ["HIVE_AGENT_STORAGE_ROOT"] = tmpdir
        try:
            agent = ProcurementApprovalAgent()
            agent._setup(mock_mode=True, mock_qb=True)
            assert agent._graph is not None
            assert agent._graph.entry_node == "setup-wizard"
        finally:
            if previous_storage_root is None:
                os.environ.pop("HIVE_AGENT_STORAGE_ROOT", None)
            else:
                os.environ["HIVE_AGENT_STORAGE_ROOT"] = previous_storage_root


def test_setup_wizard_is_skipped_after_preference_saved() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _set_qb_creds(enabled=True)
        previous_storage_root = os.environ.get("HIVE_AGENT_STORAGE_ROOT")
        os.environ["HIVE_AGENT_STORAGE_ROOT"] = tmpdir
        try:
            context = {
                "item": "Laptop",
                "cost": 1200,
                "department": "engineering",
                "requester": "alice@company.com",
                "justification": "Need new laptop for ML development work",
                "vendor": "TechSource LLC",
            }
            first_result = asyncio.run(default_agent.run(context, mock_mode=True, mock_qb=True))
            assert first_result.success is True

            setup_file = Path(tmpdir) / "procurement_approval_agent" / "setup_config.json"
            assert setup_file.exists() is True

            next_agent = ProcurementApprovalAgent()
            next_agent._setup(mock_mode=True, mock_qb=True)
            assert next_agent._graph is not None
            assert next_agent._graph.entry_node == "pre-execution-check"
        finally:
            if previous_storage_root is None:
                os.environ.pop("HIVE_AGENT_STORAGE_ROOT", None)
            else:
                os.environ["HIVE_AGENT_STORAGE_ROOT"] = previous_storage_root
