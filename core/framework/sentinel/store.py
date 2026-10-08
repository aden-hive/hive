"""On-disk config + records for Sentinel.

Two concerns, both mirroring the existing per-colony sidecar pattern in
``framework.host.colony_tools_config`` (atomic ``os.replace`` writes):

1. **Config** — a global ``sentinel`` block in ``~/.hive/configuration.json``
   (tuning only) merged with a per-colony
   ``~/.hive/colonies/<id>/notifications.json`` (the per-colony opt-in +
   channel routing). Escalation is *on by default* via the built-in Hive Inbox
   channel (no token needed — it rides the account's cloud JWT). A colony with
   no config resolves to ``channel="hive"`` + ``sentinel_enabled=True``; an
   existing file is honored as-is, and telegram/slack still require a token.

2. **Escalation records** — one JSON file per open escalation under
   ``~/.hive/colonies/<id>/escalations/<escalation_id>.json``. Disk is the
   source of truth so a reply that arrives after a restart still resolves.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from framework.config import COLONIES_DIR, get_hive_config

logger = logging.getLogger(__name__)

# Defaults for the global sentinel block (all tunable via configuration.json).
_DEFAULT_CLASSIFY_AFTER_SECONDS = 300.0  # 5 minutes
_DEFAULT_MAX_NUDGES_BEFORE_ESCALATE = 5
_DEFAULT_ESCALATE_WHEN_UI_ATTACHED = False

# The built-in always-connected channel a colony uses unless switched to
# telegram/slack. Kept in sync with ``notifier.CHANNEL_HIVE``.
DEFAULT_CHANNEL = "hive"


# --------------------------------------------------------------------------
# Global config (~/.hive/configuration.json -> "sentinel")
# --------------------------------------------------------------------------


def global_sentinel_config() -> dict[str, Any]:
    """The ``sentinel`` block from the global hive config, or ``{}``."""
    cfg = get_hive_config().get("sentinel")
    return cfg if isinstance(cfg, dict) else {}


def classify_after_seconds() -> float:
    raw = global_sentinel_config().get("classify_after_seconds", _DEFAULT_CLASSIFY_AFTER_SECONDS)
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return _DEFAULT_CLASSIFY_AFTER_SECONDS


def max_nudges_before_escalate() -> int:
    raw = global_sentinel_config().get("max_nudges_before_escalate", _DEFAULT_MAX_NUDGES_BEFORE_ESCALATE)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_NUDGES_BEFORE_ESCALATE


def escalate_when_ui_attached() -> bool:
    return bool(global_sentinel_config().get("escalate_when_ui_attached", _DEFAULT_ESCALATE_WHEN_UI_ATTACHED))


# --------------------------------------------------------------------------
# Per-colony config (~/.hive/colonies/<id>/notifications.json)
# --------------------------------------------------------------------------


@dataclass
class NotificationsConfig:
    """Resolved per-colony notification settings.

    ``sentinel_enabled`` is on by default (the built-in Hive Inbox channel is
    always connected when signed in). For telegram/slack, whether an escalation
    can actually be delivered additionally depends on a configured channel token
    — enforced at send time, not here.

    ``classify_after_seconds`` is an optional per-colony idle budget; ``None``
    means inherit the global default (:func:`classify_after_seconds`).
    """

    sentinel_enabled: bool = True
    channel: str | None = DEFAULT_CHANNEL  # "hive" | "telegram" | "slack"
    target: dict[str, Any] = field(default_factory=dict)
    allowlist: list[str] = field(default_factory=list)
    thread: dict[str, Any] = field(default_factory=dict)
    classify_after_seconds: float | None = None


def notifications_config_path(colony_id: str) -> Path:
    return COLONIES_DIR / colony_id / "notifications.json"


def load_notifications_config(colony_id: str) -> NotificationsConfig:
    """Load + resolve a colony's notification config (best-effort)."""
    path = notifications_config_path(colony_id)
    raw: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                raw = data
        except (json.JSONDecodeError, OSError):
            logger.warning("sentinel: invalid notifications.json for %s; treating as disabled", colony_id)

    allow = raw.get("allowlist") or []
    if not isinstance(allow, list):
        allow = []
    # Optional per-colony idle budget; clamp to the same >=1s floor as the
    # global value, None when unset (→ inherit global at decision time).
    cas = raw.get("classify_after_seconds")
    try:
        per_colony_budget = max(1.0, float(cas)) if cas is not None else None
    except (TypeError, ValueError):
        per_colony_budget = None
    # Migration / defaults: a colony with no config (empty raw) → Hive Inbox,
    # enabled. An existing file is honored as-is; a file that predates the
    # channel field resolves to the built-in channel rather than None.
    return NotificationsConfig(
        sentinel_enabled=bool(raw.get("sentinel_enabled", True)),
        channel=raw.get("channel") or DEFAULT_CHANNEL,
        target=raw.get("target") if isinstance(raw.get("target"), dict) else {},
        allowlist=[str(x) for x in allow],
        thread=raw.get("thread") if isinstance(raw.get("thread"), dict) else {},
        classify_after_seconds=per_colony_budget,
    )


