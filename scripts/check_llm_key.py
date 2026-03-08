"""Validate an LLM API key without consuming tokens.

Usage:
    python scripts/check_llm_key.py <provider_id> <api_key> [api_base]

Exit codes:
    0 = valid key
    1 = invalid key
    2 = inconclusive (timeout, network error)

Output: single JSON line {"valid": bool, "message": str}
"""

import json
import sys

import httpx

TIMEOUT = 10.0


def check_anthropic(api_key: str, **_: str) -> dict:
    """Send empty messages to trigger 400 without consuming tokens."""
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 1, "messages": []},
        )
    if r.status_code in (200, 400, 429):
        return {"valid": True, "message": "API key valid"}
    if r.status_code == 401:
        return {"valid": False, "message": "Invalid API key"}
    if r.status_code == 403:
        return {"valid": False, "message": "API key lacks permissions"}
    return {"valid": False, "message": f"Unexpected status {r.status_code}"}


def check_openai_compatible(api_key: str, endpoint: str, name: str) -> dict:
    """GET /models on any OpenAI-compatible API."""
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.get(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if r.status_code in (200, 429):
        return {"valid": True, "message": f"{name} API key valid"}
    if r.status_code == 401:
        return {"valid": False, "message": f"Invalid {name} API key"}
    if r.status_code == 403:
        return {"valid": False, "message": f"{name} API key lacks permissions"}
    return {"valid": False, "message": f"{name} API returned status {r.status_code}"}


def check_gemini(api_key: str, **_: str) -> dict:
    """List models with query param auth."""
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": api_key},
        )
    if r.status_code in (200, 429):
        return {"valid": True, "message": "Gemini API key valid"}
    if r.status_code in (400, 401, 403):
        return {"valid": False, "message": "Invalid Gemini API key"}
    return {"valid": False, "message": f"Gemini API returned status {r.status_code}"}


PROVIDERS = {
    "anthropic": lambda key, **kw: check_anthropic(key),
    "openai": lambda key, **kw: check_openai_compatible(
        key, "https://api.openai.com/v1/models", "OpenAI"
    ),
    "gemini": lambda key, **kw: check_gemini(key),
    "groq": lambda key, **kw: check_openai_compatible(
        key, "https://api.groq.com/openai/v1/models", "Groq"
    ),
    "cerebras": lambda key, **kw: check_openai_compatible(
        key, "https://api.cerebras.ai/v1/models", "Cerebras"
    ),
    "minimax": lambda key, **kw: check_openai_compatible(
        key, "https://api.minimax.io/v1/models", "MiniMax"
    ),
}


def main() -> None:
    if len(sys.argv) < 3:
        print(
            json.dumps(
                {
                    "valid": False,
                    "message": "Usage: check_llm_key.py <provider> <key> [api_base]",
                }
            )
        )
        sys.exit(2)

    provider_id = sys.argv[1]
    api_key = sys.argv[2]
    api_base = sys.argv[3] if len(sys.argv) > 3 else ""

    try:
        if api_base:
            # Custom API base (ZAI or other OpenAI-compatible)
            endpoint = api_base.rstrip("/") + "/models"
            name = {"zai": "ZAI", "minimax": "MiniMax"}.get(provider_id, "Custom provider")
            result = check_openai_compatible(api_key, endpoint, name)
        elif provider_id in PROVIDERS:
            result = PROVIDERS[provider_id](api_key)
        else:
            result = {"valid": True, "message": f"No health check for {provider_id}"}
            print(json.dumps(result))
            sys.exit(0)

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
