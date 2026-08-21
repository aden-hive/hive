"""Runtime configuration for RSS-to-Twitter Agent with Ollama."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "ollama/llama3.2")


def get_ollama_url() -> str:
    """Return the configured Ollama base URL without a trailing slash."""
    return OLLAMA_URL.rstrip("/")


def get_ollama_model() -> str:
    """Return the configured Ollama model name without the provider prefix."""
    model = os.environ.get("OLLAMA_MODEL") or DEFAULT_MODEL
    return model.removeprefix("ollama/")


def _fetch_ollama_tags() -> list[dict[str, Any]] | None:
    """Fetch Ollama model metadata, returning None when the service is unavailable."""
    try:
        with httpx.Client() as client:
            resp = client.get(f"{get_ollama_url()}/api/tags", timeout=2.0)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None
    models = data.get("models", [])
    return models if isinstance(models, list) else []


def _get_model() -> str:
    return get_ollama_model()


def _model_available(models: list[dict[str, Any]], configured_model: str) -> bool:
    """Match configured model names regardless of optional Ollama tag/provider prefixes."""
    configured_short = configured_model.split(":", 1)[0]
    for model in models:
        name = model.get("name")
        if not isinstance(name, str) or not name:
            continue
        if name == configured_model or name.split(":", 1)[0] == configured_short:
            return True
    return False


@dataclass
class RuntimeConfig:
    model: str = field(default_factory=_get_model)
    temperature: float = 0.7
    max_tokens: int = 8000
    api_key: str | None = os.environ.get("LLM_API_KEY")
    api_base: str | None = os.environ.get("LLM_API_BASE")


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "RSS-to-Twitter Agent"
    version: str = "1.1.0"
    description: str = (
        "Automated content repurposing from RSS feeds to Twitter threads. "
        "Uses Ollama for local LLM inference and Playwright for automated posting."
    )


metadata = AgentMetadata()


def validate_ollama() -> tuple[bool, str]:
    models = _fetch_ollama_tags()
    configured_model = get_ollama_model()
    if models is None:
        return (
            False,
            "Ollama is not running. Start it with `ollama serve` and ensure your model is pulled.",
        )
    if not _model_available(models, configured_model):
        return (
            False,
            f"Ollama model '{configured_model}' is not available. "
            f"Pull it with `ollama pull {configured_model}` or update LLM_MODEL/OLLAMA_MODEL.",
        )
    return True, ""
