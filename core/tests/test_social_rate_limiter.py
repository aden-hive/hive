"""Tests for framework.rate_limiter (SocialRateLimiter)."""

from __future__ import annotations

import os
import sqlite3
import time
from unittest import mock

import pytest

from framework.rate_limiter import SocialRateLimiter, _min_delay, _resolve_limit


@pytest.fixture()
def limiter(tmp_path):
    db = tmp_path / "rate_limits.db"
    return SocialRateLimiter(db_path=db)


# ── Schema bootstrap ────────────────────────────────────────────────


def test_creates_db_and_table(tmp_path):
    db = tmp_path / "sub" / "rate_limits.db"
    SocialRateLimiter(db_path=db)
    assert db.exists()
    con = sqlite3.connect(str(db))
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "actions" in tables
    con.close()


# ── check() — basic allowed path ────────────────────────────────────


def test_check_allowed_when_empty(limiter):
    result = limiter.check("linkedin", "user1", "invite")
    assert result["allowed"] is True
    assert result["daily_count"] == 0


def test_check_allowed_after_some_records(limiter):
    for i in range(5):
        limiter.record("linkedin", "user1", "invite", target_id=f"target_{i}")
    # Need to bypass min_delay for count test — insert with past timestamps
    con = sqlite3.connect(str(limiter._db_path))
    con.execute("DELETE FROM actions")
    now = time.time()
    for i in range(5):
        con.execute(
            "INSERT INTO actions (platform, account_id, action_type, target_id, performed_at) VALUES (?, ?, ?, ?, ?)",
            ("linkedin", "user1", "invite", f"t{i}", now - 60 * (i + 1)),
        )
    con.commit()
    con.close()
    result = limiter.check("linkedin", "user1", "invite")
    assert result["allowed"] is True
    assert result["daily_count"] == 5


# ── check() — daily limit ───────────────────────────────────────────


def test_daily_limit_blocks(limiter):
    con = sqlite3.connect(str(limiter._db_path))
    now = time.time()
    # Spread actions across multiple hours so hourly limit doesn't trip first
    for i in range(50):
        con.execute(
            "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
            ("linkedin", "acct1", "invite", now - 900 * (i + 1)),
        )
    con.commit()
    con.close()

    result = limiter.check("linkedin", "acct1", "invite")
    assert result["allowed"] is False
    assert result["reason"] == "daily_limit_reached"
    assert result["halt_campaign"] is True
    assert result["daily_count"] == 50
    assert result["daily_limit"] == 50


def test_daily_limit_different_accounts_independent(limiter):
    con = sqlite3.connect(str(limiter._db_path))
    now = time.time()
    for i in range(50):
        con.execute(
            "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
            ("linkedin", "acct_a", "invite", now - 900 * (i + 1)),
        )
    con.commit()
    con.close()

    blocked = limiter.check("linkedin", "acct_a", "invite")
    assert blocked["allowed"] is False

    allowed = limiter.check("linkedin", "acct_b", "invite")
    assert allowed["allowed"] is True


# ── check() — weekly limit ──────────────────────────────────────────


def test_weekly_limit_blocks(limiter):
    con = sqlite3.connect(str(limiter._db_path))
    now = time.time()
    # Place 200 invites between 2-7 days ago (outside the 24h daily window)
    # so the hourly and daily checks pass but the weekly check catches them.
    base = now - 2 * 86400  # 2 days ago
    for i in range(200):
        con.execute(
            "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
            ("linkedin", "user1", "invite", base - 1800 * i),
        )
    con.commit()
    con.close()

    result = limiter.check("linkedin", "user1", "invite")
    assert result["allowed"] is False
    assert result["reason"] == "weekly_limit_reached"
    assert result["weekly_count"] == 200
    assert result["weekly_limit"] == 200


def test_no_weekly_limit_for_actions_without_one(limiter):
    con = sqlite3.connect(str(limiter._db_path))
    now = time.time()
    # Insert 19 messages (under daily limit of 60), spread across hours
    for i in range(19):
        con.execute(
            "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
            ("linkedin", "user1", "message", now - 3600 * (i + 1)),
        )
    con.commit()
    con.close()

    result = limiter.check("linkedin", "user1", "message")
    assert result["allowed"] is True
    assert result["weekly_count"] is None
    assert result["weekly_limit"] is None


# ── check() — min delay ─────────────────────────────────────────────


def test_min_delay_blocks_too_fast(limiter):
    con = sqlite3.connect(str(limiter._db_path))
    con.execute(
        "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
        ("linkedin", "user1", "invite", time.time() - 5),
    )
    con.commit()
    con.close()

    result = limiter.check("linkedin", "user1", "invite")
    assert result["allowed"] is False
    assert result["reason"] == "too_fast"
    assert result["halt_campaign"] is False
    assert result["retry_after_seconds"] > 0
    assert result["retry_after_seconds"] <= 25  # 30s delay - 5s elapsed


