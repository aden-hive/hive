"""A handle-emitting tool and the tools that redeem its handles must ship together.

Several terminal tools return a deferred-result handle instead of the result
itself:

* ``terminal_exec`` → ``output_handle`` when output overflows
  ``max_output_kb``; redeemed by ``terminal_output_get``.
* ``terminal_job_start`` → ``job_id``; redeemed by ``terminal_job_logs`` /
  ``terminal_job_manage``.

Splitting a handle from its redeemer across tool tiers is the bug this file
exists to prevent: the agent receives a handle-shaped string it has no tool
to cash, and the failure surfaces as truncated output (or a stranded job)
rather than an error. The desktop runtime burned >20 minutes of a production
session on exactly this before adding the same invariant there. Pruning a
redeemer for token cost is a false economy — the handle it redeems is dead
weight without it.

The OTHER deferred path — a slow command — is deliberately not modelled
here: the agent loop dispatches ``terminal_exec`` via
``LoopConfig.background_tools`` and the agent collects through the
synthetic ``collect_result``, which bypasses the category allowlist
entirely. ``test_terminal_exec_is_dispatched_in_background`` pins that
arrangement.
"""

from __future__ import annotations

import pytest

from framework.agents.queen import queen_tools_defaults as qtd

# Handle-emitting tool -> tools required to redeem what it hands back.
_REDEEMERS: dict[str, set[str]] = {
    "terminal_exec": {"terminal_output_get"},
    "terminal_job_start": {"terminal_job_logs", "terminal_job_manage"},
}


def _categories_containing(tool: str) -> list[str]:
    return [name for name, tools in qtd._TOOL_CATEGORIES.items() if tool in tools]


@pytest.mark.parametrize("emitter", sorted(_REDEEMERS))
def test_emitter_categories_ship_their_redeemers(emitter: str):
    """No category may offer a handle-emitting tool without its redeemers."""
    categories = _categories_containing(emitter)
    assert categories, f"{emitter} vanished from the category table"

    for category in categories:
        tools = set(qtd._TOOL_CATEGORIES[category])
        missing = _REDEEMERS[emitter] - tools
        assert not missing, (
            f"category {category!r} offers {emitter} but not {sorted(missing)} — "
            f"an agent in this tier receives handles it cannot redeem"
        )


@pytest.mark.parametrize("emitter", sorted(_REDEEMERS))
def test_always_enabled_tiers_ship_their_redeemers(emitter: str):
    """The queen and worker keep-sets are the tiers that actually ship.

    Category hygiene above is necessary but not sufficient — what reaches a
    live agent is the expansion of the always-enabled sets, so assert on
    those directly.
    """
    for label, keep_set in (
        ("queen", qtd.ALWAYS_ENABLED_CATEGORIES),
        ("worker", qtd.WORKER_ALWAYS_ENABLED_CATEGORIES),
    ):
        enabled: set[str] = set()
        for category in keep_set:
            enabled.update(qtd._TOOL_CATEGORIES.get(category, ()))
        if emitter not in enabled:
            continue  # this tier doesn't hand out the handle; nothing to redeem
        missing = _REDEEMERS[emitter] - enabled
        assert not missing, (
            f"{label} always-enabled set has {emitter} but not {sorted(missing)}"
        )


def test_terminal_exec_is_dispatched_in_background():
    """Slow commands must have somewhere to go.

    Without background dispatch, a long command blocks the loop until the
    shared tool timeout kills it (resetting the MCP connection) with no way
    to recover the result. The grace window keeps the fast path free: quick
    commands return inline and never mint a handle.
    """
    from framework.agent_loop.internals.types import LoopConfig

    cfg = LoopConfig()
    assert "terminal_exec" in cfg.background_tools
    # collect_result is only attached when background_tools is non-empty.
    assert cfg.background_tools, "collect_result would not be offered to the agent"
    assert cfg.background_tool_grace_seconds > 0, (
        "grace window disabled — every quick command would pay a full "
        "collect_result model turn"
    )
