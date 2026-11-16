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


# Model prefixes routed to the Anthropic Messages API — the one API we
# speak whose tool-result block can itself hold images. ``kimi/`` and
# ``hive/`` are Anthropic-compatible proxies that ``rewrite_proxy_model``
# turns into ``anthropic/`` before the request goes out.
_ANTHROPIC_ROUTED_PREFIXES = (
    "anthropic/",
    "claude-",
    "kimi/",
    "hive/",
    "openrouter/anthropic/",
)


def supports_images_in_tool_results(model: str) -> bool:
    """Return whether *model*'s API carries image blocks inside a tool message.

    Anthropic's ``tool_result`` content can hold image blocks, so a
    screenshot rides along with the tool result that produced it. No other
    API we speak does: OpenAI chat completions (and every OpenAI-compatible
    proxy) and Gemini's ``functionResponse`` carry text there and drop image
    parts *silently* — no 400, no warning, just a model that insists it
    cannot see the screenshot it just took. Which is accurate: nothing
    reached it.

    Callers getting ``False`` should move the images into a following
    ``user`` message — see ``NodeConversation._hoist_tool_result_images``.
    Every vision-capable API accepts images there.

    Empty model strings are treated as capable, matching
    :func:`supports_image_tool_results`, so the default path doesn't
    reshape messages before a provider is selected.
    """
    if not model:
        return True
    return model.lower().startswith(_ANTHROPIC_ROUTED_PREFIXES)
