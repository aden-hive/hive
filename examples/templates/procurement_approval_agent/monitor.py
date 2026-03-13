"""Continuous monitoring utilities for Procurement Approval Agent."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any
import smtplib

from .agent import default_agent
from .nodes.quickbooks import has_quickbooks_api_credentials


REQUIRED_FIELDS = {
    "item",
    "cost",
    "department",
    "requester",
    "justification",
}


@dataclass
class MonitorResult:
    source_file: Path
    success: bool
    output_file: Path
    archive_file: Path
    output: dict[str, Any]


class RequestMonitor:
    """Poll a folder and process each request JSON through the workflow."""

    def __init__(
        self,
        watch_dir: Path,
        poll_interval: float = 2.0,
        mock_mode: bool = False,
        mock_qb: bool = True,
        auto_open_csv: bool = False,
        notify: bool = True,
        force: bool = False,
        interactive: bool = False,
        default_process_request: bool = True,
        default_sync_confirmed: bool = True,
        sync_method: str = "auto",
        qb_available: str = "auto",
        qb_credential_ref: str | None = None,
    ) -> None:
        self.watch_dir = watch_dir
        self.poll_interval = poll_interval
        self.mock_mode = mock_mode
        self.mock_qb = mock_qb
        self.auto_open_csv = auto_open_csv
        self.notify = notify
        self.force = force
        self.interactive = interactive
        self.default_process_request = default_process_request
        self.default_sync_confirmed = default_sync_confirmed
        self.sync_method = sync_method
        self.qb_available = qb_available
        self.qb_credential_ref = qb_credential_ref

        self.processing_dir = self.watch_dir / "processing"
        self.done_dir = self.watch_dir / "done"
        self.failed_dir = self.watch_dir / "failed"
        self.results_dir = self.watch_dir / "results"
        self.history_file = self.watch_dir / "history.json"

        for d in [self.watch_dir, self.processing_dir, self.done_dir, self.failed_dir, self.results_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def _load_request(self, path: Path) -> dict[str, Any]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        missing = REQUIRED_FIELDS - set(raw.keys())
        if missing:
            raise ValueError(f"Missing required fields: {sorted(missing)}")
        if "vendor" not in raw or not raw["vendor"]:
            raw["vendor"] = "Unknown"
        return raw

    async def process_file(self, path: Path) -> MonitorResult:
        processing_file = self.processing_dir / path.name
        shutil.move(str(path), str(processing_file))

        try:
            request_data = self._load_request(processing_file)
            request_hash = self._request_hash(request_data)
            if not self.force and self._is_duplicate_recent(request_hash):
                warning = (
                    "Duplicate request detected in last 24h; skipping. "
                    "Use --force to override."
                )
                output = {
                    "success": False,
                    "error": warning,
                    "steps_executed": 0,
                    "output": {},
                }
                output_file = self.results_dir / f"{processing_file.stem}.result.json"
                output_file.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
                archive_file = self.failed_dir / processing_file.name
                shutil.move(str(processing_file), str(archive_file))
                print(f"[monitor] WARNING duplicate skipped: {processing_file.name}")
                return MonitorResult(
                    source_file=path,
                    success=False,
                    output_file=output_file,
                    archive_file=archive_file,
                    output=output,
                )

            runtime_context = dict(request_data)
            runtime_context.update(self._runtime_controls(processing_file.name))
            if self.qb_credential_ref:
                runtime_context["qb_credential_ref"] = self.qb_credential_ref

            result = await default_agent.run(
                runtime_context,
                mock_mode=self.mock_mode,
                mock_qb=self.mock_qb,
            )

            output = {
                "success": result.success,
                "error": result.error,
                "steps_executed": result.steps_executed,
                "output": result.output or {},
            }
            output_file = self.results_dir / f"{processing_file.stem}.result.json"
            output_file.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")

            archive_base = self.done_dir if result.success else self.failed_dir
            archive_file = archive_base / processing_file.name
            shutil.move(str(processing_file), str(archive_file))
            if result.success:
                self._record_request_hash(request_hash)

            if result.success:
                self._auto_post_actions(result.output or {})
            if self.notify:
                self._send_notifications(processing_file.name, output)

            return MonitorResult(
                source_file=path,
                success=bool(result.success),
                output_file=output_file,
                archive_file=archive_file,
                output=output,
            )
        except Exception as exc:
            output = {
                "success": False,
                "error": str(exc),
                "steps_executed": 0,
                "output": {},
            }
            output_file = self.results_dir / f"{processing_file.stem}.result.json"
            output_file.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
            archive_file = self.failed_dir / processing_file.name
            if processing_file.exists():
                shutil.move(str(processing_file), str(archive_file))
            if self.notify:
                self._send_notifications(processing_file.name, output)
            return MonitorResult(
                source_file=path,
                success=False,
                output_file=output_file,
                archive_file=archive_file,
                output=output,
            )

    def _prompt_yes_no(self, question: str, default: bool) -> bool:
        suffix = "Y/n" if default else "y/N"
        while True:
            response = input(f"{question} [{suffix}]: ").strip().lower()
            if response == "":
                return default
            if response in {"y", "yes"}:
                return True
            if response in {"n", "no"}:
                return False
            print("Please answer yes or no.")

    def _runtime_controls(self, request_name: str) -> dict[str, Any]:
        if self.interactive:
            print(f"[monitor] interactive checkpoint for {request_name}")
            process_request = self._prompt_yes_no(
                "Process this purchase request now?",
                default=self.default_process_request,
            )
            controls: dict[str, Any] = {"process_request": process_request}
            if not process_request:
                controls["sync_confirmed"] = False
                return controls

            has_qb = self._prompt_yes_no(
                "Do you have QuickBooks API credentials configured for this run?",
                default=has_quickbooks_api_credentials(credential_ref=self.qb_credential_ref),
            )
            controls["declared_qb_api_available"] = has_qb
            controls["declared_sync_preference"] = "api" if has_qb else "csv"
            controls["sync_confirmed"] = self._prompt_yes_no(
                "Proceed with final sync/export step after PO generation?",
                default=self.default_sync_confirmed,
            )
            return controls

        controls = {
            "process_request": self.default_process_request,
            "sync_confirmed": self.default_sync_confirmed,
        }
        if self.sync_method in {"api", "csv"}:
            controls["declared_sync_preference"] = self.sync_method
            controls["declared_qb_api_available"] = self.sync_method == "api"
            return controls
        if self.qb_available in {"yes", "no"}:
            has_qb = self.qb_available == "yes"
            controls["declared_qb_api_available"] = has_qb
            controls["declared_sync_preference"] = "api" if has_qb else "csv"
            return controls

        has_qb = has_quickbooks_api_credentials(credential_ref=self.qb_credential_ref)
        controls["declared_qb_api_available"] = has_qb
        controls["declared_sync_preference"] = "api" if has_qb else "csv"
        return controls

    def _request_hash(self, request_data: dict[str, Any]) -> str:
        key = "|".join(
            [
                str(request_data.get("item", "")).strip().lower(),
                str(request_data.get("cost", "")).strip(),
                str(request_data.get("department", "")).strip().lower(),
                str(request_data.get("requester", "")).strip().lower(),
            ]
        )
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _load_history(self) -> list[dict[str, Any]]:
        if not self.history_file.exists():
            return []
        try:
            data = json.loads(self.history_file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _save_history(self, rows: list[dict[str, Any]]) -> None:
        self.history_file.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    def _is_duplicate_recent(self, request_hash: str) -> bool:
        cutoff = time.time() - 24 * 60 * 60
        history = self._load_history()
        recent = [row for row in history if float(row.get("ts", 0)) >= cutoff]
        self._save_history(recent)
        return any(row.get("hash") == request_hash for row in recent)

    def _record_request_hash(self, request_hash: str) -> None:
        history = self._load_history()
        cutoff = time.time() - 24 * 60 * 60
        history = [row for row in history if float(row.get("ts", 0)) >= cutoff]
        history.append({"hash": request_hash, "ts": time.time()})
        self._save_history(history)

    async def process_once(self) -> list[MonitorResult]:
        candidates = sorted(
            [
                p
                for p in self.watch_dir.glob("*.json")
                if p.is_file() and p.name != self.history_file.name
            ],
            key=lambda p: p.stat().st_mtime,
        )
        results: list[MonitorResult] = []
        for path in candidates:
            result = await self.process_file(path)
            status = "SUCCESS" if result.success else "FAILED"
            print(f"[monitor] {status} {path.name} -> {result.output_file}")
            results.append(result)
        return results

    async def run_forever(self) -> None:
        while True:
            await self.process_once()
            await asyncio.sleep(self.poll_interval)

    def _auto_post_actions(self, workflow_output: dict[str, Any]) -> None:
        sync_method = workflow_output.get("sync_method")
        if sync_method == "csv" and self.auto_open_csv:
            csv_rel = workflow_output.get("csv_file_path")
            if isinstance(csv_rel, str) and csv_rel:
                self._reveal_file(csv_rel)

    def _reveal_file(self, rel_path: str) -> None:
        full_path = Path(__file__).resolve().parents[0] / rel_path
        if not full_path.exists():
            return
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", "-R", str(full_path)], check=False)
            elif sys.platform.startswith("linux"):
                subprocess.run(["xdg-open", str(full_path.parent)], check=False)
        except Exception:
            pass

    def _send_notifications(self, request_name: str, payload: dict[str, Any]) -> None:
        status = "SUCCESS" if payload.get("success") else "FAILED"
        subject = f"[Procurement Agent] {status}: {request_name}"
        text = json.dumps(payload, indent=2, default=str)

        self._notify_slack(subject, payload)
        self._notify_email(subject, text)

    def _notify_slack(self, title: str, payload: dict[str, Any]) -> None:
        webhook = os.environ.get("SLACK_WEBHOOK_URL")
        if not webhook:
            return
        body = {
            "text": f"{title}\n```{json.dumps(payload, default=str)[:2800]}```",
        }
        req = urllib.request.Request(
            webhook,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass

    def _notify_email(self, subject: str, body: str) -> None:
        host = os.environ.get("SMTP_HOST")
        port = os.environ.get("SMTP_PORT")
        username = os.environ.get("SMTP_USERNAME")
        password = os.environ.get("SMTP_PASSWORD")
        sender = os.environ.get("SMTP_FROM")
        recipient = os.environ.get("SMTP_TO")

        if not all([host, port, sender, recipient]):
            return

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient
        msg.set_content(body)

        try:
            with smtplib.SMTP(host, int(port), timeout=10) as smtp:
                if username and password:
                    smtp.starttls()
                    smtp.login(username, password)
                smtp.send_message(msg)
        except Exception:
            pass


def spawn_daemon(
    watch_dir: Path,
    poll_interval: float,
    mock_mode: bool,
    mock_qb: bool,
    auto_open_csv: bool,
    notify: bool,
    force: bool,
    default_process_request: bool,
    default_sync_confirmed: bool,
    sync_method: str,
    qb_available: str,
    qb_credential_ref: str | None,
    log_file: Path,
) -> int:
    """Spawn detached monitor subprocess and return its PID."""
    cmd = [
        sys.executable,
        "-m",
        "procurement_approval_agent",
        "monitor",
        "--watch-dir",
        str(watch_dir),
        "--poll-interval",
        str(poll_interval),
        "--no-daemon",
    ]
    if mock_mode:
        cmd.append("--mock")
    if not mock_qb:
        cmd.append("--no-mock-qb")
    if auto_open_csv:
        cmd.append("--auto-open-csv")
    if not notify:
        cmd.append("--no-notify")
    if force:
        cmd.append("--force")
    if not default_process_request:
        cmd.append("--skip-process")
    if not default_sync_confirmed:
        cmd.append("--sync-cancel")
    if sync_method in {"api", "csv"}:
        cmd.extend(["--sync-method", sync_method])
    if qb_available in {"yes", "no"}:
        cmd.extend(["--qb-available", qb_available])
    if qb_credential_ref:
        cmd.extend(["--qb-credential-ref", qb_credential_ref])

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            cmd,
            stdout=log,
            stderr=log,
            start_new_session=True,
            cwd=str(Path.cwd()),
            env=os.environ.copy(),
        )
    return proc.pid


def launchd_plist_content(
    label: str,
    working_dir: Path,
    watch_dir: Path,
    log_file: Path,
    poll_interval: float,
) -> str:
    """Generate launchd plist content for macOS background service."""
    return f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
  <key>Label</key>
  <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sys.executable}</string>
    <string>-m</string>
    <string>procurement_approval_agent</string>
    <string>monitor</string>
    <string>--watch-dir</string>
    <string>{watch_dir}</string>
    <string>--poll-interval</string>
    <string>{poll_interval}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>{working_dir}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>core:examples/templates</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{log_file}</string>
  <key>StandardErrorPath</key>
  <string>{log_file}</string>
</dict>
</plist>
"""


def write_launchd_plist(
    destination: Path,
    label: str,
    working_dir: Path,
    watch_dir: Path,
    log_file: Path,
    poll_interval: float,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        launchd_plist_content(
            label=label,
            working_dir=working_dir,
            watch_dir=watch_dir,
            log_file=log_file,
            poll_interval=poll_interval,
        ),
        encoding="utf-8",
    )
    return destination
