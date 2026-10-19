"""Validate an LLM API key without consuming tokens.

Usage:
    python scripts/check_llm_key.py <provider_id> <api_key> [api_base] [model]

Exit codes:
    0 = valid key
    1 = invalid key
    2 = inconclusive (timeout, network error)

Output: single JSON line {"valid": bool, "message": str}

The checks live in ``framework.llm.key_check``; this is the quickstart CLI.
"""

import json
import sys

import httpx

from framework.llm.key_check import (  # noqa: F401 - re-exported for callers of this script
    PROVIDERS,
    check_anthropic,
    check_anthropic_compatible,
    check_gemini,
    check_key,
    check_minimax,
    check_openai_compatible,
    check_openrouter,
    check_openrouter_model,
)


def main() -> None:
    if len(sys.argv) < 3:
        print(
            json.dumps(
                {
                    "valid": False,
                    "message": "Usage: check_llm_key.py <provider> <key> [api_base] [model]",
                }
            )
        )
        sys.exit(2)

    provider_id = sys.argv[1]
    api_key = sys.argv[2]
    api_base = sys.argv[3] if len(sys.argv) > 3 else ""
    model = sys.argv[4] if len(sys.argv) > 4 else ""

    try:
        result = check_key(provider_id, api_key, api_base=api_base or None, model=model or None)
        print(json.dumps(result))
        sys.exit(0 if result["valid"] else 1)
    except httpx.TimeoutException:
        print(json.dumps({"valid": None, "message": "Request timed out"}))
        sys.exit(2)
    except httpx.RequestError as e:
        msg = str(e)
        # Redact key from error messages
        if api_key in msg:
            msg = msg.replace(api_key, "***")
        print(json.dumps({"valid": None, "message": f"Connection failed: {msg}"}))
        sys.exit(2)


if __name__ == "__main__":
    main()
