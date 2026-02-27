"""Run Codex stream with litellm debug logging enabled.

Run: .venv/bin/python core/tests/debug_codex_verbose.py
"""

import asyncio
import sys

sys.path.insert(0, "core")

import litellm  # noqa: E402

litellm._turn_on_debug()

from framework.config import get_api_base, get_api_key, get_llm_extra_kwargs  # noqa: E402
from framework.llm.litellm import LiteLLMProvider  # noqa: E402
from framework.llm.stream_events import (  # noqa: E402
    FinishEvent,
    StreamErrorEvent,
    TextDeltaEvent,
    TextEndEvent,
    ToolCallEvent,
)


async def main():
    api_key = get_api_key()
    api_base = get_api_base()
    extra_kwargs = get_llm_extra_kwargs()

    if not api_key or not api_base:
        print("ERROR: No Codex config in ~/.hive/configuration.json")
        return

    provider = LiteLLMProvider(
        model="openai/gpt-5.3-codex",
        api_key=api_key,
        api_base=api_base,
        **extra_kwargs,
    )

    print(f"_codex_backend={provider._codex_backend}")
    print()

    text = ""
    async for event in provider.stream(
        messages=[{"role": "user", "content": "What is 2+2? Reply with just the number."}],
        system="You are a helpful assistant.",
    ):
        if isinstance(event, TextDeltaEvent):
            text = event.snapshot
        elif isinstance(event, TextEndEvent):
            print(f"TextEnd: {event.full_text!r}")
        elif isinstance(event, ToolCallEvent):
            print(f"ToolCall: {event.tool_name}({event.tool_input})")
        elif isinstance(event, FinishEvent):
            print(
                f"Finish: stop={event.stop_reason} "
                f"in={event.input_tokens} out={event.output_tokens}"
            )
        elif isinstance(event, StreamErrorEvent):
            print(f"StreamError: {event.error} (recoverable={event.recoverable})")

    print(f"Text: {text!r}")
    print("OK" if text else "EMPTY")


if __name__ == "__main__":
    asyncio.run(main())
