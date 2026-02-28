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
            "max_days": 30,
            "action": "none",
            "description": "Not yet overdue — no action required.",
        },
        {
            "label": "30_day",
            "min_days": 31,
            "max_days": 60,
            "action": "first_reminder",
            "description": "First overdue notice.",
        },
        {
            "label": "60_day",
            "min_days": 61,
            "max_days": 90,
            "action": "second_reminder",
            "description": "Second overdue notice with firmer tone.",
        },
        {
            "label": "90_plus",
            "min_days": 91,
            "max_days": None,
            "action": "escalate",
            "description": "Severely overdue — escalate for human review.",
        },
    ],
    # Invoices above this amount always require HITL escalation regardless
    # of aging bucket.
    "escalation_threshold_usd": 10_000,
    # How many days between follow-up reminders within the same bucket.
    "reminder_cadence_days": 7,
    "from_email": "collections@example.com",
    "email_templates": {
        "first_reminder": {
            "subject": "Friendly Reminder: Invoice {invoice_id} is Past Due",
            "tone": "polite",
        },
        "second_reminder": {
            "subject": "Second Notice: Invoice {invoice_id} Requires Attention",
            "tone": "firm",
        },
    },
}


metadata = AgentMetadata()
