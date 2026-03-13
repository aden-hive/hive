"""Validate an LLM API key (and optionally model access) without consuming tokens.

Usage:
    python scripts/check_llm_key.py <provider_id> <api_key> [api_base] [model_id]
    python scripts/check_llm_key.py <provider_id> <api_key> [model_id]

Exit codes:
    0 = valid key
    1 = invalid key
    2 = inconclusive (timeout, network error)

Output: single JSON line {"valid": bool|None, "message": str}
"""

import json
import sys

import httpx

TIMEOUT = 10.0


def check_anthropic(
    api_key: str, model_id: str = "claude-sonnet-4-20250514", **_: str
) -> dict:
    """Send empty messages to trigger 400 without consuming tokens."""
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={"model": model_id, "max_tokens": 1, "messages": []},
        )
    if r.status_code in (200, 400, 429):
        return {"valid": True, "message": "API key valid"}
    if r.status_code == 401:
        return {"valid": False, "message": "Invalid API key"}
    if r.status_code == 403:
        return {"valid": False, "message": "API key lacks permissions"}
    return {"valid": False, "message": f"Unexpected status {r.status_code}"}


def check_openai_compatible(
    api_key: str, endpoint: str, name: str, model_id: str = ""
) -> dict:
    """GET /models on any OpenAI-compatible API."""
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.get(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if r.status_code == 200:
        if model_id:
            try:
                payload = r.json()
                available_ids = [
                    str(item.get("id"))
                    for item in payload.get("data", [])
                    if isinstance(item, dict) and item.get("id")
                ]
            except (ValueError, TypeError, AttributeError):
                available_ids = []
            if available_ids and model_id not in available_ids:
                preview = ", ".join(available_ids[:5])
                if len(available_ids) > 5:
                    preview += ", ..."
                return {
                    "valid": False,
                    "message": (
                        f"Model '{model_id}' is not available for {name}. "
                        f"Available examples: {preview}"
                    ),
                }
        return {"valid": True, "message": f"{name} API key valid"}
    if r.status_code == 429:
        if model_id:
            return {
                "valid": None,
                "message": f"{name} rate limited while checking model '{model_id}'",
            }
        return {"valid": True, "message": f"{name} API key valid"}
    if r.status_code == 401:
        return {"valid": False, "message": f"Invalid {name} API key"}
    if r.status_code == 403:
        return {"valid": False, "message": f"{name} API key lacks permissions"}
    return {"valid": False, "message": f"{name} API returned status {r.status_code}"}


def check_minimax(
    api_key: str,
    api_base: str = "https://api.minimax.io/v1",
    model_id: str = "MiniMax-M2.5",
    **_: str,
) -> dict:
    """Validate via chatcompletion_v2 endpoint with empty messages.

    MiniMax doesn't support GET /models; their native endpoint is
    /v1/text/chatcompletion_v2.
    """
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(
            f"{api_base.rstrip('/')}/text/chatcompletion_v2",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model_id, "messages": []},
        )
    if r.status_code in (200, 400, 422, 429):
        return {"valid": True, "message": "MiniMax API key valid"}
    if r.status_code == 401:
        return {"valid": False, "message": "Invalid MiniMax API key"}
    if r.status_code == 403:
        return {"valid": False, "message": "MiniMax API key lacks permissions"}
    return {"valid": False, "message": f"MiniMax API returned status {r.status_code}"}


def check_anthropic_compatible(
    api_key: str, endpoint: str, name: str, model_id: str = "kimi-k2.5"
) -> dict:
    """POST empty messages to an Anthropic-compatible endpoint to validate key."""
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(
            endpoint,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={"model": model_id, "max_tokens": 1, "messages": []},
        )
    if r.status_code in (200, 400, 429):
        return {"valid": True, "message": f"{name} API key valid"}
    if r.status_code == 401:
        return {"valid": False, "message": f"Invalid {name} API key"}
    if r.status_code == 403:
        return {"valid": False, "message": f"{name} API key lacks permissions"}
    return {"valid": False, "message": f"{name} API returned status {r.status_code}"}


