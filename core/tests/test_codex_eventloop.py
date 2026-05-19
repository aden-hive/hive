"""Integration test: Run a real EventLoopNode against the Codex backend.

Run: .venv/bin/python core/tests/test_codex_eventloop.py
"""

import asyncio
import logging
import sys
from unittest.mock import MagicMock

sys.path.insert(0, "core")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
# Show our provider's retry/stream logs
logging.getLogger("framework.llm.litellm").setLevel(logging.DEBUG)

from framework.config import RuntimeConfig  # noqa: E402
from framework.graph.event_loop_node import EventLoopNode, LoopConfig  # noqa: E402
from framework.graph.node import NodeContext, NodeResult, NodeSpec, SharedMemory  # noqa: E402
from framework.llm.litellm import LiteLLMProvider  # noqa: E402


def make_provider() -> LiteLLMProvider:
    cfg = RuntimeConfig()
    if not cfg.api_key:
        print("ERROR: No API key configured in ~/.hive/configuration.json")
        sys.exit(1)
    print(f"Model : {cfg.model}")
    print(f"Base  : {cfg.api_base}")
    print(f"Codex : {'chatgpt.com/backend-api/codex' in (cfg.api_base or '')}")
    return LiteLLMProvider(
        model=cfg.model,
        api_key=cfg.api_key,
        api_base=cfg.api_base,
        **cfg.extra_kwargs,
    )


def make_context(
    llm: LiteLLMProvider,
    *,
    node_id: str = "test",
    system_prompt: str = "You are a helpful assistant.",
    output_keys: list[str] | None = None,
) -> NodeContext:
    if output_keys is None:
        output_keys = ["answer"]

    spec = NodeSpec(
        id=node_id,
        name="Test Node",
        description="Integration test node",
        node_type="event_loop",
        output_keys=output_keys,
        system_prompt=system_prompt,
    )

    runtime = MagicMock()
    runtime.start_run = MagicMock(return_value="run-1")
    runtime.decide = MagicMock(return_value="dec-1")
    runtime.record_outcome = MagicMock()
    runtime.end_run = MagicMock()

    memory = SharedMemory()

    return NodeContext(
        runtime=runtime,
        node_id=node_id,
        node_spec=spec,
        memory=memory,
        input_data={},
        llm=llm,
        available_tools=[],
        max_tokens=4096,
    )


async def run_test(
    name: str, llm: LiteLLMProvider, system: str, output_keys: list[str]
) -> NodeResult:
    print(f"\n{'=' * 60}")
    print(f"TEST: {name}")
    print(f"{'=' * 60}")

    ctx = make_context(llm, system_prompt=system, output_keys=output_keys)
    node = EventLoopNode(config=LoopConfig(max_iterations=3))

    try:
        result = await node.execute(ctx)
        print(f"  Success : {result.success}")
        print(f"  Output  : {result.output}")
        if result.error:
            print(f"  Error   : {result.error}")
        return result
    except Exception as e:
        print(f"  EXCEPTION: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return NodeResult(success=False, error=str(e))


async def main():
    llm = make_provider()
    print()

    # Test 1: Simple text output — the node should call set_output to fill "answer"
    r1 = await run_test(
        name="Simple text generation",
        llm=llm,
        system=(
            "You are a helpful assistant. When asked a question, use the "
            "set_output tool to store your answer in the 'answer' key. "
            "Keep answers short (1-2 sentences)."
        ),
        output_keys=["answer"],
    )

    # Test 2: If test 1 failed, try bare stream() to isolate the issue
    if not r1.success:
        print(f"\n{'=' * 60}")
        print("FALLBACK: Testing bare provider.stream() directly")
        print(f"{'=' * 60}")
        try:
            from framework.llm.stream_events import (
                FinishEvent,
                StreamErrorEvent,
                TextDeltaEvent,
                ToolCallEvent,
            )

            text = ""
            events = []
            async for event in llm.stream(
                messages=[{"role": "user", "content": "Say hello in 3 words."}],
            ):
                events.append(type(event).__name__)
                if isinstance(event, TextDeltaEvent):
                    text = event.snapshot
                elif isinstance(event, FinishEvent):
                    print(
                        f"  Finish: stop={event.stop_reason}"
                        f" in={event.input_tokens}"
                        f" out={event.output_tokens}"
                    )
                elif isinstance(event, StreamErrorEvent):
                    print(f"  StreamError: {event.error} (recoverable={event.recoverable})")
                elif isinstance(event, ToolCallEvent):
                    print(f"  ToolCall: {event.tool_name}")
            print(f"  Text   : {text!r}")
            print(f"  Events : {events}")
            print(f"  RESULT : {'OK' if text else 'EMPTY'}")
        except Exception as e:
            print(f"  EXCEPTION: {type(e).__name__}: {e}")
            import traceback

            traceback.print_exc()

    print(f"\n{'=' * 60}")
    print("DONE")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
