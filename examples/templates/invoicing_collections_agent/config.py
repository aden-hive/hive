"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Invoicing & Collections Agent"
    version: str = "1.0.0"
    description: str = "Automated invoice collections with human-in-the-loop escalation"
    intro_message: str = (
        "Hi! I'm your invoicing and collections assistant. Point me at a CSV "
        "of invoices and I'll scan for overdue accounts, send reminder emails, "
        "escalate high-value or severely overdue invoices for your review, and "
        "generate an AR aging report. Ready to get started?"
    )


# ---------------------------------------------------------------------------
# Collection configuration
# ---------------------------------------------------------------------------
# Python dict instead of YAML — the codebase has no pyyaml dependency.

COLLECTION_CONFIG: dict = {
    "aging_buckets": [
        {
            "label": "current",
            "min_days": 0,
            "max_days": 2,
            "action": "none",
            "description": "Not yet overdue — no action required.",
        },
        {
            "label": "3_day",
            "min_days": 3,
            "max_days": 14,
            "action": "gentle_reminder",
            "description": "Gentle reminder with direct payment link.",
        },
        {
            "label": "15_day",
            "min_days": 15,
            "max_days": 29,
            "action": "firm_reminder_cc_ae",
            "description": "Firmer tone, CC the assigned Account Executive.",
        },
        {
            "label": "30_plus",
            "min_days": 30,
            "max_days": None,
            "action": "restrict_and_notify_cfo",
            "description": (
                "Restrict client software access via API and notify the CFO."
            ),
        },
    ],
    # Invoices above this amount always require HITL escalation regardless
    # of aging bucket.
    "escalation_threshold_usd": 10_000,
    # How many days between follow-up reminders within the same bucket.
    "reminder_cadence_days": 7,
    "from_email": "collections@example.com",
    "payment_link_base": "https://pay.example.com/invoice/",
    "cfo_email": "cfo@example.com",
    "email_templates": {
        "gentle_reminder": {
            "subject": "Friendly Reminder: Invoice {invoice_id} is Past Due",
            "tone": "polite",
        },
        "firm_reminder_cc_ae": {
            "subject": "Second Notice: Invoice {invoice_id} Requires Immediate Attention",
            "tone": "firm",
        },
        "restrict_and_notify_cfo": {
            "subject": "Final Notice: Invoice {invoice_id} — Access Restricted",
            "tone": "final",
        },
    },
}


metadata = AgentMetadata()
