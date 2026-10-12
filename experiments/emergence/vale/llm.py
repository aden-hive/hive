"""A tiny OpenAI-compatible chat client (stdlib only)."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any


class LLM:
    def __init__(self, base: str | None = None, model: str | None = None, key: str | None = None, timeout: float = 240) -> None:
        self.base = (base or os.environ.get("VALE_API_BASE") or "http://127.0.0.1:8790/v1").rstrip("/")
        self.model = model or os.environ.get("VALE_MODEL") or "gpt-6.1-sol"
        self.key = key or os.environ.get("VALE_API_KEY") or "local"
        self.timeout = timeout
        self.calls = 0
        self.chars_in = 0
        self.chars_out = 0
        self._lock = threading.Lock()

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.9, max_tokens: int = 900, json_mode: bool = True) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        data = json.dumps(body).encode("utf-8")
        last: Exception | None = None
        for attempt in range(5):
            req = urllib.request.Request(
                self.base + "/chat/completions",
                data=data,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"},
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                text = payload["choices"][0]["message"]["content"] or ""
                with self._lock:
                    self.calls += 1
                    self.chars_in += sum(len(m["content"]) for m in messages)
                    self.chars_out += len(text)
                return text
            except (urllib.error.URLError, TimeoutError, ConnectionError, KeyError, IndexError, json.JSONDecodeError) as exc:
                last = exc
                time.sleep(min(30, 2 ** attempt))
        raise RuntimeError(f"model call to {self.base} failed after 5 attempts: {last}")


def parse_json_object(text: str) -> dict:
    """The first JSON object in a model reply, tolerating fences and preamble."""
    text = text.strip()
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
