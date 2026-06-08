"""Validate an LLM API key without consuming tokens.

Usage:
    python scripts/check_llm_key.py <provider_id> <api_key> [api_base] [model]

Exit codes:
    0 = valid key
    1 = invalid key
    2 = inconclusive (timeout, network error)

Output: single JSON line {"valid": bool, "message": str}
"""

import json
import re
import sys
import unicodedata
from difflib import get_close_matches

import httpx

from framework.config import HIVE_LLM_ENDPOINT

TIMEOUT = 10.0
OPENROUTER_SEPARATOR_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u2044": "/",
        "\u2215": "/",
        "\u29f8": "/",
        "\uff0f": "/",
    }
)


def _extract_error_message(response: httpx.Response) -> str:
    """Best-effort extraction of a provider error message."""
    try:
        payload = response.json()
    except Exception:
        text = (response.text or "").strip()
        return text[:240] if text else ""

    if isinstance(payload, dict):
        error_value = payload.get("error")
        if isinstance(error_value, dict):
            message = error_value.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        if isinstance(error_value, str) and error_value.strip():
            return error_value.strip()
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    return ""


def _sanitize_openrouter_model_id(value: str) -> str:
    """Sanitize pasted OpenRouter model IDs into a comparable slug."""
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) not in {"Cc", "Cf"})
    normalized = normalized.translate(OPENROUTER_SEPARATOR_TRANSLATION)
    normalized = re.sub(r"\s+", "", normalized)
    if normalized.casefold().startswith("openrouter/"):
        normalized = normalized.split("/", 1)[1]
    return normalized


def _normalize_openrouter_model_id(value: str) -> str:
    """Normalize OpenRouter model IDs for exact/alias matching."""
    return _sanitize_openrouter_model_id(value).casefold()


