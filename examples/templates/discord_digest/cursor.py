"""Cursor management for incremental Discord message fetching.

Stores the last-processed message ID per channel so reruns only
fetch new messages. Message IDs are Discord snowflakes — higher
values mean newer messages.
"""

from __future__ import annotations

import json
from pathlib import Path

CURSOR_FILENAME = "cursors.json"


def read_cursors(storage_path: Path) -> dict[str, str]:
    """Load per-channel cursors from disk.

    Returns a dict mapping channel_id -> last_message_id.
    Returns empty dict if file doesn't exist or is invalid.
    """
    path = storage_path / CURSOR_FILENAME
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_cursors(cursors: dict[str, str], storage_path: Path) -> Path:
    """Save per-channel cursors to disk. Returns the path written."""
    path = storage_path / CURSOR_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cursors, f, indent=2)
    return path


def update_cursors(
    existing: dict[str, str],
    new_messages: dict[str, str],
) -> dict[str, str]:
    """Merge new high-water marks into existing cursors.

    For each channel, keeps the higher message ID (newer message).
    Preserves channels in existing that aren't in new_messages.
    """
    merged = dict(existing)
    for channel_id, message_id in new_messages.items():
        old = merged.get(channel_id)
        if old is None or int(message_id) > int(old):
            merged[channel_id] = message_id
    return merged
