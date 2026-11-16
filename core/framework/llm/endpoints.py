"""Named OpenAI-compatible endpoints that serve models: Magpie, Ollama, vLLM, LM Studio, a gateway.

configuration.json ``model_endpoints`` maps a name to ``{"api_base": ...}``. ``magpie`` is there even
when not written, at Magpie's own address on this computer (https://github.com/yetone/magpie, a
gateway in front of many vendors, subscriptions and routing groups). An endpoint's key lives in the
credential store (``endpoint_<name>``), never in configuration.json. An endpoint with none (a gateway
on this computer) is sent a placeholder, so no ambient key such as ``OPENAI_API_KEY`` ever reaches it.

A model slot served from one names it (``"endpoint": "<name>"``) beside its provider ("openai"),
model and ``api_base``; :mod:`framework.config` takes its key from here. Its models are listed live
from ``GET {api_base}/models``.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

MAGPIE = "magpie"
MAGPIE_API_BASE = "http://127.0.0.1:3425/v1"
# What a keyless request carries: litellm's OpenAI client needs a key, and given none it falls back
# to OPENAI_API_KEY. Magpie documents "magpie" as the key for clients on its own computer.
_PLACEHOLDER = {MAGPIE: "magpie"}
_NO_KEY = "no-key"
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_LIST_TTL_S = 60.0
_LIST_TIMEOUT_S = 10.0
_PROBE_TIMEOUT_S = 1.0
# Fields an endpoint's /models may carry its context window in (OpenRouter, vLLM, LM Studio, others).
_CONTEXT_FIELDS = ("context_length", "max_model_len", "max_context_tokens", "context_window")
# Fields it may carry a readable name in (Magpie's says where the model comes from too).
_LABEL_FIELDS = ("magpie_label", "display_name", "name")


class EndpointError(Exception):
    """An endpoint that can't be used now; the message says why."""


@dataclass(frozen=True)
class Endpoint:
    name: str
    api_base: str
    #: Magpie, present without being configured.
    builtin: bool


def valid_name(name: str) -> bool:
    """Lowercase letters, digits, ``_`` and ``-``; it names a credential and a part of the URL."""
    return bool(_NAME.match(name))


def endpoints() -> dict[str, Endpoint]:
    """Every endpoint: Magpie, and those in ``model_endpoints``."""
    from framework.config import get_hive_config

    found = {MAGPIE: Endpoint(MAGPIE, MAGPIE_API_BASE, True)}
    raw = get_hive_config().get("model_endpoints")
    for name, entry in raw.items() if isinstance(raw, dict) else ():
        base = entry.get("api_base") if isinstance(entry, dict) else None
        if isinstance(name, str) and valid_name(name) and isinstance(base, str) and base.strip():
            found[name] = Endpoint(name, base.strip().rstrip("/"), name == MAGPIE)
    return found


def get(name: str) -> Endpoint | None:
    return endpoints().get(name)


def credential_id(name: str) -> str:
    return f"endpoint_{name}"


def stored_key(name: str) -> str | None:
    """The endpoint's key from the credential store, if one was saved."""
    if not os.environ.get("HIVE_CREDENTIAL_KEY"):
        return None
    try:
        from framework.credentials import CredentialStore

        return CredentialStore.with_encrypted_storage().get(credential_id(name)) or None
    except Exception:
        return None


def key_for(name: str) -> str:
    """The key to send ``name``: its own, or the placeholder that keeps an ambient key away from it."""
    return stored_key(name) or _PLACEHOLDER.get(name, _NO_KEY)


_cache: dict[str, tuple[float, str, list[dict[str, Any]]]] = {}
_cache_lock = threading.Lock()


def list_models(name: str, *, fresh: bool = False) -> list[dict[str, Any]]:
    """Its models, from ``GET {api_base}/models`` (kept a minute): ``{"id", "label", "max_context_tokens"}`` each.

    Raises :class:`EndpointError` with the reason when it can't be listed.
    """
    endpoint = get(name)
    if endpoint is None:
        raise EndpointError(f"There's no endpoint {name!r}")
    with _cache_lock:
        cached = _cache.get(name)
    if not fresh and cached is not None and cached[1] == endpoint.api_base and time.monotonic() - cached[0] < _LIST_TTL_S:
        return cached[2]
    models = _fetch(endpoint, timeout=_LIST_TIMEOUT_S)
    with _cache_lock:
        _cache[name] = (time.monotonic(), endpoint.api_base, models)
    return models


def probe(name: str) -> bool:
    """Whether ``name`` answers its /models within a second (whether Magpie is running, say)."""
    endpoint = get(name)
    if endpoint is None:
        return False
    try:
        models = _fetch(endpoint, timeout=_PROBE_TIMEOUT_S)
    except EndpointError:
        return False
    with _cache_lock:
        _cache[name] = (time.monotonic(), endpoint.api_base, models)
    return True


def forget(name: str) -> None:
    """Drop the cached list, after the endpoint or its key changed."""
    with _cache_lock:
        _cache.pop(name, None)


def _fetch(endpoint: Endpoint, *, timeout: float) -> list[dict[str, Any]]:
    url = f"{endpoint.api_base}/models"
    try:
        response = httpx.get(url, headers={"Authorization": f"Bearer {key_for(endpoint.name)}"}, timeout=timeout)
    except httpx.HTTPError as e:
        raise EndpointError(f"Can't reach {url}: {e.__class__.__name__}") from e
    if response.status_code in (401, 403):
        raise EndpointError(f"{url} refused the key (HTTP {response.status_code})")
    if response.status_code != 200:
        raise EndpointError(f"{url} answered HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as e:
        raise EndpointError(f"{url} didn't answer with JSON") from e
    items = body.get("data") if isinstance(body, dict) else body
    if not isinstance(items, list):
        raise EndpointError(f"{url} didn't answer with a list of models")
    models = []
    for item in items:
        model_id = item.get("id") if isinstance(item, dict) else item
        if isinstance(model_id, str) and model_id:
            details = item if isinstance(item, dict) else {}
            models.append({"id": model_id, "label": _label_of(details), "max_context_tokens": _context_of(details)})
    return sorted(models, key=lambda m: m["id"].lower())


def _label_of(item: dict[str, Any]) -> str | None:
    for field in _LABEL_FIELDS:
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _context_of(item: dict[str, Any]) -> int | None:
    for field in _CONTEXT_FIELDS:
        value = item.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None