def _extract_openrouter_model_lookup(payload: object) -> dict[str, str]:
    """Map normalized model IDs/aliases to a preferred canonical display slug."""
    if not isinstance(payload, dict):
        return {}

    data = payload.get("data")
    if not isinstance(data, list):
        return {}

    lookup: dict[str, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue

        model_id = item.get("id")
        canonical_slug = item.get("canonical_slug")
        candidates = [
            _sanitize_openrouter_model_id(value)
            for value in (model_id, canonical_slug)
            if isinstance(value, str) and _sanitize_openrouter_model_id(value)
        ]
        if not candidates:
            continue

        preferred_slug = candidates[-1]
        for candidate in candidates:
            lookup[_normalize_openrouter_model_id(candidate)] = preferred_slug

    return lookup


def _format_openrouter_model_unavailable_message(model: str, available_model_lookup: dict[str, str]) -> str:
    """Return a helpful not-found message with close-match suggestions."""
    suggestions = [
        available_model_lookup[key]
        for key in get_close_matches(
            _normalize_openrouter_model_id(model),
            list(available_model_lookup),
            n=1,
            cutoff=0.6,
        )
    ]

    base = f"OpenRouter model is not available for this key/settings: {model}"
    if suggestions:
        return f"{base}. Closest matches: {', '.join(suggestions)}"
    return base


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


def check_openrouter(api_key: str, api_base: str = "https://openrouter.ai/api/v1", **_: str) -> dict:
    """Validate OpenRouter key against GET /models."""
    endpoint = f"{api_base.rstrip('/')}/models"
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.get(endpoint, headers={"Authorization": f"Bearer {api_key}"})
    if r.status_code in (200, 429):
        return {"valid": True, "message": "OpenRouter API key valid"}
    if r.status_code == 401:
        return {"valid": False, "message": "Invalid OpenRouter API key"}
    if r.status_code == 403:
        return {"valid": False, "message": "OpenRouter API key lacks permissions"}
    return {
        "valid": False,
        "message": f"OpenRouter API returned status {r.status_code}",
    }


def check_openrouter_model(
    api_key: str,
    model: str,
    api_base: str = "https://openrouter.ai/api/v1",
    **_: str,
) -> dict:
    """Validate that an OpenRouter model ID is available to this key/settings."""
    requested_model = _sanitize_openrouter_model_id(model)
    endpoint = f"{api_base.rstrip('/')}/models/user"
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.get(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if r.status_code == 200:
        available_model_lookup = _extract_openrouter_model_lookup(r.json())
        matched_model = available_model_lookup.get(_normalize_openrouter_model_id(requested_model))
        if matched_model:
            return {
                "valid": True,
                "message": f"OpenRouter model is available: {matched_model}",
                "model": matched_model,
            }

        return {
            "valid": False,
            "message": _format_openrouter_model_unavailable_message(requested_model, available_model_lookup),
        }
    if r.status_code == 429:
        return {
            "valid": True,
            "message": "OpenRouter model check rate-limited; assuming model is reachable",
        }
    if r.status_code == 401:
        return {"valid": False, "message": "Invalid OpenRouter API key"}
    if r.status_code == 403:
        return {"valid": False, "message": "OpenRouter API key lacks permissions"}

    detail = _extract_error_message(r)
    if r.status_code in (400, 404, 422):
        base = f"OpenRouter model is not available for this key/settings: {requested_model}"
        return {"valid": False, "message": f"{base}. {detail}" if detail else base}

    suffix = f": {detail}" if detail else ""
    return {
        "valid": False,
        "message": f"OpenRouter model check returned status {r.status_code}{suffix}",
    }


def check_minimax(api_key: str, api_base: str = "https://api.minimax.io/v1", **_: str) -> dict:
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
            json={"model": "MiniMax-M2.5", "messages": []},
        )
    if r.status_code in (200, 400, 422, 429):
        return {"valid": True, "message": "MiniMax API key valid"}
    if r.status_code == 401:
        return {"valid": False, "message": "Invalid MiniMax API key"}
    if r.status_code == 403:
        return {"valid": False, "message": "MiniMax API key lacks permissions"}
    return {"valid": False, "message": f"MiniMax API returned status {r.status_code}"}


def check_anthropic_compatible(api_key: str, endpoint: str, name: str) -> dict:
    """POST empty messages to an Anthropic-compatible endpoint to validate key."""
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(
            endpoint,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={"model": "kimi-k2.5", "max_tokens": 1, "messages": []},
        )
    if r.status_code in (200, 400, 429):
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
    "openai": lambda key, **kw: check_openai_compatible(key, "https://api.openai.com/v1/models", "OpenAI"),
    "gemini": lambda key, **kw: check_gemini(key),
    "groq": lambda key, **kw: check_openai_compatible(key, "https://api.groq.com/openai/v1/models", "Groq"),
    "cerebras": lambda key, **kw: check_openai_compatible(key, "https://api.cerebras.ai/v1/models", "Cerebras"),
    "openrouter": lambda key, **kw: check_openrouter(key, **kw),
    "deepseek": lambda key, **_: check_openai_compatible(key, "https://api.deepseek.com/v1/models", "DeepSeek"),
    "together": lambda key, **_: check_openai_compatible(key, "https://api.together.xyz/v1/models", "Together AI"),
    "mistral": lambda key, **_: check_openai_compatible(key, "https://api.mistral.ai/v1/models", "Mistral"),
    "xai": lambda key, **_: check_openai_compatible(key, "https://api.x.ai/v1/models", "xAI"),
    "perplexity": lambda key, **_: check_openai_compatible(key, "https://api.perplexity.ai/v1/models", "Perplexity"),
    "minimax": lambda key, **_: check_minimax(key),
    # Kimi For Coding uses an Anthropic-compatible endpoint; check via /v1/messages
    # with empty messages (same as check_anthropic, triggers 400 not 401).
    "kimi": lambda key, **kw: check_anthropic_compatible(key, "https://api.kimi.com/coding/v1/messages", "Kimi"),
    # Hive LLM uses an Anthropic-compatible endpoint
    "hive": lambda key, **kw: check_anthropic_compatible(key, f"{HIVE_LLM_ENDPOINT}/v1/messages", "Hive"),
}


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
        if provider_id == "openrouter" and model:
            result = check_openrouter_model(
                api_key,
                model=model,
                api_base=(api_base or "https://openrouter.ai/api/v1"),
            )
        elif api_base and provider_id == "minimax":
            result = check_minimax(api_key, api_base)
        elif api_base and provider_id == "openrouter":
            result = check_openrouter(api_key, api_base)
        elif api_base and provider_id == "kimi":
            # Kimi uses an Anthropic-compatible endpoint; check via /v1/messages
            result = check_anthropic_compatible(api_key, api_base.rstrip("/") + "/v1/messages", "Kimi")
        elif api_base and provider_id == "hive":
            result = check_anthropic_compatible(api_key, api_base.rstrip("/") + "/v1/messages", "Hive")
        elif api_base:
            # Custom API base (ZAI or other OpenAI-compatible)
            endpoint = api_base.rstrip("/") + "/models"
            name = {"zai": "ZAI"}.get(provider_id, "Custom provider")
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
