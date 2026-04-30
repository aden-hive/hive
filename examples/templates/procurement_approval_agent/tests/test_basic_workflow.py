"""Basic end-to-end workflow test for Procurement Approval Agent."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from pytest import MonkeyPatch

from procurement_approval_agent.agent import ProcurementApprovalAgent


_QB_ENV_KEYS = (
    "QUICKBOOKS_CLIENT_ID",
    "QUICKBOOKS_CLIENT_SECRET",
    "QUICKBOOKS_REALM_ID",
    "QUICKBOOKS_REFRESH_TOKEN",
    "QUICKBOOKS_ENV",
    "QUICKBOOKS_CREDENTIAL_REF",
)


def _setup_test_data(data_dir: Path) -> None:
    """Create sample budget DB and approved vendor CSV for test runs."""
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


def _capture_qb_env() -> dict[str, str | None]:
    return {key: os.environ.get(key) for key in _QB_ENV_KEYS}


def _restore_qb_env(previous_env: dict[str, str | None]) -> None:
    for key, value in previous_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _run_workflow(mock_qb: bool, data_dir: Path) -> tuple[dict, Path]:
    context = {
        "item": "Laptop",
        "cost": 1200,
        "department": "engineering",
        "requester": "alice@company.com",
        "justification": "Need new laptop for ML development work",
        "vendor": "TechSource LLC",
    }
    agent = ProcurementApprovalAgent()
    result = asyncio.run(agent.run(context, mock_mode=True, mock_qb=mock_qb))
    assert result.success is True
    assert isinstance(result.output, dict)
    qb_mock_path = data_dir / "qb_mock_responses.json"
    return result.output, qb_mock_path


def test_full_workflow_api_path_mock_mode() -> None:
    previous_qb_env = _capture_qb_env()
    _set_qb_creds(enabled=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "agent-data"
        _setup_test_data(data_dir)
        previous_storage_root = os.environ.get("HIVE_AGENT_STORAGE_ROOT")
        previous_data_dir = os.environ.get("PROCUREMENT_APPROVAL_AGENT_DATA_DIR")
        os.environ["HIVE_AGENT_STORAGE_ROOT"] = tmpdir
        os.environ["PROCUREMENT_APPROVAL_AGENT_DATA_DIR"] = str(data_dir)
        try:
            output, qb_mock_path = _run_workflow(mock_qb=True, data_dir=data_dir)

            assert output.get("budget_status") == "auto_approved"
            assert output.get("vendor_approved") is True
            assert output.get("po_number", "").startswith("PO-")
            assert output.get("validated_request", {}).get("item") == "Laptop"
            assert (
                output.get("validated_request", {}).get("requester")
                == "alice@company.com"
            )
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
            if previous_data_dir is None:
                os.environ.pop("PROCUREMENT_APPROVAL_AGENT_DATA_DIR", None)
            else:
                os.environ["PROCUREMENT_APPROVAL_AGENT_DATA_DIR"] = previous_data_dir
            _restore_qb_env(previous_qb_env)


def test_full_workflow_csv_fallback_mock_mode() -> None:
    previous_qb_env = _capture_qb_env()
    _set_qb_creds(enabled=False)
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "agent-data"
        _setup_test_data(data_dir)
        previous_storage_root = os.environ.get("HIVE_AGENT_STORAGE_ROOT")
        previous_data_dir = os.environ.get("PROCUREMENT_APPROVAL_AGENT_DATA_DIR")
        os.environ["HIVE_AGENT_STORAGE_ROOT"] = tmpdir
        os.environ["PROCUREMENT_APPROVAL_AGENT_DATA_DIR"] = str(data_dir)
        try:
            output, qb_mock_path = _run_workflow(mock_qb=True, data_dir=data_dir)

            assert output.get("sync_method") == "csv"
            assert output.get("validated_request", {}).get("item") == "Laptop"
            assert (
                output.get("validated_request", {}).get("requester")
                == "alice@company.com"
            )
            assert float(output.get("validated_request", {}).get("cost", 0)) == 1200.0
            assert output.get("csv_file_path", "").endswith("_qb_manual_import.csv")
            assert output.get("import_instructions", "").endswith(
                "_qb_import_instructions.md"
            )
            assert output.get("qb_po_id") in (None, "")
            assert qb_mock_path.exists() is False

            assert (
                data_dir / output["csv_file_path"].replace("data/", "")
            ).exists() is True
            assert (
                data_dir / output["import_instructions"].replace("data/", "")
            ).exists() is True
        finally:
            if previous_storage_root is None:
                os.environ.pop("HIVE_AGENT_STORAGE_ROOT", None)
            else:
                os.environ["HIVE_AGENT_STORAGE_ROOT"] = previous_storage_root
            if previous_data_dir is None:
                os.environ.pop("PROCUREMENT_APPROVAL_AGENT_DATA_DIR", None)
            else:
                os.environ["PROCUREMENT_APPROVAL_AGENT_DATA_DIR"] = previous_data_dir
            _restore_qb_env(previous_qb_env)


def test_each_workflow_run_generates_unique_po_artifacts() -> None:
    previous_qb_env = _capture_qb_env()
    _set_qb_creds(enabled=False)
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "agent-data"
        _setup_test_data(data_dir)
        previous_storage_root = os.environ.get("HIVE_AGENT_STORAGE_ROOT")
        previous_data_dir = os.environ.get("PROCUREMENT_APPROVAL_AGENT_DATA_DIR")
        os.environ["HIVE_AGENT_STORAGE_ROOT"] = tmpdir
        os.environ["PROCUREMENT_APPROVAL_AGENT_DATA_DIR"] = str(data_dir)
        try:
            first_output, _ = _run_workflow(mock_qb=True, data_dir=data_dir)
            second_output, _ = _run_workflow(mock_qb=True, data_dir=data_dir)

            assert first_output["po_number"] != second_output["po_number"]
            for po_output in (first_output, second_output):
                assert all(
                    po_output["po_number"] in rel_path
                    for rel_path in po_output.get("po_files_created", [])
                )
        finally:
            if previous_storage_root is None:
                os.environ.pop("HIVE_AGENT_STORAGE_ROOT", None)
            else:
                os.environ["HIVE_AGENT_STORAGE_ROOT"] = previous_storage_root
            if previous_data_dir is None:
                os.environ.pop("PROCUREMENT_APPROVAL_AGENT_DATA_DIR", None)
            else:
                os.environ["PROCUREMENT_APPROVAL_AGENT_DATA_DIR"] = previous_data_dir
            _restore_qb_env(previous_qb_env)


def test_over_budget_request_is_denied(monkeypatch: MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "agent-data"
        _setup_test_data(data_dir)
        monkeypatch.setenv("HIVE_AGENT_STORAGE_ROOT", str(Path(tmpdir) / "storage"))
        monkeypatch.setenv("PROCUREMENT_APPROVAL_AGENT_DATA_DIR", str(data_dir))

        result = asyncio.run(
            ProcurementApprovalAgent().run(
                {
                    "item": "High-end Server",
                    "cost": 999999,
                    "department": "engineering",
                    "requester": "alice@company.com",
                    "justification": "Need new infrastructure for testing",
                    "vendor": "TechSource LLC",
                },
                mock_mode=True,
                mock_qb=True,
            )
        )

        assert result.success is False
        assert result.output["budget_status"] == "denied"


def test_unapproved_vendor_is_rejected(monkeypatch: MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "agent-data"
        _setup_test_data(data_dir)
        monkeypatch.setenv("HIVE_AGENT_STORAGE_ROOT", str(Path(tmpdir) / "storage"))
        monkeypatch.setenv("PROCUREMENT_APPROVAL_AGENT_DATA_DIR", str(data_dir))

        result = asyncio.run(
            ProcurementApprovalAgent().run(
                {
                    "item": "Laptop",
                    "cost": 1200,
                    "department": "engineering",
                    "requester": "alice@company.com",
                    "justification": "Need new laptop for ML development work",
                    "vendor": "Not Approved Inc",
                },
                mock_mode=True,
                mock_qb=True,
            )
        )

        assert result.success is False
        assert result.output["vendor_approved"] is False


def test_setup_wizard_runs_on_first_execution() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        previous_qb_env = _capture_qb_env()
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
            _restore_qb_env(previous_qb_env)


def test_setup_wizard_is_skipped_after_preference_saved() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        previous_qb_env = _capture_qb_env()
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
            first_result = asyncio.run(
                ProcurementApprovalAgent().run(context, mock_mode=True, mock_qb=True)
            )
            assert first_result.success is True

            setup_file = (
                Path(tmpdir) / "procurement_approval_agent" / "setup_config.json"
            )
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
            _restore_qb_env(previous_qb_env)
