"""``_ensure_context`` must not silently hand back a differently-bound browser.

A session's tab group lives in exactly ONE Chrome profile, fixed at cold-start.
The bug these tests pin: ``_ensure_context`` computed ``bp`` and then early-
returned the existing context without ever comparing it, so an agent calling
``open --browser-profile product-testing`` on an already-bound session got a tab
in the OLD profile back with ``ok: True``. It then acted on the wrong logged-in
account (observed 2026-08-03: work intended for a product-testing Instagram
session ran against the default profile's account for ~20 minutes).

Silence is the defect, so the mismatch case asserts a raise. The remaining tests
guard the other half — a conflict check that fires on the normal
no-``browser_profile`` path would break every tab-scoped command.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import gcu.browser.tools.lifecycle as lc
from gcu.browser.bridge import BridgeError


@pytest.fixture(autouse=True)
def _clean_contexts(monkeypatch):
    """Isolate the module-level context registry and never touch ~/.hive."""
    lc._contexts.clear()
    monkeypatch.setattr(lc, "_persist_contexts", lambda: None)
    yield
    lc._contexts.clear()


def _bound(label: str = "nimble-cyan-tapir") -> dict:
    """An established context already bound to a concrete Chrome profile."""
    return {"groupId": 7, "activeTabId": 70, "name": "bound", "browser_profile": label, "tabs": {70}}


def _bridge(created_label: str = "product-testing") -> MagicMock:
    b = MagicMock()
    b.is_connected = True
    b.create_context = AsyncMock(return_value={"groupId": 9, "tabId": 90, "browser_profile": created_label})
    return b


async def test_explicit_mismatch_raises_instead_of_returning_wrong_profile():
    """The bug: this used to return the nimble-cyan-tapir context with ok:True."""
    lc._contexts["s1"] = _bound("nimble-cyan-tapir")

    with pytest.raises(BridgeError) as exc:
        await lc._ensure_context(_bridge(), "s1", None, "product-testing")

    assert exc.value.code == "browser_profile_conflict"
    assert exc.value.retryable is False
    msg = str(exc.value)
    # The message must name both profiles and the way out — an agent that can't
    # tell which browser it landed in can't recover on its own.
    assert "nimble-cyan-tapir" in msg and "product-testing" in msg
    assert "hive-browser stop" in msg


async def test_matching_explicit_profile_is_not_a_conflict():
    """Re-asserting the profile a session is already bound to is legitimate."""
    ctx = _bound("product-testing")
    lc._contexts["s1"] = ctx

    name, got, created = await lc._ensure_context(_bridge(), "s1", None, "product-testing")

    assert (name, got, created) == ("s1", ctx, False)


async def test_omitted_profile_reuses_binding():
    """The common path: tab-scoped commands pass no profile and must not raise."""
    ctx = _bound("nimble-cyan-tapir")
    lc._contexts["s1"] = ctx

    _, got, created = await lc._ensure_context(_bridge(), "s1", None, None)

    assert got is ctx and created is False


async def test_default_request_means_dont_care():
    """ "default" is the caller declining to choose, not a claim about which one."""
    ctx = _bound("nimble-cyan-tapir")
    lc._contexts["s1"] = ctx

    _, got, created = await lc._ensure_context(_bridge(), "s1", None, "default")

    assert got is ctx and created is False


async def test_unresolved_stored_label_cannot_be_proven_wrong():
    """An older persisted entry stores "default"; we don't know which Chrome that
    is, so raising would be a false alarm on a context that may well be correct."""
    ctx = _bound("default")
    lc._contexts["s1"] = ctx

    _, got, created = await lc._ensure_context(_bridge(), "s1", None, "product-testing")

    assert got is ctx and created is False


async def test_cold_start_still_binds_to_the_requested_profile():
    """No existing context → the flag works exactly as before the fix."""
    bridge = _bridge("product-testing")

    _, ctx, created = await lc._ensure_context(bridge, "fresh", None, "product-testing")

    assert created is True
    assert ctx["browser_profile"] == "product-testing"
    assert bridge.create_context.await_args.kwargs["browser_profile"] == "product-testing"
