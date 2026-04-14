#!/usr/bin/env python3
"""Test script for Gemini CLI OAuth + a custom-tool agent loop.

Tests two things:

1. OAuth flow (gemini-cli subscription path):
   verify that the credentials produced by ``quickstart``
   (stored in ``~/.hive/google-gemini-cli-accounts.json``) are present,
   can be refreshed into a valid access token, and can actually serve a
   request via ``GoogleGeminiCliProvider`` → ``cloudcode-pa.googleapis.com``.

2. Agent loop with a custom tool:
   run a minimal streaming agent loop that exposes ``get_weather`` and
   checks that the model both calls the tool and, after the tool result
   is fed back, produces a final text answer.

Model note:
    ``gemini-3.1-pro-preview-customtools`` is **not** served on the
    Code Assist OAuth backend (``cloudcode-pa.googleapis.com``) — it
    only exists on the Gemini API-key path. See gemini-cli issue #22062.
    This script therefore defaults to ``gemini-3.1-pro-preview``, which
    is the strongest model the gemini-cli OAuth subscription actually
    serves.

Usage:
    uv run python scripts/test_gemini_cli_customtools.py
    uv run python scripts/test_gemini_cli_customtools.py --reauth
    uv run python scripts/test_gemini_cli_customtools.py --model gemini-3-flash-preview
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# Make ``core`` importable like scripts/test_google_providers.py does.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "core"))

from framework.llm.google import (  # noqa: E402
    GoogleGeminiCliProvider,
    _ACCOUNTS_FILE,
    _do_token_refresh,
    _load_accounts_from_json,
)
from framework.llm.provider import Tool  # noqa: E402
from framework.llm.stream_events import (  # noqa: E402
    FinishEvent,
    StreamErrorEvent,
    TextDeltaEvent,
    ToolCallEvent,
)

# Strongest model the gemini-cli OAuth subscription actually serves.
DEFAULT_MODEL = "gemini-3.1-pro-preview"


# ---------------------------------------------------------------------------
# Step 1: OAuth flow check
# ---------------------------------------------------------------------------


def run_quickstart_oauth() -> bool:
    """Invoke the same OAuth entrypoint that quickstart.sh uses."""
    auth_script = _REPO / "core" / "google_auth.py"
    print(f"  Running: uv run python {auth_script} auth account add")
    try:
        result = subprocess.run(
            ["uv", "run", "python", str(auth_script), "auth", "account", "add"],
            cwd=str(_REPO),
            check=False,
        )
    except FileNotFoundError:
        print("  FAIL: `uv` not found on PATH")
        return False
    if result.returncode != 0:
        print(f"  FAIL: google_auth.py exited with code {result.returncode}")
        return False
    return _ACCOUNTS_FILE.exists()


def test_oauth_flow(*, reauth: bool) -> bool:
    print("=" * 60)
    print("STEP 1: OAuth flow (quickstart path)")
    print("=" * 60)
    print(f"  Credentials file: {_ACCOUNTS_FILE}")

    if reauth or not _ACCOUNTS_FILE.exists():
        if not _ACCOUNTS_FILE.exists():
            print("  No credentials on disk — running OAuth login.")
        else:
            print("  --reauth requested — running OAuth login.")
        if not run_quickstart_oauth():
            return False

    if not _ACCOUNTS_FILE.exists():
        print("  FAIL: credentials file still missing after OAuth")
        return False

    access, refresh, expires_at = _load_accounts_from_json()
    print(f"  Loaded credentials: access={'yes' if access else 'no'}, "
          f"refresh={'yes' if refresh else 'no'}, expires_at={expires_at}")

    if not refresh and not access:
        print("  FAIL: credentials file has no tokens")
        return False

    # Force a refresh round-trip so we know the refresh token + OAuth
    # client credentials from quickstart are actually working end-to-end.
    if refresh:
        print("  Refreshing access token...")
        refreshed = _do_token_refresh(refresh)
        if not refreshed:
            print("  FAIL: refresh_token exchange failed")
            return False
        new_token, new_expiry = refreshed
        print(f"  OK: refreshed token (len={len(new_token)}, expires_at={new_expiry:.0f})")
    else:
        print("  WARN: no refresh token; only validating existing access token")

    # Sanity check: the provider will also re-run _ensure_token() later.
    provider = GoogleGeminiCliProvider(model=DEFAULT_MODEL)
    if not provider.has_credentials():
        print("  FAIL: provider reports no credentials after load")
        return False
    print("  OK: provider has credentials")
    return True


# ---------------------------------------------------------------------------
# Step 2: Agent loop with a custom tool
# ---------------------------------------------------------------------------


WEATHER_TOOL = Tool(
    name="get_weather",
    description="Get the current weather for a given city.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name, e.g. 'Tokyo'"},
        },
        "required": ["city"],
    },
)


def fake_get_weather(city: str) -> str:
    # Deterministic fake result; the test cares about the loop, not the value.
    return json.dumps({"city": city, "temp_c": 21, "conditions": "sunny"})


def _parse_rate_limit_reset(err_msg: str) -> int | None:
    """Extract the 'reset after Ns' hint from a Cloud Code Assist 429 body."""
    if "RATE_LIMIT_EXCEEDED" not in err_msg and "429" not in err_msg:
        return None
    m = re.search(r"reset after (\d+)\s*s", err_msg)
    if m:
        return int(m.group(1))
    # No hint — fall back to a short default so we still retry once.
    return 5


async def run_agent_turn(
    provider: Any,
    messages: list[dict[str, Any]],
    tools: list[Tool],
) -> tuple[str, list[dict[str, Any]], str]:
    """Run one streaming turn. Returns (text, tool_calls, finish_reason)."""
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    finish_reason = ""

    async for event in provider.stream(
        messages=messages,
        system="You are a helpful assistant. Use tools when appropriate.",
        tools=tools,
        max_tokens=1024,
    ):
        if isinstance(event, TextDeltaEvent):
            text_parts.append(event.content)
            sys.stdout.write(event.content)
            sys.stdout.flush()
        elif isinstance(event, ToolCallEvent):
            print(f"\n  [tool_call] {event.tool_name}({event.tool_input}) id={event.tool_use_id}")
            tool_calls.append(
                {
                    "id": event.tool_use_id,
                    "type": "function",
                    "function": {
                        "name": event.tool_name,
                        "arguments": json.dumps(event.tool_input or {}),
                    },
                }
            )
        elif isinstance(event, FinishEvent):
            finish_reason = event.stop_reason
            print(f"\n  [finish] reason={finish_reason} "
                  f"in={event.input_tokens} out={event.output_tokens}")
        elif isinstance(event, StreamErrorEvent):
            raise RuntimeError(f"stream error: {event.error}")

    return "".join(text_parts), tool_calls, finish_reason


async def test_agent_loop(model: str, max_turns: int = 4) -> bool:
    print()
    print("=" * 60)
    print(f"STEP 2: Agent loop with custom tool  (model={model})")
    print("=" * 60)

    try:
        provider = GoogleGeminiCliProvider(model=model)
    except Exception as exc:
        print(f"  FAIL: could not construct provider: {exc}")
        return False

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                "What's the weather in Tokyo right now? "
                "Use the get_weather tool, then tell me in one short sentence."
            ),
        }
    ]

    saw_tool_call = False
    final_text = ""

    for turn in range(1, max_turns + 1):
        print(f"\n--- turn {turn} ---")
        # Back-to-back calls on the Gemini CLI free tier trip per-model
        # rate limits with very short reset windows. Retry once or twice
        # after the reset instead of failing the whole run on a 2s pause.
        retries_left = 3
        while True:
            try:
                text, tool_calls, finish = await run_agent_turn(
                    provider, messages, [WEATHER_TOOL]
                )
                break
            except Exception as exc:
                msg = str(exc)
                reset = _parse_rate_limit_reset(msg)
                if reset is not None and retries_left > 0:
                    wait = max(reset, 1) + 2
                    print(f"\n  rate-limited; sleeping {wait}s then retrying...")
                    await asyncio.sleep(wait)
                    retries_left -= 1
                    continue
                print(f"\n  FAIL: turn {turn} raised: {exc}")
                return False

        if tool_calls:
            saw_tool_call = True
            messages.append(
                {"role": "assistant", "content": text or None, "tool_calls": tool_calls}
            )
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                if fn_name == "get_weather":
                    result = fake_get_weather(args.get("city", ""))
                else:
                    result = json.dumps({"error": f"unknown tool {fn_name}"})
                print(f"  [tool_result] {fn_name} -> {result}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": fn_name,
                        "content": result,
                    }
                )
            continue

        final_text = text.strip()
        break
    else:
        print("\n  FAIL: agent loop did not terminate within max_turns")
        return False

    if not saw_tool_call:
        print("\n  FAIL: model never called get_weather")
        return False
    if not final_text:
        print("\n  FAIL: model returned no final text after tool result")
        return False

    print(f"\n  OK: final answer -> {final_text!r}")
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model ID to test")
    parser.add_argument(
        "--reauth",
        action="store_true",
        help="Force running the quickstart OAuth flow before testing",
    )
    parser.add_argument(
        "--skip-oauth",
        action="store_true",
        help="Skip step 1 and assume credentials already work",
    )
    args = parser.parse_args()

    if not args.skip_oauth:
        if not test_oauth_flow(reauth=args.reauth):
            print("\nRESULT: OAUTH FAILED")
            return 1

    try:
        ok = asyncio.run(test_agent_loop(args.model))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130

    print()
    print("=" * 60)
    print("RESULT:", "PASS" if ok else "FAIL")
    print("=" * 60)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
