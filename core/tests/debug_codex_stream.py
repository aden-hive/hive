"""Diagnostic script to reproduce and trace Codex streaming errors.

Run: .venv/bin/python core/tests/debug_codex_stream.py
"""

import asyncio
import json
import sys
import traceback

sys.path.insert(0, "core")

import litellm  # noqa: E402

# Enable litellm debug logging to see the raw HTTP exchange
litellm._turn_on_debug()


async def test_codex_stream():
    """Minimal Codex streaming call via LiteLLMProvider (Responses API path)."""
    from framework.config import get_api_base, get_api_key, get_llm_extra_kwargs
    from framework.llm.litellm import LiteLLMProvider

    api_key = get_api_key()
    api_base = get_api_base()
    extra_kwargs = get_llm_extra_kwargs()

    if not api_key or not api_base:
        print("ERROR: No Codex subscription configured in ~/.hive/configuration.json")
        return

    print(f"api_base: {api_base}")
    print(f"extra_kwargs keys: {list(extra_kwargs.keys())}")
    print(f"extra_headers: {list(extra_kwargs.get('extra_headers', {}).keys())}")

    model = "openai/gpt-5.3-codex"

    # Create the provider
    provider = LiteLLMProvider(
        model=model,
        api_key=api_key,
        api_base=api_base,
        **extra_kwargs,
    )
    print(f"_codex_backend: {provider._codex_backend}")

    # Verify mode is "responses" (the correct routing for Codex backend)
    _strip = model.removeprefix("openai/")
    mode = litellm.model_cost.get(_strip, {}).get("mode", "NOT SET")
    print(f"litellm.model_cost['{_strip}']['mode']: {mode}")
    if mode != "responses":
        print("  WARNING: Expected mode='responses' for Codex backend!")
    print()

    # -----------------------------------------------------------
    # Test 1: Stream via LiteLLMProvider.stream() (the real code path)
    # -----------------------------------------------------------
    print("=" * 60)
    print("TEST 1: LiteLLMProvider.stream() — basic text")
    print("=" * 60)
    try:
        from framework.llm.stream_events import (
            FinishEvent,
            StreamErrorEvent,
            TextDeltaEvent,
            TextEndEvent,
            ToolCallEvent,
        )

        messages = [{"role": "user", "content": "Say hello in exactly 3 words."}]
        chunk_count = 0
        text = ""
        async for event in provider.stream(messages=messages):
            chunk_count += 1
            if isinstance(event, TextDeltaEvent):
                text = event.snapshot
            elif isinstance(event, TextEndEvent):
                print(f"  TextEnd: {event.full_text!r}")
            elif isinstance(event, ToolCallEvent):
                print(f"  ToolCall: {event.tool_name}({event.tool_input})")
            elif isinstance(event, FinishEvent):
                print(
                    f"  Finish: stop={event.stop_reason} "
                    f"in={event.input_tokens} out={event.output_tokens}"
                )
            elif isinstance(event, StreamErrorEvent):
                print(f"  StreamError: {event.error} (recoverable={event.recoverable})")
        print(f"  Text: {text!r}")
        print(f"  Total events: {chunk_count}")
        print("  RESULT: OK" if text else "  RESULT: EMPTY")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
    print()

    # -----------------------------------------------------------
    # Test 2: Stream via LiteLLMProvider.stream() with tools
    # -----------------------------------------------------------
    print("=" * 60)
    print("TEST 2: LiteLLMProvider.stream() — with tools")
    print("=" * 60)
    try:
        from framework.llm.provider import Tool

        tools = [
            Tool(
                name="get_weather",
                description="Get weather for a city",
                parameters={
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            )
        ]
        messages = [{"role": "user", "content": "What is the weather in SF?"}]
        chunk_count = 0
        text = ""
        tool_calls = []
        async for event in provider.stream(messages=messages, tools=tools):
            chunk_count += 1
            if isinstance(event, TextDeltaEvent):
                text = event.snapshot
            elif isinstance(event, ToolCallEvent):
                tool_calls.append({"name": event.tool_name, "input": event.tool_input})
                print(f"  ToolCall: {event.tool_name}({json.dumps(event.tool_input)})")
            elif isinstance(event, FinishEvent):
                print(
                    f"  Finish: stop={event.stop_reason} "
                    f"in={event.input_tokens} out={event.output_tokens}"
                )
            elif isinstance(event, StreamErrorEvent):
                print(f"  StreamError: {event.error} (recoverable={event.recoverable})")
        print(f"  Text: {text!r}")
        print(f"  Tool calls: {json.dumps(tool_calls, indent=2)}")
        print(f"  Total events: {chunk_count}")
        status = "OK" if (text or tool_calls) else "EMPTY"
        print(f"  RESULT: {status}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
    print()

    # -----------------------------------------------------------
    # Test 3: acomplete() via provider (uses stream + collect)
    # -----------------------------------------------------------
    print("=" * 60)
    print("TEST 3: LiteLLMProvider.acomplete() — round-trip")
    print("=" * 60)
    try:
        messages = [{"role": "user", "content": "What is 2+2? Reply with just the number."}]
        response = await provider.acomplete(messages=messages)
        print(f"  Content: {response.content!r}")
        print(f"  Model: {response.model}")
        print(f"  Tokens: in={response.input_tokens} out={response.output_tokens}")
        print(f"  Stop: {response.stop_reason}")
        print("  RESULT: OK" if response.content else "  RESULT: EMPTY")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
    print()

    # -----------------------------------------------------------
    # Test 4: Direct litellm.acompletion with metadata fix
    # -----------------------------------------------------------
    print("=" * 60)
    print("TEST 4: Direct litellm.acompletion (with metadata={})")
    print("=" * 60)
    try:
        direct_kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": "Say hello in exactly 3 words."}],
            "stream": True,
            "api_key": api_key,
            "api_base": api_base,
            "metadata": {},  # Prevent NoneType masking in error handler
            **extra_kwargs,
        }
        response = await litellm.acompletion(**direct_kwargs)
        chunk_count = 0
        text = ""
        async for chunk in response:
            chunk_count += 1
            choices = chunk.choices if chunk.choices else []
            delta = choices[0].delta if choices else None
            content = delta.content if delta and delta.content else ""
            if content:
                text += content
            finish = choices[0].finish_reason if choices else None
            if finish:
                print(f"  finish_reason: {finish}")
        print(f"  Text: {text!r}")
        print(f"  Total chunks: {chunk_count}")
        print("  RESULT: OK" if text else "  RESULT: EMPTY")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
    print()

    # -----------------------------------------------------------
    # Test 5: Rapid-fire 3 calls via provider.stream()
    # -----------------------------------------------------------
    print("=" * 60)
    print("TEST 5: Rapid-fire 3 calls via provider.stream()")
    print("=" * 60)
    for i in range(3):
        try:
            messages = [{"role": "user", "content": f"Say the number {i + 1}."}]
            text = ""
            async for event in provider.stream(messages=messages):
                if isinstance(event, TextDeltaEvent):
                    text = event.snapshot
                elif isinstance(event, StreamErrorEvent):
                    print(f"  Call {i + 1}: StreamError: {event.error}")
                    break
            status = f"OK ({len(text)} chars: {text!r})" if text else "EMPTY"
            print(f"  Call {i + 1}: {status}")
        except Exception as e:
            print(f"  Call {i + 1}: ERROR {type(e).__name__}: {e}")
    print()


if __name__ == "__main__":
    asyncio.run(test_codex_stream())
