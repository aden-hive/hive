"""Tests for the nudge-vs-escalate classifier (framework.sentinel.classifier)."""

from __future__ import annotations

import pytest

from framework.sentinel.classifier import (
    VERDICT_CONTINUE,
    VERDICT_NEEDS_HUMAN,
    ParkContext,
    classify_park,
    format_running_workers,
)


class _Resp:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    def __init__(self, content: str | None = None, raise_exc: bool = False) -> None:
        self._content = content
        self._raise = raise_exc

    async def acomplete(self, **kwargs):
        if self._raise:
            raise RuntimeError("llm down")
        return _Resp(self._content)


def _ctx() -> ParkContext:
    return ParkContext(
        park_reason="turn_done",
        goal="enrich 1000 leads",
        open_tasks=["enrich batch 3"],
        last_assistant_text="I've done 200. Shall I continue?",
    )


@pytest.mark.asyncio
async def test_needs_human_verdict():
    llm = _FakeLLM('{"verdict": "needs_human", "reason": "login expired"}')
    v = await classify_park(_ctx(), llm)
    assert v.verdict == VERDICT_NEEDS_HUMAN
    assert v.needs_human is True


@pytest.mark.asyncio
async def test_continue_verdict():
    llm = _FakeLLM('{"verdict": "continue", "reason": "just a checkpoint"}')
    v = await classify_park(_ctx(), llm)
    assert v.verdict == VERDICT_CONTINUE
    assert v.needs_human is False


@pytest.mark.asyncio
async def test_no_llm_defaults_continue():
    v = await classify_park(_ctx(), None)
    assert v.verdict == VERDICT_CONTINUE


@pytest.mark.asyncio
async def test_bad_json_defaults_continue():
    v = await classify_park(_ctx(), _FakeLLM("not json at all"))
    assert v.verdict == VERDICT_CONTINUE


@pytest.mark.asyncio
async def test_llm_exception_defaults_continue():
    v = await classify_park(_ctx(), _FakeLLM(raise_exc=True))
    assert v.verdict == VERDICT_CONTINUE


@pytest.mark.asyncio
async def test_unknown_verdict_defaults_continue():
    v = await classify_park(_ctx(), _FakeLLM('{"verdict": "maybe"}'))
    assert v.verdict == VERDICT_CONTINUE


class _CapturingLLM:
    """Records the prompt/system it was asked, returns a fixed verdict."""

    def __init__(self) -> None:
        self.user_prompt = ""
        self.system = ""

    async def acomplete(self, *, messages, system, **kwargs):
        self.user_prompt = messages[0]["content"]
        self.system = system
        return _Resp('{"verdict": "needs_human", "reason": "user asked to wait"}')


@pytest.mark.asyncio
async def test_recent_user_message_reaches_classifier():
    # The user's steer ("stop / wait") is the authoritative intent signal; it
    # must be delivered to the classifier, or sentinel can't honor it and will
    # nudge the queen to resume against an explicit stop.
    ctx = _ctx()
    ctx.recent_user_text = "Stop here and wait for me, I want to review before you continue."
    llm = _CapturingLLM()
    await classify_park(ctx, llm)
    assert "wait for me" in llm.user_prompt
    assert "most recent message" in llm.user_prompt.lower()
    # And the system prompt must license overriding standing-authority on a stop.
    assert "stop" in llm.system.lower() and "needs_human" in llm.system


@pytest.mark.asyncio
async def test_no_user_message_omits_section():
    # When the last turn was the queen's, the user section is absent (no empty
    # block that could read as a stray instruction).
    llm = _CapturingLLM()
    await classify_park(_ctx(), llm)  # _ctx() leaves recent_user_text empty
    assert "most recent message" not in llm.user_prompt.lower()


@pytest.mark.asyncio
async def test_running_workers_reach_classifier():
    # A queen idling while its fan-out is still running isn't stalled — it's
    # waiting. The classifier must see the live workers (and be licensed to
    # answer "continue"), or it can misread a healthy wait as a blocker.
    ctx = _ctx()
    ctx.running_workers = [{"worker_id": "w1", "status": "running", "task": "scrape influencer A", "elapsed_seconds": 750}]
    llm = _CapturingLLM()
    await classify_park(ctx, llm)
    assert "w1" in llm.user_prompt and "scrape influencer A" in llm.user_prompt
    assert "still running" in llm.user_prompt.lower()
    # Elapsed time is surfaced so the classifier can weigh a long-stuck worker.
    assert "12m" in llm.user_prompt
    # System prompt must license "continue" while workers run.
    assert "still running" in llm.system.lower() and "continue" in llm.system.lower()


@pytest.mark.parametrize(
    "elapsed,expected",
    [(45, "45s"), (90, "1m"), (750, "12m"), (3600, "1h"), (7380, "2h3m")],
)
def test_format_running_workers_renders_elapsed(elapsed, expected):
    # Elapsed time must read at a glance (s / m / h+m), so a human (or the
    # classifier) can spot a worker stuck far longer than its peers.
    out = format_running_workers([{"worker_id": "w1", "status": "running", "elapsed_seconds": elapsed}])
    assert f"[running, {expected}]" in out


def test_format_running_workers_omits_elapsed_when_absent():
    # No timing data → bare status, no stray "0s" that implies just-started.
    out = format_running_workers([{"worker_id": "w1", "status": "running"}])
    assert "[running]" in out


@pytest.mark.asyncio
async def test_no_running_workers_omits_section():
    # No workers → no worker block (avoids a misleading "0 running" line).
    llm = _CapturingLLM()
    await classify_park(_ctx(), llm)  # _ctx() leaves running_workers empty
    assert "still running" not in llm.user_prompt.lower()
