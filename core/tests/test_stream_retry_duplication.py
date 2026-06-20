"""
Regression test for GitHub issue #5923:
mid-stream retry must not duplicate already-published tokens.

``LiteLLMProvider.stream`` yields ``TextDeltaEvent``s to the caller in real
time (they are published to the event bus as they arrive). If the underlying
streaming call fails *after* some text has been yielded, the provider's retry
loop resets ``accumulated_text`` and re-streams from token 1 — duplicating
content the client already received.

Fix: once any text has been streamed, stop retrying and emit a recoverable
``StreamErrorEvent`` instead. The consumer (AgentLoop) then commits the partial
text and skips the outer retry. The legitimate retry path (failure *before* any
text was published) must remain intact.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from litellm.exceptions import RateLimitError

from framework.llm.litellm import LiteLLMProvider
from framework.llm.stream_events import StreamErrorEvent, TextDeltaEvent

# ---------------------------------------------------------------------------
# Minimal stubs mirroring the litellm streaming chunk shape the loop actually
# touches: chunk.choices[0].delta.content / .tool_calls and choice.finish_reason.
# ---------------------------------------------------------------------------


def _tool_call(name, arguments, tc_id="call_1"):
    """Build a stub tool-call delta entry (id + index + function name/args)."""
    return SimpleNamespace(id=tc_id, index=0, function=SimpleNamespace(name=name, arguments=arguments))


def _chunk(content=None, finish_reason=None, tool_calls=None):
    """Build a stub streaming chunk wrapping a single choice/delta."""
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


def _text(content):
    """A chunk carrying a single text delta."""
    return _chunk(content=content)


def _tool(name, arguments, tc_id="call_1"):
    """A chunk carrying a single tool-call delta (no text)."""
    return _chunk(tool_calls=[_tool_call(name, arguments, tc_id)])


def _finish(reason="stop"):
    """A terminal chunk carrying a finish_reason and no delta content."""
    return _chunk(finish_reason=reason)


def _scripted_acompletion(scripts):
    """Build an ``acompletion`` side-effect that plays one script per call.

    Each script is ``(chunks, exc_or_none)``: yield each chunk, then raise
    ``exc`` (mid-stream) if provided.
    """
    state = {"calls": 0}

    async def _side_effect(*args, **kwargs):
        idx = min(state["calls"], len(scripts) - 1)
        state["calls"] += 1
        chunks, exc = scripts[idx]

        async def _gen():
            for chunk in chunks:
                yield chunk
            if exc is not None:
                raise exc

        return _gen()

    return _side_effect


async def _collect(provider):
    """Drive ``provider.stream(...)`` to exhaustion and return all emitted events."""
    events = []
    async for event in provider.stream(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=64,
    ):
        events.append(event)
    return events


@pytest.mark.asyncio
@patch("framework.llm.litellm._compute_retry_delay", return_value=0.0)
@patch("litellm.acompletion")
async def test_rate_limit_after_streamed_text_does_not_duplicate(mock_acompletion, _delay):
    """A 429 after text was streamed yields one recoverable error, no retry, no duplication."""
    provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")

    rate_limited = RateLimitError(message="429 rate limited", llm_provider="openai", model="gpt-4o-mini")
    mock_acompletion.side_effect = _scripted_acompletion(
        [
            # attempt 1: stream two tokens, then hit a 429 mid-stream
            ([_text("Hello "), _text("world")], rate_limited),
            # attempt 2: only the buggy code reaches this — it re-streams the text
            ([_text("Hello "), _text("world"), _finish()], None),
        ]
    )

    events = await _collect(provider)

    text = "".join(e.content for e in events if isinstance(e, TextDeltaEvent))
    errors = [e for e in events if isinstance(e, StreamErrorEvent)]

    # Once text has been published, the provider must not retry...
    assert mock_acompletion.call_count == 1
    # ...so every token appears exactly once (no duplication)...
    assert text == "Hello world"
    # ...and the caller is told the failure is recoverable.
    assert len(errors) == 1
    assert errors[0].recoverable is True


@pytest.mark.asyncio
@patch("framework.llm.litellm._compute_retry_delay", return_value=0.0)
@patch("litellm.acompletion")
async def test_transient_error_after_streamed_text_does_not_duplicate(mock_acompletion, _delay):
    """A transient error after text was streamed behaves like the 429 case: no retry, no duplication."""
    provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")

    transient = ConnectionError("connection reset by peer")
    mock_acompletion.side_effect = _scripted_acompletion(
        [
            ([_text("Hello "), _text("world")], transient),
            ([_text("Hello "), _text("world"), _finish()], None),
        ]
    )

    events = await _collect(provider)

    text = "".join(e.content for e in events if isinstance(e, TextDeltaEvent))
    errors = [e for e in events if isinstance(e, StreamErrorEvent)]

    assert mock_acompletion.call_count == 1
    assert text == "Hello world"
    assert len(errors) == 1
    assert errors[0].recoverable is True


@pytest.mark.asyncio
@patch("framework.llm.litellm._compute_retry_delay", return_value=0.0)
@patch("litellm.acompletion")
async def test_transient_error_before_any_text_still_retries(mock_acompletion, _delay):
    """Non-regression guard: a failure *before* any text was published is safe
    to retry, and the provider should still do so."""
    provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")

    mock_acompletion.side_effect = _scripted_acompletion(
        [
            # attempt 1: fail before yielding any text
            ([], ConnectionError("reset before first token")),
            # attempt 2: succeeds
            ([_text("Hello world"), _finish()], None),
        ]
    )

    events = await _collect(provider)

    text = "".join(e.content for e in events if isinstance(e, TextDeltaEvent))

    # Nothing was published yet, so retrying is correct.
    assert mock_acompletion.call_count == 2
    assert text == "Hello world"


@pytest.mark.asyncio
@patch("framework.llm.litellm._compute_retry_delay", return_value=0.0)
@patch("litellm.acompletion")
async def test_no_duplicate_deltas_across_many_chunks(mock_acompletion, _delay):
    """A long partial stream then a 429: every token appears exactly once and in
    order — no chunk is re-emitted by a restart."""
    provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")

    tokens = [f"t{i} " for i in range(50)]
    rate_limited = RateLimitError(message="429 rate limited", llm_provider="openai", model="gpt-4o-mini")
    mock_acompletion.side_effect = _scripted_acompletion(
        [
            ([_text(t) for t in tokens], rate_limited),
            # only the buggy code reaches attempt 2 and re-streams the 50 tokens
            ([_text(t) for t in tokens] + [_finish()], None),
        ]
    )

    events = await _collect(provider)

    deltas = [e.content for e in events if isinstance(e, TextDeltaEvent)]
    errors = [e for e in events if isinstance(e, StreamErrorEvent)]

    assert mock_acompletion.call_count == 1
    assert deltas == tokens  # exactly 50, in order, no duplicates
    assert len(errors) == 1
    assert errors[0].recoverable is True


@pytest.mark.asyncio
@patch("framework.llm.litellm._compute_retry_delay", return_value=0.0)
@patch("litellm.acompletion")
async def test_tool_only_stream_error_still_retries_internally(mock_acompletion, _delay):
    """The guard keys on accumulated_text, not buffered tool-call deltas. Tool
    deltas are never published before the stream completes, so a transient error
    during a tool-only stream is still safe to retry internally."""
    provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")

    mock_acompletion.side_effect = _scripted_acompletion(
        [
            # attempt 1: only tool-call deltas (no text), then a transient error
            ([_tool("search", '{"q": "x"}')], ConnectionError("reset mid-tool")),
            # attempt 2: succeeds
            ([_tool("search", '{"q": "x"}'), _finish("tool_calls")], None),
        ]
    )

    events = await _collect(provider)

    text = "".join(e.content for e in events if isinstance(e, TextDeltaEvent))
    errors = [e for e in events if isinstance(e, StreamErrorEvent)]

    # No text was published, so the guard must NOT fire — the stream is retried.
    assert mock_acompletion.call_count == 2
    assert text == ""
    assert errors == []
