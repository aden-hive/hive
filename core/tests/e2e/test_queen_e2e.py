"""End-to-end queen suite: every spec in ``specs.SPECS`` against a live model.

Run all:        cd core && uv run pytest tests/e2e -m live -v
Some scenarios: ... -k "bugfix_with_tests or log_forensics"
"""

from __future__ import annotations

import pytest

from tests.e2e.specs import SPECS, Spec

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


@pytest.mark.parametrize("spec", SPECS, ids=[s.id for s in SPECS])
async def test_spec(spec: Spec, run_queen) -> None:
    run = await run_queen(list(spec.turns), queen_id=spec.queen_id, seed=spec.seed, resume=spec.resume)
    assert len(run.turns) == len(spec.turns), run.summary()
    spec.check(run)
