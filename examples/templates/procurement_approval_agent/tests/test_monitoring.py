"""Tests for continuous request monitoring and auto-trigger execution."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from procurement_approval_agent.monitor import RequestMonitor


def _request_payload() -> dict:
    return {
        "item": "Laptop",
        "cost": 1200,
        "department": "engineering",
        "requester": "alice@company.com",
        "justification": "Need new laptop for ML development work",
        "vendor": "TechSource LLC",
    }


def _write_request(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_monitor_processes_api_path(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        watch_dir = tmp / "watched_requests"
        monkeypatch.setenv("HIVE_AGENT_STORAGE_ROOT", str(tmp / "storage"))
        monkeypatch.setenv("QUICKBOOKS_CLIENT_ID", "x")
        monkeypatch.setenv("QUICKBOOKS_CLIENT_SECRET", "y")
        monkeypatch.setenv("QUICKBOOKS_REALM_ID", "z")

        request_file = watch_dir / "req_api.json"
        watch_dir.mkdir(parents=True, exist_ok=True)
        _write_request(request_file, _request_payload())

        monitor = RequestMonitor(
            watch_dir=watch_dir,
            mock_mode=True,
            mock_qb=True,
            notify=False,
        )
        results = asyncio.run(monitor.process_once())

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].archive_file.parent.name == "done"

        output = json.loads(results[0].output_file.read_text(encoding="utf-8"))
        assert output["output"]["sync_method"] == "api"
        assert output["output"]["qb_po_id"].startswith("QB-")


def test_monitor_processes_csv_path(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        watch_dir = tmp / "watched_requests"
        monkeypatch.setenv("HIVE_AGENT_STORAGE_ROOT", str(tmp / "storage"))
        monkeypatch.delenv("QUICKBOOKS_CLIENT_ID", raising=False)
        monkeypatch.delenv("QUICKBOOKS_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("QUICKBOOKS_REALM_ID", raising=False)

        request_file = watch_dir / "req_csv.json"
        watch_dir.mkdir(parents=True, exist_ok=True)
        _write_request(request_file, _request_payload())

        monitor = RequestMonitor(
            watch_dir=watch_dir,
            mock_mode=True,
            mock_qb=True,
            notify=False,
        )
        results = asyncio.run(monitor.process_once())

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].archive_file.parent.name == "done"

        output = json.loads(results[0].output_file.read_text(encoding="utf-8"))
        assert output["output"]["sync_method"] == "csv"
        assert output["output"]["csv_file_path"].endswith("_qb_manual_import.csv")


def test_monitor_duplicate_detection_and_force(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        watch_dir = tmp / "watched_requests"
        monkeypatch.setenv("HIVE_AGENT_STORAGE_ROOT", str(tmp / "storage"))
        monkeypatch.delenv("QUICKBOOKS_CLIENT_ID", raising=False)
        monkeypatch.delenv("QUICKBOOKS_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("QUICKBOOKS_REALM_ID", raising=False)

        watch_dir.mkdir(parents=True, exist_ok=True)
        _write_request(watch_dir / "req1.json", _request_payload())
        monitor = RequestMonitor(
            watch_dir=watch_dir,
            mock_mode=True,
            mock_qb=True,
            notify=False,
            force=False,
        )
        first = asyncio.run(monitor.process_once())
        assert len(first) == 1
        assert first[0].success is True

        _write_request(watch_dir / "req2.json", _request_payload())
        second = asyncio.run(monitor.process_once())
        assert len(second) == 1
        assert second[0].success is False
        assert "Duplicate request detected" in second[0].output.get("error", "")

        _write_request(watch_dir / "req3.json", _request_payload())
        force_monitor = RequestMonitor(
            watch_dir=watch_dir,
            mock_mode=True,
            mock_qb=True,
            notify=False,
            force=True,
        )
        third = asyncio.run(force_monitor.process_once())
        assert len(third) == 1
        assert third[0].success is True


def test_monitor_skip_process_exits_early(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        watch_dir = tmp / "watched_requests"
        monkeypatch.setenv("HIVE_AGENT_STORAGE_ROOT", str(tmp / "storage"))

        request_file = watch_dir / "req_skip.json"
        watch_dir.mkdir(parents=True, exist_ok=True)
        _write_request(request_file, _request_payload())

        monitor = RequestMonitor(
            watch_dir=watch_dir,
            mock_mode=True,
            mock_qb=True,
            notify=False,
            default_process_request=False,
        )
        results = asyncio.run(monitor.process_once())

        assert len(results) == 1
        assert results[0].success is True
        output = json.loads(results[0].output_file.read_text(encoding="utf-8"))
        assert output["output"]["process_request"] is False
        assert "validated_request" not in output["output"]


def test_monitor_forces_api_path_without_env_credentials(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        watch_dir = tmp / "watched_requests"
        monkeypatch.setenv("HIVE_AGENT_STORAGE_ROOT", str(tmp / "storage"))
        monkeypatch.delenv("QUICKBOOKS_CLIENT_ID", raising=False)
        monkeypatch.delenv("QUICKBOOKS_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("QUICKBOOKS_REALM_ID", raising=False)

        request_file = watch_dir / "req_forced_api.json"
        watch_dir.mkdir(parents=True, exist_ok=True)
        _write_request(request_file, _request_payload())

        monitor = RequestMonitor(
            watch_dir=watch_dir,
            mock_mode=True,
            mock_qb=True,
            notify=False,
            sync_method="api",
        )
        results = asyncio.run(monitor.process_once())

        assert len(results) == 1
        assert results[0].success is True
        output = json.loads(results[0].output_file.read_text(encoding="utf-8"))
        assert output["output"]["sync_method"] == "api"
