"""QuickBooks sync helpers for procurement approval workflow."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..credentials import resolve_quickbooks_credentials


def has_quickbooks_api_credentials(credential_ref: str | None = None) -> bool:
    """Detect QuickBooks credential availability (env or Hive name/alias credential)."""
    creds = resolve_quickbooks_credentials(credential_ref=credential_ref)
    return creds.has_minimum


def mock_quickbooks_api(
    po_number: str,
    po_data: dict[str, Any] | None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Simulate a QuickBooks PO sync and persist a mock response log."""
    qb_po_id = f"QB-{po_number}"
    payload = {
        "po_number": po_number,
        "po_data": po_data or {},
    }
    response = {
        "qb_po_id": qb_po_id,
        "sync_status": "mock_synced",
        "api": "quickbooks.purchase_orders.create",
    }

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request": payload,
        "response": response,
    }

    if output_path is None:
        output_path = Path(__file__).resolve().parents[1] / "data" / "qb_mock_responses.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing: list[dict[str, Any]] = []
    if output_path.exists():
        try:
            existing_raw = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(existing_raw, list):
                existing = existing_raw
        except json.JSONDecodeError:
            existing = []

    existing.append(record)
    output_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    print(f"[mock-qb] would sync PO {po_number} to QuickBooks API")
    return response


def mock_csv_export(
    po_number: str,
    po_data: dict[str, Any] | None,
    output_dir: Path | None = None,
) -> dict[str, str]:
    """Generate fallback CSV and manual import instructions."""
    if output_dir is None:
        output_dir = Path(__file__).resolve().parents[1] / "data" / "po"

    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / f"{po_number}_qb_manual_import.csv"
    md_path = output_dir / f"{po_number}_qb_import_instructions.md"

    vendor = (po_data or {}).get("vendor", "Unknown")
    amount = (po_data or {}).get("amount", 0)
    currency = (po_data or {}).get("currency", "USD")

    csv_path.write_text(
        "DocNumber,Vendor,Amount,Currency\n"
        f"{po_number},{vendor},{amount},{currency}\n",
        encoding="utf-8",
    )

    md_path.write_text(
        "# QuickBooks Manual Import Instructions\n\n"
        f"1. Open QuickBooks and go to import purchase orders.\n"
        f"2. Upload `{csv_path.name}`.\n"
        "3. Map columns: DocNumber, Vendor, Amount, Currency.\n"
        "4. Validate preview and submit import.\n",
        encoding="utf-8",
    )

    print(f"[mock-qb-csv] generated fallback CSV for PO {po_number}")
    return {
        "csv_file_path": str(csv_path.relative_to(Path(__file__).resolve().parents[1])),
        "import_instructions": str(md_path.relative_to(Path(__file__).resolve().parents[1])),
    }
