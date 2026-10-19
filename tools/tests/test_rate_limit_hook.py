"""Tests for the rate_limit_hook script hook."""

from __future__ import annotations

import sqlite3
import time
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from framework.rate_limiter import SocialRateLimiter

import gcu.browser.hooks.rate_limit_hook as _hook_mod
from gcu.browser.hooks.rate_limit_hook import IDENTITY_JS, after_run, before_run

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_db(tmp_path):
    """Provide a temp rate limits DB path."""
    return tmp_path / "rate_limits.db"


def _make_module(rate_action=None):
    """Create a fake script module with optional RATE_LIMITED_ACTION."""
    mod = types.ModuleType("fake_script")
    if rate_action is not None:
        mod.RATE_LIMITED_ACTION = rate_action
    return mod


def _make_bsc(args=None, skill_dir=None):
    """Create a fake BrowserScriptContext."""
    bsc = MagicMock()
    bsc.args = dict(args or {})
    bsc.skill_dir = skill_dir or Path("/fake/skill/dir")
    bsc.tab_id = 1
    # Allow setting arbitrary attributes (for _rate_hook stashing)
    bsc.configure_mock(**{"_rate_hook": None})
    # Use a real dict for _rate_hook to avoid MagicMock auto-creation
    type(bsc)._rate_hook = property(
        lambda self: self.__dict__.get("_rate_hook_val"),
        lambda self, v: self.__dict__.__setitem__("_rate_hook_val", v),
    )
    return bsc


def _make_bridge(identity_result=None):
    """Create a fake bridge that returns identity_result from evaluate()."""
    bridge = MagicMock()
    if identity_result is not None:
        bridge.evaluate = AsyncMock(return_value={"result": identity_result})
    else:
        bridge.evaluate = AsyncMock(return_value={"result": {"status": "no_nav"}})
    return bridge


# ── before_run tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_rate_action_returns_none():
    """Module without RATE_LIMITED_ACTION → no-op."""
    mod = _make_module()
    result = await before_run(mod, _make_bsc(), _make_bridge())
    assert result is None


@pytest.mark.asyncio
async def test_rate_action_with_account_id_checks_limiter(tmp_db):
    """When account_id is in args, identity detection is skipped."""
    mod = _make_module({"platform": "linkedin", "action_type": "invite"})
    bsc = _make_bsc(args={"account_id": "https://www.linkedin.com/in/jdoe/"})
    bridge = _make_bridge()

    with patch.object(_hook_mod, "SocialRateLimiter", lambda: SocialRateLimiter(db_path=tmp_db)):
        result = await before_run(mod, bsc, bridge)

    assert result is None  # Allowed (no prior actions)
    bridge.evaluate.assert_not_called()  # No identity detection needed


@pytest.mark.asyncio
async def test_rate_action_without_account_id_detects_identity(tmp_db):
    """When account_id is missing, identity JS runs on the bridge."""
    mod = _make_module({"platform": "linkedin", "action_type": "invite"})
    bsc = _make_bsc()
    bridge = _make_bridge(
        identity_result={
            "status": "ok",
            "account_id": "https://www.linkedin.com/in/detected/",
        }
    )

    with patch.object(_hook_mod, "SocialRateLimiter", lambda: SocialRateLimiter(db_path=tmp_db)):
        result = await before_run(mod, bsc, bridge)

    assert result is None  # Allowed
    bridge.evaluate.assert_called_once()
    assert bsc.args["account_id"] == "https://www.linkedin.com/in/detected/"


@pytest.mark.asyncio
async def test_rate_action_blocked_returns_rate_limited(tmp_db):
    """When rate limit is exceeded, before_run returns a rate_limited dict."""
    mod = _make_module({"platform": "linkedin", "action_type": "invite"})
    bsc = _make_bsc(args={"account_id": "acct1"})
    bridge = _make_bridge()

    # Pre-fill 10 invites within the last hour to hit the hourly limit
    SocialRateLimiter(db_path=tmp_db)
    con = sqlite3.connect(str(tmp_db))
    now = time.time()
    for i in range(10):
        con.execute(
            "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
            ("linkedin", "acct1", "invite", now - 60 * (i + 1)),
        )
    con.commit()
    con.close()

    with patch.object(_hook_mod, "SocialRateLimiter", lambda: SocialRateLimiter(db_path=tmp_db)):
        result = await before_run(mod, bsc, bridge)

    assert result is not None
    assert result["status"] == "rate_limited"
    assert result["reason"] == "hourly_limit_reached"


@pytest.mark.asyncio
async def test_identity_detection_failure_falls_back_to_unknown(tmp_db):
    """When identity JS returns no_nav, account stays 'unknown'."""
    mod = _make_module({"platform": "linkedin", "action_type": "invite"})
    bsc = _make_bsc()  # No account_id
    bridge = _make_bridge(identity_result={"status": "no_nav"})

    with patch.object(_hook_mod, "SocialRateLimiter", lambda: SocialRateLimiter(db_path=tmp_db)):
        result = await before_run(mod, bsc, bridge)

    assert result is None  # Allowed
    assert bsc.args.get("account_id") is None  # Not injected


# ── after_run tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_after_run_no_rate_hook_is_noop():
    """Module without _rate_hook → result unchanged."""
    mod = _make_module()
    bsc = _make_bsc()
    result = {"status": "ok", "data": 123}
    out = await after_run(mod, bsc, _make_bridge(), result)
    assert out == result


