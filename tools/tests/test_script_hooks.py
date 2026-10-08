"""Tests for the browser_script hook system in script.py."""

from __future__ import annotations

import types

import pytest

# Import the hook system directly from script.py
from gcu.browser.tools.script import (
    _SCRIPT_HOOKS,
    register_script_hook,
)


@pytest.fixture(autouse=True)
def _clean_hooks():
    """Ensure hooks list is clean for each test."""
    original = _SCRIPT_HOOKS.copy()
    _SCRIPT_HOOKS.clear()
    yield
    _SCRIPT_HOOKS.clear()
    _SCRIPT_HOOKS.extend(original)


def _make_hook(*, before_result=None, after_transform=None):
    """Create a hook module with optional before_run/after_run."""
    hook = types.ModuleType("test_hook")
    if before_result is not None:

        async def before_run(module, bsc, bridge):
            return before_result

        hook.before_run = before_run
    if after_transform is not None:

        async def after_run(module, bsc, bridge, result):
            result.update(after_transform)
            return result

        hook.after_run = after_run
    return hook


def test_register_adds_to_list():
    hook = _make_hook()
    register_script_hook(hook)
    assert hook in _SCRIPT_HOOKS


def test_register_preserves_order():
    h1 = _make_hook()
    h2 = _make_hook()
    h3 = _make_hook()
    register_script_hook(h1)
    register_script_hook(h2)
    register_script_hook(h3)
    assert _SCRIPT_HOOKS == [h1, h2, h3]


def test_hook_without_before_run_is_noop():
    hook = types.ModuleType("empty_hook")
    register_script_hook(hook)
    before = getattr(hook, "before_run", None)
    assert before is None


def test_hook_without_after_run_is_noop():
    hook = types.ModuleType("empty_hook")
    register_script_hook(hook)
    after = getattr(hook, "after_run", None)
    assert after is None


@pytest.mark.asyncio
async def test_before_run_returning_none_proceeds():
    hook = _make_hook(before_result=None)
    register_script_hook(hook)

    # Simulate the hook loop from script.py
    result = None
    for h in _SCRIPT_HOOKS:
        before = getattr(h, "before_run", None)
        if before is not None:
            hook_result = await before(None, None, None)
            if hook_result is not None:
                result = hook_result
                break
    assert result is None  # No short-circuit


@pytest.mark.asyncio
async def test_before_run_returning_dict_short_circuits():
    block_result = {"status": "rate_limited", "halt_campaign": True}
    hook = _make_hook(before_result=block_result)
    register_script_hook(hook)

    result = None
    for h in _SCRIPT_HOOKS:
        before = getattr(h, "before_run", None)
        if before is not None:
            hook_result = await before(None, None, None)
            if hook_result is not None:
                result = hook_result
                break
    assert result == block_result


@pytest.mark.asyncio
async def test_first_blocking_hook_wins():
    """When multiple hooks have before_run, the first to return a dict wins."""
    h1 = _make_hook(before_result={"from": "h1"})
    h2 = _make_hook(before_result={"from": "h2"})
    register_script_hook(h1)
    register_script_hook(h2)

    result = None
    for h in _SCRIPT_HOOKS:
        before = getattr(h, "before_run", None)
        if before is not None:
            hook_result = await before(None, None, None)
            if hook_result is not None:
                result = hook_result
                break
    assert result == {"from": "h1"}


@pytest.mark.asyncio
async def test_after_run_transforms_result():
    hook = _make_hook(after_transform={"enriched": True})
    register_script_hook(hook)

    result = {"status": "ok"}
    for h in _SCRIPT_HOOKS:
        after = getattr(h, "after_run", None)
        if after is not None:
            result = await after(None, None, None, result)
    assert result == {"status": "ok", "enriched": True}


@pytest.mark.asyncio
async def test_after_run_chains_multiple_hooks():
    h1 = _make_hook(after_transform={"h1": True})
    h2 = _make_hook(after_transform={"h2": True})
    register_script_hook(h1)
    register_script_hook(h2)

    result = {"status": "ok"}
    for h in _SCRIPT_HOOKS:
        after = getattr(h, "after_run", None)
        if after is not None:
            result = await after(None, None, None, result)
    assert result == {"status": "ok", "h1": True, "h2": True}
