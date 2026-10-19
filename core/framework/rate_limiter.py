"""Social-media rate limiter — prevents account bans from excessive automation.

Self-contained module (stdlib only).  Consumed by the browser-script
rate-limit hook and available to any framework-level caller.

Limits are conservative defaults with hard ceilings.  Users can raise
defaults via env vars (``HIVE_RATE_<PLATFORM>_<ACTION>_DAILY``), but
never past the ceiling.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from framework.config import get_hive_config

# ── Config file integration ─────────────────────────────────────────


def _get_config_overrides() -> dict[str, Any]:
    """Read rate_limits overrides from the hive configuration file.

    Returns a flat dict like ``{"linkedin.invite.daily": 20}``.
    """
    try:
        return get_hive_config().get("rate_limits", {})
    except Exception:
        pass
    return {}


# ── Limit definitions ────────────────────────────────────────────────

_LIMITS: dict[tuple[str, str], dict[str, Any]] = {
    # (platform, action): {hourly_default, hourly_max, daily_default, daily_max,
    #                       weekly_default, weekly_max, min_delay_s}
    ("linkedin", "profile_view"): {
        "hourly_default": 25,
        "hourly_max": 100,
        "daily_default": 150,
        "daily_max": 400,
        "weekly_default": None,
        "weekly_max": None,
        "min_delay_s": 5,
    },
    ("linkedin", "invite"): {
        "hourly_default": 10,
        "hourly_max": 25,
        "daily_default": 50,
        "daily_max": 125,
        "weekly_default": 200,
        "weekly_max": 500,
        "min_delay_s": 30,
    },
    ("linkedin", "message"): {
        "hourly_default": 20,
        "hourly_max": 80,
        "daily_default": 60,
        "daily_max": 200,
        "weekly_default": None,
        "weekly_max": None,
        "min_delay_s": 15,
    },
    ("linkedin", "comment"): {
        "hourly_default": 8,
        "hourly_max": 30,
        "daily_default": 50,
        "daily_max": 150,
        "weekly_default": None,
        "weekly_max": None,
        "min_delay_s": 20,
    },
    ("x", "reply"): {
        "hourly_default": 10,
        "hourly_max": 30,
        "daily_default": 50,
        "daily_max": 150,
        "weekly_default": None,
        "weekly_max": None,
        "min_delay_s": 30,
    },
    ("x", "dm"): {
        "hourly_default": 20,
        "hourly_max": 80,
        "daily_default": 60,
        "daily_max": 200,
        "weekly_default": None,
        "weekly_max": None,
        "min_delay_s": 20,
    },
    ("x", "post"): {
        "hourly_default": 5,
        "hourly_max": 25,
        "daily_default": 30,
        "daily_max": 125,
        "weekly_default": None,
        "weekly_max": None,
        "min_delay_s": 60,
    },
    ("instagram", "dm"): {
        "hourly_default": 16,
        "hourly_max": 40,
        "daily_default": 80,
        "daily_max": 150,
        "weekly_default": 300,
        "weekly_max": 500,
        "min_delay_s": 45,
    },
}

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS actions (
    id           INTEGER PRIMARY KEY,
    platform     TEXT    NOT NULL,
    account_id   TEXT    NOT NULL,
    action_type  TEXT    NOT NULL,
    target_id    TEXT,
    performed_at REAL    NOT NULL,
    session_id   TEXT
);
CREATE INDEX IF NOT EXISTS idx_actions_lookup
    ON actions(platform, account_id, action_type, performed_at);
"""


def _clamp(value: int, ceiling: int | None) -> int:
    return min(value, ceiling) if ceiling is not None else value


def _resolve_limit(platform: str, action: str, window: str) -> int | None:
    """Read the effective limit for *window* (``hourly``, ``daily``, or ``weekly``).

    Priority: env var > configuration.json > default.  All clamped to ceiling.
    """
    key = (platform.lower(), action.lower())
    entry = _LIMITS.get(key)
    if entry is None:
        return None

    default = entry.get(f"{window}_default")
    ceiling = entry.get(f"{window}_max")
    if default is None:
        return None

    env_name = f"HIVE_RATE_{platform.upper()}_{action.upper()}_{window.upper()}"
    env_val = os.environ.get(env_name)
    if env_val is not None:
        try:
            return _clamp(int(env_val), ceiling)
        except ValueError:
            pass

    cfg = _get_config_overrides()
    cfg_key = f"{platform.lower()}.{action.lower()}.{window}"
    if cfg_key in cfg:
        try:
            return max(1, int(cfg[cfg_key]))
        except (ValueError, TypeError):
            pass

    return default


def _min_delay(platform: str, action: str) -> float:
    key = (platform.lower(), action.lower())
    entry = _LIMITS.get(key)
    return float(entry["min_delay_s"]) if entry else 0.0


def get_all_limits() -> list[dict[str, Any]]:
    """Return every defined limit with its effective and ceiling values."""
    out: list[dict[str, Any]] = []
    for (platform, action), entry in _LIMITS.items():
        row: dict[str, Any] = {
            "platform": platform,
            "action_type": action,
            "min_delay_s": entry.get("min_delay_s", 0),
        }
        for window in ("hourly", "daily", "weekly"):
            default = entry.get(f"{window}_default")
            if default is not None:
                row[window] = _resolve_limit(platform, action, window)
                row[f"{window}_max"] = entry.get(f"{window}_max")
                row[f"{window}_default"] = default
        out.append(row)
    return out


