"""Unit tests for the per-spawn LoopConfig override helper.

The helper is the choke point that turns queen-supplied overrides into a
real ``LoopConfig`` for the worker's ``AgentLoop``. We test it directly
because mistakes here silently change every spawned worker's budget,
which is hard to catch in integration tests.
"""

from __future__ import annotations

import pytest

from framework.agent_loop.agent_loop import LoopConfig
from framework.host.colony_runtime import (
    _ALLOWED_WORKER_LOOP_OVERRIDES,
    _build_worker_loop_config,
)

# Worker profile baked into _build_worker_loop_config (mirrors
# DEFAULT_LOOP_CONFIG): 3 work iterations + 1 grace iteration, tighter
# tool-call budget than the queen (30 calls — sized for a 5-10 unit
# batch task processed in-turn — hard stop at 3x = 90).
_WORKER_MAX_ITERATIONS = 3
_WORKER_GRACE_ITERATIONS = 1
_WORKER_BUDGET = 30
_WORKER_HARD_MULTIPLE = 3
# Cumulative (lifetime) tool-call cap across all of a worker's turns.
_WORKER_LIFETIME_BUDGET = 200


def test_no_overrides_returns_worker_profile() -> None:
    cfg = _build_worker_loop_config({})
    default = LoopConfig()
    # Worker iteration ceiling comes from the worker profile (3 + 1),
    # not LoopConfig's bare default (50 + 0).
    assert cfg.max_iterations == _WORKER_MAX_ITERATIONS
    assert cfg.grace_iterations == _WORKER_GRACE_ITERATIONS
    assert cfg.max_context_tokens == default.max_context_tokens
    # Tool-call budget comes from the worker profile, not the bare default.
    assert cfg.tool_call_budget == _WORKER_BUDGET
    assert cfg.tool_call_hard_multiple == _WORKER_HARD_MULTIPLE
    # Lifetime cap comes from the worker profile (default is 0 = off).
    assert cfg.tool_call_lifetime_budget == _WORKER_LIFETIME_BUDGET
    assert default.tool_call_lifetime_budget == 0


def test_max_iterations_override() -> None:
    cfg = _build_worker_loop_config({"max_iterations": 12})
    assert cfg.max_iterations == 12
    # Other fields untouched.
    assert cfg.max_context_tokens == LoopConfig().max_context_tokens


def test_tool_call_budget_zero_means_unlimited() -> None:
    """Boundary: 0 is the documented "unlimited" sentinel and must be allowed."""
    cfg = _build_worker_loop_config({"tool_call_budget": 0})
    assert cfg.tool_call_budget == 0


def test_tool_call_lifetime_budget_override() -> None:
    cfg = _build_worker_loop_config({"tool_call_lifetime_budget": 40})
    assert cfg.tool_call_lifetime_budget == 40


def test_tool_call_lifetime_budget_zero_means_disabled() -> None:
    """Boundary: 0 disables the cumulative cap and must be allowed."""
    cfg = _build_worker_loop_config({"tool_call_lifetime_budget": 0})
    assert cfg.tool_call_lifetime_budget == 0


def test_tool_call_hard_multiple_is_not_queen_tunable() -> None:
    """The worker's hard-stop multiple stays framework-controlled at 2."""
    cfg = _build_worker_loop_config({"tool_call_hard_multiple": 9})
    assert cfg.tool_call_hard_multiple == _WORKER_HARD_MULTIPLE


def test_max_context_tokens_override() -> None:
    cfg = _build_worker_loop_config({"max_context_tokens": 64_000})
    assert cfg.max_context_tokens == 64_000


def test_combined_overrides() -> None:
    cfg = _build_worker_loop_config(
        {
            "max_iterations": 8,
            "tool_call_budget": 5,
            "max_context_tokens": 12_000,
        }
    )
    assert cfg.max_iterations == 8
    assert cfg.tool_call_budget == 5
    assert cfg.max_context_tokens == 12_000


def test_unknown_keys_silently_dropped() -> None:
    """Typos shouldn't crash the spawn — drop, log, continue."""
    cfg = _build_worker_loop_config({"max_iterations": 7, "judge_every_n_turns": 99, "garbage_field": "x"})
    assert cfg.max_iterations == 7
    # Framework-controlled field stays at default — override IGNORED.
    assert cfg.judge_every_n_turns == LoopConfig().judge_every_n_turns


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_iterations", 0),
        ("max_iterations", 1001),
        ("max_iterations", -5),
        ("tool_call_budget", -1),
        ("tool_call_budget", 201),
        ("tool_call_lifetime_budget", -1),
        ("tool_call_lifetime_budget", 2001),
        ("max_context_tokens", 999),
        ("max_context_tokens", 1_000_001),
    ],
)
def test_out_of_range_raises(field: str, value: int) -> None:
    with pytest.raises(ValueError, match="out of range"):
        _build_worker_loop_config({field: value})


def test_non_int_raises() -> None:
    with pytest.raises(ValueError, match="must be int"):
        _build_worker_loop_config({"max_iterations": "100"})


def test_grace_iterations_override() -> None:
    cfg = _build_worker_loop_config({"grace_iterations": 0})
    assert cfg.grace_iterations == 0  # opt-out: queen wants no grace
    cfg = _build_worker_loop_config({"grace_iterations": 2})
    assert cfg.grace_iterations == 2


def test_allowed_set_is_the_documented_fields() -> None:
    """Lock the queen-tunable surface — adding another override is a deliberate change."""
    assert _ALLOWED_WORKER_LOOP_OVERRIDES == frozenset(
        {
            "max_iterations",
            "grace_iterations",
            "tool_call_budget",
            "tool_call_lifetime_budget",
            "max_context_tokens",
        }
    )