def check_gemini(api_key: str, model_id: str = "", **_: str) -> dict:
    """List models with query param auth."""
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": api_key},
        )
    if r.status_code == 200:
        if model_id:
            try:
                payload = r.json()
                names = [
                    str(item.get("name"))
                    for item in payload.get("models", [])
                    if isinstance(item, dict) and item.get("name")
                ]
            except (ValueError, TypeError, AttributeError):
                names = []
            if names:
                needle = model_id.lower()
                has_model = any(
                    n.lower() == needle or n.lower().endswith("/" + needle) for n in names
                )
                if not has_model:
                    preview = ", ".join(names[:5])
                    if len(names) > 5:
                        preview += ", ..."
                    return {
                        "valid": False,
                        "message": (
                            f"Model '{model_id}' is not available for Gemini. "
                            f"Available examples: {preview}"
                        ),
                    }
        return {"valid": True, "message": "Gemini API key valid"}
    if r.status_code == 429:
        if model_id:
            return {
                "valid": None,
                "message": f"Gemini rate limited while checking model '{model_id}'",
            }
        return {"valid": True, "message": "Gemini API key valid"}
    if r.status_code in (400, 401, 403):
        return {"valid": False, "message": "Invalid Gemini API key"}
    return {"valid": False, "message": f"Gemini API returned status {r.status_code}"}


PROVIDERS = {
    "anthropic": lambda key, model_id="", **kw: check_anthropic(key, model_id=model_id),
    "openai": lambda key, **kw: check_openai_compatible(
        key, "https://api.openai.com/v1/models", "OpenAI", model_id=kw.get("model_id", "")
    ),
    "gemini": lambda key, model_id="", **kw: check_gemini(key, model_id=model_id),
    "groq": lambda key, **kw: check_openai_compatible(
        key, "https://api.groq.com/openai/v1/models", "Groq", model_id=kw.get("model_id", "")
    ),
    "cerebras": lambda key, **kw: check_openai_compatible(
        key,
        "https://api.cerebras.ai/v1/models",
        "Cerebras",
        model_id=kw.get("model_id", ""),
    ),
    "minimax": lambda key, model_id="", **kw: check_minimax(key, model_id=model_id),
    # Kimi For Coding uses an Anthropic-compatible endpoint; check via /v1/messages
    # with empty messages (same as check_anthropic, triggers 400 not 401).
    "kimi": lambda key, model_id="", **kw: check_anthropic_compatible(
        key, "https://api.kimi.com/coding/v1/messages", "Kimi", model_id=model_id or "kimi-k2.5"
    ),
}


def main() -> None:
    if len(sys.argv) < 3:
        print(
            json.dumps(
                {"valid": False, "message": "Usage: check_llm_key.py <provider> <key> [api_base] [model_id]"}
            )
        )
        sys.exit(2)

    provider_id = sys.argv[1]
    api_key = sys.argv[2]
    api_base = ""
    model_id = ""
    for extra in sys.argv[3:]:
        if extra.startswith(("http://", "https://")):
            api_base = extra
        else:
            model_id = extra

    try:
        if api_base and provider_id == "minimax":
            result = check_minimax(api_key, api_base, model_id=model_id or "MiniMax-M2.5")
        elif api_base and provider_id == "kimi":
            # Kimi uses an Anthropic-compatible endpoint; check via /v1/messages
            result = check_anthropic_compatible(
                api_key,
                api_base.rstrip("/") + "/v1/messages",
                "Kimi",
                model_id=model_id or "kimi-k2.5",
            )
        elif api_base:
            # Custom API base (ZAI or other OpenAI-compatible)
            endpoint = api_base.rstrip("/") + "/models"
            name = {"zai": "ZAI"}.get(provider_id, "Custom provider")
            result = check_openai_compatible(api_key, endpoint, name, model_id=model_id)
        elif provider_id in PROVIDERS:
            result = PROVIDERS[provider_id](api_key, model_id=model_id)
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
