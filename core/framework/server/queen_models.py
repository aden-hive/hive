"""A queen's own model: ``queen_llm`` in configuration.json gives a queen a model of her own.

    "queen_llm": {"queen_archivist": {"provider": "openai", "model": "...", "api_base": "...", "api_key": "..."}}

Each entry has the ``llm`` slot's shape; a queen without one uses the ``llm`` slot. Her session
is built with her model when she is known up front (a chat opened with her, a channel, a resumed
session). When she is picked only once the session runs, or her entry changes while her sessions
run, her model is put on the session's provider in place, so everything holding it (her loop, her
tools, colony workers sharing it) switches with it.

Supported: a literal key, ``api_key_env_var`` or the credential store, any endpoint, and
``extra_body`` (a provider's thinking switch, ``reasoning_effort``). Not supported: the
subscription logins (Claude Code, Codex, Kimi, Antigravity).
"""

from __future__ import annotations

import logging
from typing import Any

from framework.config import (
    get_api_base,
    get_api_key,
    get_llm_extra_kwargs,
    get_preferred_model,
    get_queen_api_base,
    get_queen_api_key,
    get_queen_llm_section,
    section_extra_body,
    section_model,
)

logger = logging.getLogger(__name__)


def build(queen_id: str) -> Any | None:
    """A provider for the queen's own model, or ``None`` when she has none."""
    section = get_queen_llm_section(queen_id)
    if section is None:
        return None
    from framework.llm.litellm import LiteLLMProvider

    extra: dict[str, Any] = {"num_ctx": section.get("num_ctx", 16384)} if section.get("provider") == "ollama" else {}
    if extra_body := section_extra_body(section):
        extra["extra_body"] = extra_body
    return LiteLLMProvider(
        model=section_model(section),
        api_key=get_queen_api_key(queen_id),
        api_base=get_queen_api_base(queen_id),
        api_key_resolver=lambda: get_queen_api_key(queen_id),
        **extra,
    )


def apply(llm: Any, queen_id: str, *, default_model: str | None = None) -> bool:
    """Put the queen's model on ``llm`` in place: her own, or the main one when she has none.

    ``default_model`` is the main ``provider/model`` (the running server's, which may be newer
    than the file's). Returns whether ``llm`` could be switched.
    """
    if llm is None or not hasattr(llm, "reconfigure"):
        return False
    section = get_queen_llm_section(queen_id)
    if section is None:
        llm.reconfigure(
            default_model or get_preferred_model(),
            api_key=get_api_key(),
            api_base=get_api_base(),
            api_key_resolver=get_api_key,
            extra_body=get_llm_extra_kwargs().get("extra_body"),
        )
    else:
        llm.reconfigure(
            section_model(section),
            api_key=get_queen_api_key(queen_id),
            api_base=get_queen_api_base(queen_id),
            api_key_resolver=lambda: get_queen_api_key(queen_id),
            extra_body=section_extra_body(section),
        )
    logger.info("queen %s now uses %s", queen_id, getattr(llm, "model", "?"))
    return True


def has_own(queen_id: str | None) -> bool:
    return get_queen_llm_section(queen_id) is not None
