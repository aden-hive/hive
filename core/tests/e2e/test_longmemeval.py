"""LongMemEval-S as an end-to-end test of Hive's memory (see ``longmemeval.py``).

One test per question; the pass rate is the benchmark accuracy, and a
per-type report is printed at the end of the run and saved next to the
per-question results.

Default sample (12, stratified):  cd core && uv run pytest tests/e2e/test_longmemeval.py -m live
Full benchmark, 4 at a time:      HIVE_LME_QUESTIONS=all uv run pytest tests/e2e/test_longmemeval.py -m live -n 4
Specific questions:               HIVE_LME_QUESTIONS=e47becba,gpt4_2655b836 uv run pytest ...
Without timeline extraction:      HIVE_LME_TIMELINE=0 ...
"""

from __future__ import annotations

import os

import pytest

from tests.e2e import conftest as harness, longmemeval as lme

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


def _live_selected(config: pytest.Config) -> bool:
    expr = config.option.markexpr or ""
    return "live" in expr and "not live" not in expr


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "question_id" not in metafunc.fixturenames:
        return
    if not _live_selected(metafunc.config):
        # Collected but deselected by the default ``-m 'not live'``: don't
        # fetch or read 277 MB of dataset just to throw the items away.
        metafunc.parametrize("question_id", ["not-collected-without-live"])
        return
    index = {q["question_id"]: q for q in lme.load_index()}
    ids = lme.select(list(index.values()), os.environ.get("HIVE_LME_QUESTIONS", "12"))
    metafunc.parametrize("question_id", ids, ids=[f"{index[q]['question_type']}:{q}" for q in ids])


async def test_longmemeval(question_id: str, run_queen, hive_home, monkeypatch) -> None:
    item = lme.load_question(question_id)
    session_map = lme.seed_haystack(hive_home, item)
    if os.environ.get("HIVE_LME_TIMELINE", "1") != "0":
        await lme.build_timelines(
            hive_home,
            api_base=harness.API_BASE,
            api_key=harness.API_KEY,
            model=os.environ.get("HIVE_LME_TIMELINE_MODEL", harness.MODEL),
        )
    lme.freeze_clock(monkeypatch, lme.parse_date(item["question_date"]))

    try:
        run = await run_queen([item["question"]], queen_id=lme.QUEEN_ID)
        verdict = await lme.judge(
            item,
            run.text,
            api_base=harness.API_BASE,
            api_key=harness.API_KEY,
            model=os.environ.get("HIVE_LME_JUDGE_MODEL", harness.MODEL),
        )
    except BaseException as exc:  # incl. pytest.fail on a turn timeout
        # Count it as a miss in the report instead of silently dropping it.
        lme.record_error(item, exc)
        raise
    result = lme.record(item, run, verdict, session_map=session_map)

    assert verdict.correct, (
        f"[{item['question_type']}] {item['question']}\n"
        f"  expected: {item['answer']}\n"
        f"  got:      {run.text[:600]!r}\n"
        f"  searched={result['searched']} evidence_retrieved={result['evidence_retrieved']} tools={result['tools']}"
    )
