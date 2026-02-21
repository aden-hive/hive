"""
Custom tool functions for SDR Agent.

These tools extend the built-in Hive tools with SDR-specific utilities
for loading and writing contact/outreach data.
"""

import json
import os
from pathlib import Path


def get_storage_path() -> Path:
    """Get the SDR agent's local storage path."""
    path = Path.home() / ".hive" / "agents" / "sdr_agent" / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_contacts_from_json(contacts_json: str, filename: str = "contacts.jsonl") -> dict:
    """
    Parse a JSON contacts list and write it to a JSONL file for processing.

    Args:
        contacts_json: JSON string containing a list of contact objects.
            Each contact should have: name, email (optional), company,
            title, linkedin_url (optional), connection_degree, is_alumni,
            school_name (optional), connections_count (optional).
        filename: Output filename (default: contacts.jsonl)

    Returns:
        dict: {"filename": str, "count": int} — path to the written file
              and the number of contacts parsed.
    """
    storage = get_storage_path()
    output_path = storage / filename

    try:
        contacts = json.loads(contacts_json)
        if not isinstance(contacts, list):
            contacts = [contacts]
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}", "filename": None, "count": 0}

    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for contact in contacts:
            f.write(json.dumps(contact, ensure_ascii=False) + "\n")
            count += 1

    return {"filename": str(output_path), "count": count}


def summarize_campaign_results(
    scored_file: str,
    filtered_count: int,
    drafts_file: str,
) -> dict:
    """
    Summarize SDR campaign results across all pipeline stages.

    Args:
        scored_file: Path to scored_contacts.jsonl
        filtered_count: Number of contacts filtered by scam detection
        drafts_file: Path to drafts.jsonl

    Returns:
        dict: Campaign summary statistics
    """
    storage = get_storage_path()

    stats = {
        "total_scored": 0,
        "total_filtered": filtered_count,
        "total_safe": 0,
        "total_drafted": 0,
        "top_contacts": [],
    }

    # Count scored contacts
    scored_path = Path(scored_file) if os.path.isabs(scored_file) else storage / scored_file
    if scored_path.exists():
        with open(scored_path, encoding="utf-8") as f:
            contacts = [json.loads(line) for line in f if line.strip()]
        stats["total_scored"] = len(contacts)
        stats["total_safe"] = len(contacts) - filtered_count
        # Top 3 by priority score
        top = sorted(contacts, key=lambda c: c.get("priority_score", 0), reverse=True)[:3]
        stats["top_contacts"] = [
            {
                "name": c.get("name"),
                "company": c.get("company"),
                "priority_score": c.get("priority_score"),
            }
            for c in top
        ]

    # Count drafts created
    drafts_path = Path(drafts_file) if os.path.isabs(drafts_file) else storage / drafts_file
    if drafts_path.exists():
        with open(drafts_path, encoding="utf-8") as f:
            stats["total_drafted"] = sum(1 for line in f if line.strip())

    return stats
