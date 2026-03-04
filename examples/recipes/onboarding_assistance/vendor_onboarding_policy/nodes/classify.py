from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class NodeResult:
    ok: bool
    data: Dict[str, Any]
    notes: str = ""


def _classify(service_type: str) -> tuple[str, str]:
    s = (service_type or "").lower()

    if any(x in s for x in ["payment", "processor", "fintech", "wallet", "bank"]):
        return "payment_processor", "Service type indicates payments/financial processing"
    if any(x in s for x in ["data", "analytics", "intelligence", "insights"]):
        return "data_provider", "Service type indicates data/analytics"
    if any(x in s for x in ["security", "pentest", "vulnerability", "soc", "audit"]):
        return "security_vendor", "Service type indicates security/audit work"
    if any(x in s for x in ["logistics", "shipping", "transport", "fleet"]):
        return "logistics_vendor", "Service type indicates logistics"
    if any(x in s for x in ["consult", "advisory", "contractor", "freelance"]):
        return "consultant", "Service type indicates consulting services"
    if any(x in s for x in ["software", "engineering", "development", "saas"]):
        return "software_vendor", "Service type indicates software development/SaaS"

    return "other", "Could not confidently classify from service_type"


def run(state: Dict[str, Any]) -> NodeResult:
    vendor = (state or {}).get("vendor", {})
    vendor_type, reason = _classify(vendor.get("service_type", ""))

    new_state = dict(state or {})
    new_state["vendor_type"] = vendor_type
    new_state["vendor_type_reason"] = reason
    new_state["audit"].append({"node": "classify", "event": "classified_vendor_type", "type": vendor_type})

    return NodeResult(ok=True, data=new_state, notes=reason)