def test_min_delay_allows_after_enough_time(limiter):
    con = sqlite3.connect(str(limiter._db_path))
    con.execute(
        "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
        ("linkedin", "user1", "invite", time.time() - 31),
    )
    con.commit()
    con.close()

    result = limiter.check("linkedin", "user1", "invite")
    assert result["allowed"] is True


# ── record() ────────────────────────────────────────────────────────


def test_record_inserts_action(limiter):
    limiter.record("x", "@handle", "reply", target_id="https://x.com/post/123", session_id="s1")

    con = sqlite3.connect(str(limiter._db_path))
    row = con.execute("SELECT platform, account_id, action_type, target_id, session_id FROM actions").fetchone()
    con.close()
    assert row == ("x", "@handle", "reply", "https://x.com/post/123", "s1")


def test_record_normalizes_platform_and_action(limiter):
    limiter.record("LinkedIn", "@user", "INVITE")

    con = sqlite3.connect(str(limiter._db_path))
    row = con.execute("SELECT platform, action_type FROM actions").fetchone()
    con.close()
    assert row == ("linkedin", "invite")


# ── env var overrides ────────────────────────────────────────────────


def test_env_var_raises_limit(limiter):
    with mock.patch.dict(os.environ, {"HIVE_RATE_LINKEDIN_INVITE_DAILY": "20"}):
        result = _resolve_limit("linkedin", "invite", "daily")
    assert result == 20


def test_env_var_clamped_to_ceiling(limiter):
    with mock.patch.dict(os.environ, {"HIVE_RATE_LINKEDIN_INVITE_DAILY": "999"}):
        result = _resolve_limit("linkedin", "invite", "daily")
    assert result == 125  # daily_max ceiling


def test_env_var_invalid_falls_back_to_default(limiter):
    with mock.patch.dict(os.environ, {"HIVE_RATE_LINKEDIN_INVITE_DAILY": "not_a_number"}):
        result = _resolve_limit("linkedin", "invite", "daily")
    assert result == 50  # daily_default


def test_env_var_weekly_clamped(limiter):
    with mock.patch.dict(os.environ, {"HIVE_RATE_LINKEDIN_INVITE_WEEKLY": "999"}):
        result = _resolve_limit("linkedin", "invite", "weekly")
    assert result == 500  # weekly_max ceiling


# ── get_daily_counts / get_weekly_counts ─────────────────────────────


def test_get_daily_counts(limiter):
    con = sqlite3.connect(str(limiter._db_path))
    now = time.time()
    con.execute(
        "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
        ("linkedin", "u1", "invite", now - 100),
    )
    con.execute(
        "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
        ("linkedin", "u1", "invite", now - 200),
    )
    con.execute(
        "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
        ("linkedin", "u1", "message", now - 300),
    )
    # Old action (>24h ago) should not count
    con.execute(
        "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
        ("linkedin", "u1", "invite", now - 90000),
    )
    con.commit()
    con.close()

    counts = limiter.get_daily_counts("linkedin", "u1")
    assert counts == {"invite": 2, "message": 1}


def test_get_weekly_counts(limiter):
    con = sqlite3.connect(str(limiter._db_path))
    now = time.time()
    for i in range(10):
        con.execute(
            "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
            ("x", "@h", "reply", now - 3600 * (i + 1)),
        )
    # Old action (>7d ago) should not count
    con.execute(
        "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
        ("x", "@h", "reply", now - 700000),
    )
    con.commit()
    con.close()

    counts = limiter.get_weekly_counts("x", "@h")
    assert counts == {"reply": 10}


# ── unknown action type ─────────────────────────────────────────────


def test_unknown_action_always_allowed(limiter):
    result = limiter.check("tiktok", "user1", "dance")
    assert result["allowed"] is True
    assert result["daily_limit"] is None


# ── cross-platform isolation ────────────────────────────────────────


def test_cross_platform_counts_isolated(limiter):
    con = sqlite3.connect(str(limiter._db_path))
    now = time.time()
    for i in range(15):
        con.execute(
            "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
            ("linkedin", "user1", "comment", now - 60 * (i + 1)),
        )
    con.commit()
    con.close()

    blocked = limiter.check("linkedin", "user1", "comment")
    assert blocked["allowed"] is False

    # Same account_id on X should not be blocked
    allowed = limiter.check("x", "user1", "reply")
    assert allowed["allowed"] is True


# ── _min_delay helper ────────────────────────────────────────────────


def test_min_delay_values():
    assert _min_delay("linkedin", "invite") == 30.0
    assert _min_delay("linkedin", "message") == 15.0
    assert _min_delay("x", "reply") == 30.0
    assert _min_delay("x", "dm") == 20.0
    assert _min_delay("x", "post") == 60.0
    assert _min_delay("unknown", "action") == 0.0
