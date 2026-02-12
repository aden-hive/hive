"""Regression tests for LLMNode token accounting across retries."""

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from framework.graph.node import LLMNode, NodeContext, NodeSpec, SharedMemory
from framework.llm.provider import LLMResponse


class SequentialLLM:
    """LLM test double that returns responses in sequence."""

    def __init__(self, responses: list[LLMResponse]):
        self.model = "mock-model"
        self._responses = list(responses)
        self.complete_calls = 0

    def complete(
        self,
        messages,
        system="",
        tools=None,
        max_tokens=1024,
        response_format=None,
        json_mode=False,
    ):
        if not self._responses:
            raise AssertionError("No more mock responses configured")
        self.complete_calls += 1
        return self._responses.pop(0)

    def complete_with_tools(self, messages, system, tools, tool_executor, max_iterations=10):
        raise NotImplementedError("Tool flow not used in these tests")


def _build_context(node_spec: NodeSpec, responses: list[LLMResponse]):
    runtime = MagicMock()
    runtime.decide.return_value = "decision-1"

    llm = SequentialLLM(responses)
    ctx = NodeContext(
        runtime=runtime,
        node_id=node_spec.id,
        node_spec=node_spec,
        memory=SharedMemory(),
        input_data={"task": "demo"},
        llm=llm,
        max_tokens=256,
    )
    return ctx, runtime, llm


class ValidationOutput(BaseModel):
    """Output schema used to trigger validation retry."""

    message: str
    count: int


@pytest.mark.asyncio
async def test_tokens_include_validation_retry_usage():
    node_spec = NodeSpec(
        id="node_validation",
        name="Validation Node",
        description="Validation retry token accounting",
        node_type="llm_generate",
        output_keys=["message", "count"],
        output_model=ValidationOutput,
        max_validation_retries=1,
    )
    responses = [
        LLMResponse(
            content='{"message":"missing count"}',
            model="mock-model",
            input_tokens=11,
            output_tokens=7,
            stop_reason="stop",
        ),
        LLMResponse(
            content='{"message":"ok","count":2}',
            model="mock-model",
            input_tokens=13,
            output_tokens=5,
            stop_reason="stop",
        ),
    ]

    ctx, runtime, llm = _build_context(node_spec, responses)
    result = await LLMNode().execute(ctx)

    expected_tokens = 36  # (11+7) + (13+5)
    assert result.success is True
    assert result.tokens_used == expected_tokens
    assert llm.complete_calls == 2
    assert runtime.record_outcome.call_args.kwargs["tokens_used"] == expected_tokens


@pytest.mark.asyncio
async def test_tokens_include_compaction_retry_usage():
    node_spec = NodeSpec(
        id="node_compaction",
        name="Compaction Node",
        description="Compaction retry token accounting",
        node_type="llm_generate",
        output_keys=["answer"],
    )
    responses = [
        LLMResponse(
            content='{"answer":"too long"}',
            model="mock-model",
            input_tokens=5,
            output_tokens=3,
            stop_reason="length",
        ),
        LLMResponse(
            content='{"answer":"ok"}',
            model="mock-model",
            input_tokens=7,
            output_tokens=4,
            stop_reason="stop",
        ),
    ]

    ctx, runtime, llm = _build_context(node_spec, responses)
    result = await LLMNode().execute(ctx)

    expected_tokens = 19  # (5+3) + (7+4)
    assert result.success is True
    assert result.tokens_used == expected_tokens
    assert llm.complete_calls == 2
    assert runtime.record_outcome.call_args.kwargs["tokens_used"] == expected_tokens


@pytest.mark.asyncio
async def test_extraction_failure_uses_aggregated_tokens(monkeypatch):
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    node_spec = NodeSpec(
        id="node_extract_fail",
        name="Extraction Failure Node",
        description="Extraction failure token accounting",
        node_type="llm_generate",
        output_keys=["answer"],
    )
    responses = [
        LLMResponse(
            content='{"answer":"truncated"}',
            model="mock-model",
            input_tokens=6,
            output_tokens=2,
            stop_reason="length",
        ),
        LLMResponse(
            content="not json output",
            model="mock-model",
            input_tokens=9,
            output_tokens=1,
            stop_reason="stop",
        ),
    ]

    ctx, runtime, llm = _build_context(node_spec, responses)
    result = await LLMNode().execute(ctx)

    expected_tokens = 18  # (6+2) + (9+1)
    assert result.success is False
    assert "Output extraction failed" in (result.error or "")
    assert result.tokens_used == expected_tokens
    assert llm.complete_calls == 2
    assert runtime.record_outcome.call_args.kwargs["tokens_used"] == expected_tokens
