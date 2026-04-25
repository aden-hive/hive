"""Model capability checks for LLM providers.

Vision support is sourced from the curated ``model_catalog.json``. Each model
entry carries an optional ``supports_vision`` boolean; unknown models default
to vision-capable so hosted frontier models work out of the box. To toggle
support for a model, edit its catalog entry rather than this file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from framework.llm.model_catalog import model_supports_vision

if TYPE_CHECKING:
    from framework.llm.provider import Tool


def supports_image_tool_results(model: str) -> bool:
    """Return whether *model* can receive image content in messages.

    Thin wrapper over :func:`model_supports_vision` so existing call sites
    keep working. Used to gate both user-message images and tool-result
    image blocks. Empty model strings are treated as capable so the default
    code path doesn't strip images before a provider is selected.
    """
    if not model:
        return True
    return model_supports_vision(model)


def filter_tools_for_model(tools: list[Tool], model: str) -> tuple[list[Tool], list[str]]:
    """Drop image-producing tools for text-only models.

    Returns ``(filtered_tools, hidden_names)``. For vision-capable models
    (or when *model* is empty) the input list is returned unchanged and
    ``hidden_names`` is empty. For text-only models any tool with
    ``produces_image=True`` is removed so the LLM never sees it in its
    schema — avoids wasted calls and stale "screenshot failed" entries
    in agent memory.
    """
    if not model or supports_image_tool_results(model):
        return list(tools), []
    hidden = [t.name for t in tools if t.produces_image]
    if not hidden:
        return list(tools), []
    kept = [t for t in tools if not t.produces_image]
    return kept, hidden
