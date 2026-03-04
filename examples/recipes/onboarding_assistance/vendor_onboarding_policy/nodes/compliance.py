from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class NodeResult:
    ok: bool
    data: Dict[str, Any]
    notes: str = ""


REQUIRED_DOCS_BY_TYPE = {
    "payment_processor": ["registration_certificate", "tax_certificate", "aml_policy", "privacy_policy"],
    "data_provider": ["registration_certificate", "tax_certificate", "privacy_policy", "data_processing_terms"],
    "security_vendor": ["registration_certificate", "tax_certificate", "security_policy"],
    "software_vendor": ["registration_certificate", "tax_certificate", "privacy_policy"],
    "consultant": ["registration_certificate", "tax_certificate"],
    "logistics_vendor": ["registration_certificate", "tax_certificate"],
    "other": ["registration_certificate", "tax_certificate"],
}


def run(state: Dict[str, Any]) -> NodeResult:
    vendor = (state or {}).get("vendor", {})
    vendor_type = (state or {}).get("vendor_type", "other")
    docs = set([d.strip().lower() for d in (vendor.get("documents") or []) if isinstance(d, str)])

    required = REQUIRED_DOCS_BY_TYPE.get(vendor_type, REQUIRED_DOCS_BY_TYPE["other"])
    missing_docs: List[str] = [d for d in required if d.lower() not in docs]

    status = "pass" if not missing_docs else "needs_documents"

    new_state = dict(state or {})
    new_state["compliance"] = {
        "status": status,
        "required_docs": required,
        "missing_docs": missing_docs,
    }
    new_state["audit"].append({"node": "compliance", "event": "checked_documents", "missing_docs": missing_docs})

    notes = "Compliance docs complete" if status == "pass" else f"Missing documents: {', '.join(missing_docs)}"
    return NodeResult(ok=True, data=new_state, notes=notes)
