"""List chat/generation-capable models for a provider using the user's API key.

Usage:
    python scripts/list_provider_models.py <provider_id> <api_key> [api_base]

Output JSON:
    {
      "ok": true|false,
      "message": "...",
      "models": [
        {
          "id": "model-id",
          "label": "Display Name",
          "max_tokens": 8192,
          "max_context_tokens": 120000
        }
      ]
    }
"""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx

TIMEOUT = 15.0

OPENAI_COMPAT_ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/models",
    "groq": "https://api.groq.com/openai/v1/models",
    "cerebras": "https://api.cerebras.ai/v1/models",
}


def _to_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_model(
    model_id: str,
    label: str,
    max_tokens: int,
    max_context_tokens: int,
) -> dict[str, Any]:
    return {
        "id": model_id.strip(),
        "label": label.strip() or model_id.strip(),
        "max_tokens": max(1, int(max_tokens)),
        "max_context_tokens": max(1, int(max_context_tokens)),
    }


def _list_openai_compatible(api_key: str, endpoint: str, provider_id: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(endpoint, headers={"Authorization": f"Bearer {api_key}"})
    resp.raise_for_status()
    payload = resp.json()

    models: list[dict[str, Any]] = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id", "")).strip()
        if not mid:
            continue

        lower = mid.lower()
        # OpenAI /models can include non-chat models. Keep only chat/reasoning families.
        if provider_id == "openai":
            if not (
                lower.startswith("gpt-")
                or lower.startswith("o1")
                or lower.startswith("o3")
                or lower.startswith("o4")
                or lower.startswith("o5")
                or lower.startswith("chatgpt-")
                or lower.startswith("codex-")
            ):
                continue

        max_ctx = _to_int(
            item.get("context_window") or item.get("input_token_limit"),
            120000,
        )
        max_out = _to_int(
            item.get("max_output_tokens")
            or item.get("output_token_limit")
            or item.get("max_completion_tokens"),
            8192,
        )
        models.append(_normalize_model(mid, mid, max_out, max_ctx))

    models.sort(key=lambda m: m["id"])
    return models


def _list_gemini(api_key: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": api_key},
        )
    resp.raise_for_status()
    payload = resp.json()

    models: list[dict[str, Any]] = []
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        model_id = name.split("/", 1)[1] if "/" in name else name
        if not model_id.startswith("gemini"):
            continue
        methods = item.get("supportedGenerationMethods") or []
        if isinstance(methods, list) and "generateContent" not in methods:
            continue

        label = str(item.get("displayName", "")).strip() or model_id
        max_ctx = _to_int(item.get("inputTokenLimit"), 120000)
        max_out = _to_int(item.get("outputTokenLimit"), 8192)
        models.append(_normalize_model(model_id, label, max_out, max_ctx))

    models.sort(key=lambda m: m["id"])
    return models


def _list_anthropic(api_key: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
    resp.raise_for_status()
    payload = resp.json()

    models: list[dict[str, Any]] = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id", "")).strip()
        if not mid or not mid.startswith("claude"):
            continue
        label = str(item.get("display_name", "")).strip() or mid
        max_out = _to_int(item.get("max_output_tokens"), 8192)
        max_ctx = _to_int(item.get("context_window"), 180000)
        models.append(_normalize_model(mid, label, max_out, max_ctx))

    models.sort(key=lambda m: m["id"])
    return models


def main() -> None:
    if len(sys.argv) < 3:
        print(json.dumps({"ok": False, "message": "Usage: list_provider_models.py <provider> <key> [api_base]"}))
        sys.exit(2)

    provider_id = sys.argv[1].strip().lower()
    api_key = sys.argv[2].strip()
    api_base = sys.argv[3].strip() if len(sys.argv) > 3 else ""

    try:
        if provider_id in OPENAI_COMPAT_ENDPOINTS:
            endpoint = api_base.rstrip("/") + "/models" if api_base else OPENAI_COMPAT_ENDPOINTS[provider_id]
            models = _list_openai_compatible(api_key, endpoint, provider_id)
        elif provider_id == "gemini":
            models = _list_gemini(api_key)
        elif provider_id == "anthropic":
            models = _list_anthropic(api_key)
        else:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "message": f"Dynamic model listing is not implemented for provider '{provider_id}'.",
                        "models": [],
                    }
                )
            )
            sys.exit(1)

        if not models:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "message": f"No supported models returned for provider '{provider_id}'.",
                        "models": [],
                    }
                )
            )
            sys.exit(1)

        print(json.dumps({"ok": True, "message": "ok", "models": models}))
        sys.exit(0)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else "?"
        print(
            json.dumps(
                {
                    "ok": False,
                    "message": f"Provider API returned HTTP {status} for '{provider_id}'.",
                    "models": [],
                }
            )
        )
        sys.exit(1)
    except httpx.RequestError as e:
        print(json.dumps({"ok": False, "message": f"Network error: {e}", "models": []}))
        sys.exit(2)
    except Exception as e:
        print(json.dumps({"ok": False, "message": f"Unexpected error: {e}", "models": []}))
        sys.exit(1)


if __name__ == "__main__":
    main()