class SocialRateLimiter:
    """Per-account, per-action rate limiter backed by a SQLite file."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            from framework.config import HIVE_HOME

            db_path = HIVE_HOME / "social_rate_limits.db"
        self._db_path = Path(db_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    # ── public API ────────────────────────────────────────────────

    def check(
        self,
        platform: str,
        account_id: str,
        action_type: str,
    ) -> dict[str, Any]:
        """Return whether *action_type* is currently allowed.

        Checks both count-based limits (daily/weekly) and minimum delay
        since the last action of the same type for this account.
        """
        platform = platform.lower()
        action_type = action_type.lower()
        now = time.time()

        con = self._connect()
        try:
            # ── min-delay check ──────────────────────────────────
            delay = _min_delay(platform, action_type)
            if delay > 0:
                row = con.execute(
                    "SELECT performed_at FROM actions WHERE platform = ? AND account_id = ? AND action_type = ? ORDER BY performed_at DESC LIMIT 1",
                    (platform, account_id, action_type),
                ).fetchone()
                if row is not None:
                    elapsed = now - row[0]
                    if elapsed < delay:
                        remaining = delay - elapsed
                        return {
                            "allowed": False,
                            "reason": "too_fast",
                            "retry_after_seconds": round(remaining, 1),
                            "min_delay_seconds": delay,
                            "halt_campaign": False,
                        }

            # ── window checks (hourly → daily → weekly) ─────────
            _windows = (
                ("hourly", 3600, False),
                ("daily", 86400, True),
                ("weekly", 604800, True),
            )
            hourly_count = hourly_limit = None
            daily_count = daily_limit = None
            weekly_count = weekly_limit = None

            for window_name, window_secs, halt in _windows:
                limit = _resolve_limit(platform, action_type, window_name)
                if limit is None:
                    continue
                window_start = now - window_secs
                count = con.execute(
                    "SELECT COUNT(*) FROM actions WHERE platform = ? AND account_id = ? AND action_type = ? AND performed_at >= ?",
                    (platform, account_id, action_type, window_start),
                ).fetchone()[0]

                if window_name == "hourly":
                    hourly_count, hourly_limit = count, limit
                elif window_name == "daily":
                    daily_count, daily_limit = count, limit
                else:
                    weekly_count, weekly_limit = count, limit

                if count >= limit:
                    oldest = con.execute(
                        "SELECT performed_at FROM actions "
                        "WHERE platform = ? AND account_id = ? AND action_type = ? "
                        "AND performed_at >= ? "
                        "ORDER BY performed_at ASC LIMIT 1",
                        (platform, account_id, action_type, window_start),
                    ).fetchone()
                    retry_after = round((oldest[0] + window_secs) - now, 1) if oldest else float(window_secs)
                    if retry_after < 0:
                        retry_after = 0
                    return {
                        "allowed": False,
                        "reason": f"{window_name}_limit_reached",
                        f"{window_name}_count": count,
                        f"{window_name}_limit": limit,
                        "retry_after_seconds": retry_after,
                        "halt_campaign": halt,
                    }

            return {
                "allowed": True,
                "hourly_count": hourly_count,
                "hourly_limit": hourly_limit,
                "daily_count": daily_count,
                "daily_limit": daily_limit,
                "weekly_count": weekly_count,
                "weekly_limit": weekly_limit,
            }
        finally:
            con.close()

    def record(
        self,
        platform: str,
        account_id: str,
        action_type: str,
        target_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Record a successfully completed action."""
        con = self._connect()
        try:
            con.execute(
                "INSERT INTO actions (platform, account_id, action_type, target_id, performed_at, session_id) VALUES (?, ?, ?, ?, ?, ?)",
                (platform.lower(), account_id, action_type.lower(), target_id, time.time(), session_id),
            )
            con.commit()
        finally:
            con.close()

    def get_daily_counts(self, platform: str, account_id: str) -> dict[str, int]:
        """Return action counts in the last 24 hours."""
        day_start = time.time() - 86400
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT action_type, COUNT(*) FROM actions WHERE platform = ? AND account_id = ? AND performed_at >= ? GROUP BY action_type",
                (platform.lower(), account_id, day_start),
            ).fetchall()
            return {r[0]: r[1] for r in rows}
        finally:
            con.close()

    def get_weekly_counts(self, platform: str, account_id: str) -> dict[str, int]:
        """Return action counts in the last 7 days."""
        week_start = time.time() - 604800
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT action_type, COUNT(*) FROM actions WHERE platform = ? AND account_id = ? AND performed_at >= ? GROUP BY action_type",
                (platform.lower(), account_id, week_start),
            ).fetchall()
            return {r[0]: r[1] for r in rows}
        finally:
            con.close()

    # ── internals ─────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self._db_path), timeout=10)
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA busy_timeout = 5000")
        return con

    def _ensure_schema(self) -> None:
        con = self._connect()
        try:
            con.executescript(_SCHEMA)
            con.commit()
        finally:
            con.close()