def update_notifications_config(
    colony_id: str,
    *,
    sentinel_enabled: bool,
    channel: str | None,
    target: dict[str, Any],
    allowlist: list[str],
    classify_after_seconds: float | None = None,
) -> None:
    """Persist a colony's notification settings (merges, preserving ``thread``).

    ``classify_after_seconds`` of ``None`` clears any per-colony override so the
    colony falls back to the global default.

    Raises ``FileNotFoundError`` if the colony directory is missing — the UI
    should only call this for a real colony.
    """
    colony_path = COLONIES_DIR / colony_id
    if not colony_path.exists():
        raise FileNotFoundError(f"Colony directory not found: {colony_id}")
    path = notifications_config_path(colony_id)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            pass
    data["sentinel_enabled"] = bool(sentinel_enabled)
    data["channel"] = channel
    data["target"] = target
    data["allowlist"] = [str(x) for x in allowlist]
    if classify_after_seconds is None:
        data.pop("classify_after_seconds", None)
    else:
        data["classify_after_seconds"] = float(classify_after_seconds)
    data["updated_at"] = datetime.now(UTC).isoformat()
    _atomic_write_json(path, data)


def update_notifications_thread(colony_id: str, thread: dict[str, Any]) -> None:
    """Persist the channel thread anchor (parent message id/ts) for a colony.

    Merges into the existing file rather than overwriting it, so the user's
    enable/channel/allowlist settings survive a thread-pointer update.
    """
    path = notifications_config_path(colony_id)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            pass
    data["thread"] = thread
    data["updated_at"] = datetime.now(UTC).isoformat()
    _atomic_write_json(path, data)


# --------------------------------------------------------------------------
# Escalation records (~/.hive/colonies/<id>/escalations/<id>.json)
# --------------------------------------------------------------------------

STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"


@dataclass
class EscalationRecord:
    escalation_id: str
    colony_id: str
    session_id: str
    correlation_token: str
    park_reason: str
    question_text: str
    channel: str
    thread_ref: dict[str, Any] = field(default_factory=dict)
    status: str = STATUS_OPEN
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    resolved_at: str | None = None
    resolved_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "escalation_id": self.escalation_id,
            "colony_id": self.colony_id,
            "session_id": self.session_id,
            "correlation_token": self.correlation_token,
            "park_reason": self.park_reason,
            "question_text": self.question_text,
            "channel": self.channel,
            "thread_ref": self.thread_ref,
            "status": self.status,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EscalationRecord:
        return cls(
            escalation_id=data["escalation_id"],
            colony_id=data["colony_id"],
            session_id=data["session_id"],
            correlation_token=data.get("correlation_token", ""),
            park_reason=data.get("park_reason", ""),
            question_text=data.get("question_text", ""),
            channel=data.get("channel", ""),
            thread_ref=data.get("thread_ref") or {},
            status=data.get("status", STATUS_OPEN),
            created_at=data.get("created_at", ""),
            resolved_at=data.get("resolved_at"),
            resolved_by=data.get("resolved_by"),
        )


def escalations_dir(colony_id: str) -> Path:
    return COLONIES_DIR / colony_id / "escalations"


def _record_path(colony_id: str, escalation_id: str) -> Path:
    return escalations_dir(colony_id) / f"{escalation_id}.json"


def write_escalation(record: EscalationRecord) -> None:
    _atomic_write_json(_record_path(record.colony_id, record.escalation_id), record.to_dict())


def load_escalation(colony_id: str, escalation_id: str) -> EscalationRecord | None:
    path = _record_path(colony_id, escalation_id)
    if not path.exists():
        return None
    try:
        return EscalationRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError, KeyError):
        logger.warning("sentinel: invalid escalation record %s", path, exc_info=True)
        return None


def list_open(colony_id: str) -> list[EscalationRecord]:
    out: list[EscalationRecord] = []
    d = escalations_dir(colony_id)
    if not d.exists():
        return out
    for path in d.glob("*.json"):
        try:
            rec = EscalationRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, KeyError):
            continue
        if rec.status == STATUS_OPEN:
            out.append(rec)
    return out


def list_all_open() -> list[EscalationRecord]:
    """Every open escalation across all colonies — used to rebuild the
    in-memory token index on manager startup."""
    out: list[EscalationRecord] = []
    if not COLONIES_DIR.exists():
        return out
    for colony_path in COLONIES_DIR.iterdir():
        if colony_path.is_dir():
            out.extend(list_open(colony_path.name))
    return out


def resolve_escalation(colony_id: str, escalation_id: str, resolved_by: str | None = None) -> bool:
    """Mark an escalation resolved. Returns False if it was missing/already done."""
    rec = load_escalation(colony_id, escalation_id)
    if rec is None or rec.status == STATUS_RESOLVED:
        return False
    rec.status = STATUS_RESOLVED
    rec.resolved_at = datetime.now(UTC).isoformat()
    rec.resolved_by = resolved_by
    write_escalation(rec)
    return True


# --------------------------------------------------------------------------
# Atomic write (mirrors colony_tools_config._atomic_write_json)
# --------------------------------------------------------------------------


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".sentinel.", suffix=".json.tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
