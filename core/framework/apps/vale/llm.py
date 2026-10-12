"""The vale's model calls, through Hive's LLM layer.

Villagers run as Hive agent loops (see ``villager.py``). Fate, the gods and the
chronicler make single JSON calls through :class:`HiveChat`, which keeps the small
``chat()`` interface the engine was written against.
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Any

from framework.llm.provider import LLMProvider

# Reasoning models put their thinking in the content; it is not the answer.
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def build_provider(settings: dict[str, Any] | None = None, *, temperature: float | None = None, timeout: float = 90.0) -> LLMProvider:
    """A provider from Hive's configuration, or from a game's own model override.

    ``settings`` may hold ``model`` (``provider/model``), ``api_base`` and ``api_key_env``.
    A model with its own ``api_base`` (a local OpenAI-compatible server, say) is used as is;
    otherwise Hive's configured key and base apply. ``timeout`` bounds each request, so a stream
    that stalls fails fast and is retried instead of holding a villager's turn until it times out.
    """
    from framework.config import RuntimeConfig, get_api_key
    from framework.llm.litellm import LiteLLMProvider

    s = settings or {}
    extra: dict[str, Any] = {"timeout": timeout} if temperature is None else {"temperature": temperature, "timeout": timeout}
    if s.get("model") and s.get("api_base"):
        key = os.environ.get(str(s.get("api_key_env") or ""), "") or "local"
        return LiteLLMProvider(model=s["model"], api_key=key, api_base=s["api_base"], **extra)
    rc = RuntimeConfig(model=s.get("model") or RuntimeConfig().model)
    return LiteLLMProvider(model=rc.model, api_key=rc.api_key, api_base=rc.api_base, api_key_resolver=get_api_key, **{**rc.extra_kwargs, **extra})


class HiveChat:
    """``chat(messages) -> str`` over Hive providers, one per temperature, with call accounting."""

    def __init__(self, settings: dict[str, Any] | None = None, *, factory=build_provider) -> None:
        self.settings = dict(settings or {})
        self._factory = factory
        self._providers: dict[float, LLMProvider] = {}
        self._lock = threading.Lock()
        self.calls = 0
        self.chars_in = 0
        self.chars_out = 0
        self.cost_usd = 0.0

    def provider(self, temperature: float) -> LLMProvider:
        key = round(float(temperature), 2)
        with self._lock:
            if key not in self._providers:
                self._providers[key] = self._factory(self.settings, temperature=key, timeout=150.0)  # fate and the gods write long replies
            return self._providers[key]

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.9, max_tokens: int = 900, json_mode: bool = True) -> str:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        rest = [m for m in messages if m["role"] != "system"]
        try:
            resp = self.provider(temperature).complete(rest, system=system, max_tokens=max_tokens, json_mode=json_mode)
        except Exception as exc:  # the engine treats any failed call as RuntimeError and carries on
            raise RuntimeError(f"model call failed: {exc}") from exc
        text = _THINK.sub("", resp.content or "").strip()
        self.count(len(system) + sum(len(m["content"]) for m in rest), len(text), getattr(resp, "cost_usd", 0.0))
        return text

    def count(self, chars_in: int, chars_out: int, cost_usd: float | None = 0.0) -> None:
        with self._lock:
            self.calls += 1
            self.chars_in += chars_in
            self.chars_out += chars_out
            self.cost_usd += float(cost_usd or 0.0)


def parse_json_object(text: str) -> dict:
    """The first JSON object in a model reply, tolerating fences and preamble."""
    text = _THINK.sub("", text).strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"no JSON object in reply: {text[:200]!r}") from None
        obj = json.loads(match.group(0))
    if not isinstance(obj, dict):
        raise ValueError(f"reply is JSON but not an object: {text[:200]!r}")
    return obj


# The engine's modules type their model as ``LLM``.
LLM = HiveChat
