"""Runtime configuration for RSS-to-Twitter Agent with Ollama."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "ollama/llama3.2")


def _check_ollama_running() -> bool:
    """Check if Ollama is running locally."""
    try:
        with httpx.Client() as client:
            resp = client.get(f"{OLLAMA_URL}/api/tags", timeout=2.0)
            return resp.status_code == 200
    except Exception:
        return False


def _get_model() -> str:
    return DEFAULT_MODEL


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
    if not _check_ollama_running():
        return (
            False,
            "Ollama is not running. Start it with `ollama serve` and ensure your model is pulled.",
        )
    return True, ""