@pytest.mark.asyncio
async def test_after_run_records_on_success(tmp_db):
    """After successful run, limiter.record() is called."""
    limiter = SocialRateLimiter(db_path=tmp_db)

    mod = _make_module({"platform": "x", "action_type": "reply"})
    bsc = _make_bsc()
    bsc._rate_hook = {
        "limiter": limiter,
        "platform": "x",
        "account_id": "@testuser",
        "actions": [{"platform": "x", "action_type": "reply"}],
        "success_statuses": {"ok", "sent"},
    }

    result = {"status": "sent", "tweet_url": "https://x.com/someone/status/123"}
    out = await after_run(mod, bsc, _make_bridge(), result)
    assert out == result

    # Verify record was written
    counts = limiter.get_daily_counts("x", "@testuser")
    assert counts.get("reply") == 1


@pytest.mark.asyncio
async def test_after_run_skips_non_success_status(tmp_db):
    """After non-success status, limiter.record() is NOT called."""
    limiter = SocialRateLimiter(db_path=tmp_db)

    mod = _make_module()
    bsc = _make_bsc()
    bsc._rate_hook = {
        "limiter": limiter,
        "platform": "x",
        "account_id": "@testuser",
        "actions": [{"platform": "x", "action_type": "reply"}],
        "success_statuses": {"ok", "sent"},
    }

    result = {"status": "error", "detail": "something failed"}
    out = await after_run(mod, bsc, _make_bridge(), result)
    assert out == result

    counts = limiter.get_daily_counts("x", "@testuser")
    assert counts.get("reply") is None


# ── IDENTITY_JS tests ──────────────────────────────────────────────


def test_identity_js_has_both_platforms():
    assert "linkedin" in IDENTITY_JS
    assert "x" in IDENTITY_JS


def test_identity_js_is_valid_string():
    for _platform, js in IDENTITY_JS.items():
        assert isinstance(js, str)
        assert len(js) > 50
        assert "status" in js
        assert "account_id" in js


# ── too_fast absorb tests (2026-07-21) ─────────────────────────────
# WHY: batch workers send several DMs in one session. If the hook bounces the
# configured min-delay ("too_fast") back to the agent, every second send costs
# a full LLM round-trip just to wait. The hook must WAIT OUT short pacing gaps
# in-process (respecting the limit, never bypassing it) and still bounce
# hourly/daily caps so the agent schedules a trigger instead of blocking.


@pytest.mark.asyncio
async def test_too_fast_short_gap_is_absorbed(tmp_db):
    """A small too_fast gap → hook sleeps it out and proceeds (returns None)."""
    mod = _make_module({"platform": "instagram", "action_type": "dm"})
    bsc = _make_bsc(args={"account_id": "@acct"})
    bridge = _make_bridge()

    # Last dm 43s ago with a 45s min delay → retry_after ≈ 2s (absorbable).
    SocialRateLimiter(db_path=tmp_db)  # create schema
    con = sqlite3.connect(str(tmp_db))
    now = time.time()
    con.execute(
        "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
        ("instagram", "@acct", "dm", now - 43),
    )
    con.commit()
    con.close()
    # Sanity: the schema above must match SocialRateLimiter's.
    assert SocialRateLimiter(db_path=tmp_db).check("instagram", "@acct", "dm")["reason"] == "too_fast"

    waits: list[float] = []

    async def fake_sleep(seconds):
        waits.append(seconds)
        # Emulate the gap elapsing: age the recorded action past the min delay.
        con = sqlite3.connect(str(tmp_db))
        con.execute("UPDATE actions SET performed_at = ?", (time.time() - 46,))
        con.commit()
        con.close()

    with (
        patch.object(_hook_mod, "SocialRateLimiter", lambda: SocialRateLimiter(db_path=tmp_db)),
        patch.object(_hook_mod.asyncio, "sleep", fake_sleep),
    ):
        result = await before_run(mod, bsc, bridge)

    assert result is None  # absorbed, script proceeds
    assert len(waits) == 1 and 1.0 <= waits[0] <= _hook_mod._TOO_FAST_ABSORB_S + 1.0


@pytest.mark.asyncio
async def test_too_fast_long_gap_still_bounces(tmp_db):
    """A too_fast gap ABOVE the absorb ceiling → rate_limited, no sleep."""
    import framework.rate_limiter as _rl

    mod = _make_module({"platform": "instagram", "action_type": "dm"})
    bsc = _make_bsc(args={"account_id": "@acct"})
    bridge = _make_bridge()

    SocialRateLimiter(db_path=tmp_db)  # create schema
    con = sqlite3.connect(str(tmp_db))
    con.execute(
        "INSERT INTO actions (platform, account_id, action_type, performed_at) VALUES (?, ?, ?, ?)",
        ("instagram", "@acct", "dm", time.time() - 10),
    )
    con.commit()
    con.close()

    slept = AsyncMock()
    with (
        patch.object(_hook_mod, "SocialRateLimiter", lambda: SocialRateLimiter(db_path=tmp_db)),
        patch.object(_rl, "_min_delay", lambda p, a: 300.0),
        patch.object(_hook_mod.asyncio, "sleep", slept),
    ):
        result = await before_run(mod, bsc, bridge)

    assert result is not None and result["status"] == "rate_limited"
    assert result["reason"] == "too_fast"
    slept.assert_not_awaited()
