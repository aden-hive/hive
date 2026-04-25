"""Vision-fallback subagent for tool-result images on text-only LLMs.

When a tool returns image content but the main agent's model can't
accept image blocks (i.e. its catalog entry has ``supports_vision: false``),
the framework strips the images before they ever reach the LLM. Without
this module, the agent then sees only the tool's text envelope (URL,
dimensions, size) and is blind to whatever the image actually shows.

This module provides:

* ``caption_tool_image()`` — direct LiteLLM call to a configured
  vision model (``vision_fallback`` block in ``~/.hive/configuration.json``)
  that takes the agent's intent + the image(s) and returns a textual
  description tailored to that intent.
* ``extract_intent_for_tool()`` — pull the most recent assistant text
  + the tool call descriptor and concatenate them into a ≤2KB intent
  string the vision subagent can reason against.

Both helpers degrade silently — return ``None`` / a placeholder rather
than raise — so a vision-fallback failure can never kill the main
agent's run. The agent-loop call site is responsible for chaining
through to the existing generic-caption rotation
(``_describe_images_as_text``) on a None return.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from framework.config import (
    get_vision_fallback_api_base,
    get_vision_fallback_api_key,
    get_vision_fallback_model,
)

if TYPE_CHECKING:
    from ..conversation import NodeConversation

logger = logging.getLogger(__name__)


# Hard cap on the intent string handed to the vision subagent. The
# subagent only needs the agent's recent reasoning + the tool descriptor;
# anything longer is wasted tokens (and risks pushing past the vision
# model's context with the image attached).
_INTENT_MAX_CHARS = 4096

# Cap on the tool args JSON snippet inside the intent. Some tool inputs
# (large strings, file contents) would dominate the intent if uncapped.
_TOOL_ARGS_MAX_CHARS = 4096

# Subagent system prompt — kept short so it fits within any provider's
# system-prompt budget alongside the user message + image. Tells the
# subagent its role and constrains output format.
#
# Coordinate labeling: the main agent's browser tools
# (browser_click_coordinate / browser_hover_coordinate / browser_press_at)
# accept VIEWPORT FRACTIONS (x, y) in [0..1] where (0,0) is the top-left
# and (1,1) is the bottom-right of the screenshot. Without coordinates
# the text-only agent has no way to act on what we describe — it can
# read the caption but cannot point. So for every interactive element
# we name (button, link, input, icon, tab, menu item, dialog control),
# include its approximate viewport-fraction centre as ``(fx, fy)``
# right after the element's name, e.g. ``"Submit" button (0.83, 0.92)``.
# Three rules: (1) coordinates only for things plausibly clickable /
# hoverable / typeable — don't tag pure body text or decorative
# graphics. (2) Eyeball to two decimal places; precision beyond that
# is false confidence. (3) Never invent — if an element is partly
# off-screen or you can't locate it, omit the coordinate rather than
# guessing.
_VISION_SUBAGENT_SYSTEM = (
    "You are a vision subagent for a text-only main agent. The main "
    "agent invoked a tool that returned the image(s) attached. Their "
    "intent (their reasoning + the tool call) is below. Describe what "
    "the image shows in service of their intent — concrete, factual, "
    "no speculation. If their intent asks a yes/no question, answer it "
    "directly first.\n\n"
    "Coordinate labeling: the main agent uses fractional viewport "
    "coordinates (x, y) in [0..1] — (0, 0) is the top-left of the "
    "image, (1, 1) is the bottom-right — to drive its click / hover / "
    "key-press tools. For every interactive element you mention "
    "(button, link, input, checkbox, radio, dropdown, tab, menu item, "
    "dialog control, icon), append its approximate centre as "
    "``(fx, fy)`` immediately after the element's name or label, e.g. "
    '``"Submit" button (0.83, 0.92)`` or ``profile avatar icon '
    "(0.05, 0.07)``. Use two decimal places — more is false precision. "
    "Skip coordinates for pure body text and decorative elements that "
    "aren't clickable. If an element is partially off-screen or you "
    "cannot reliably locate its centre, omit the coordinate rather "
    "than guessing.\n\n"
    "Output plain text, no markdown, ≤ 600 words."
)


def extract_intent_for_tool(
    conversation: NodeConversation,
    tool_name: str,
    tool_args: dict[str, Any] | None,
) -> str:
    """Build the intent string passed to the vision subagent.

    Combines the most recent assistant text (the LLM's reasoning right
    before invoking the tool) with a structured tool-call descriptor.
    Truncates to ``_INTENT_MAX_CHARS`` total, favouring the head of the
    assistant text where goal-stating sentences usually live.

    If no preceding assistant text exists (rare — first turn), falls
    back to ``"<no preceding reasoning>"`` so the subagent still gets
    the tool descriptor.
    """
    args_json: str
    try:
        args_json = json.dumps(tool_args or {}, default=str)
    except Exception:
        args_json = repr(tool_args)
    if len(args_json) > _TOOL_ARGS_MAX_CHARS:
        args_json = args_json[:_TOOL_ARGS_MAX_CHARS] + "…"

    tool_line = f"Called: {tool_name}({args_json})"

    # Walk newest → oldest, take the first assistant message with text.
    assistant_text = ""
    try:
        messages = getattr(conversation, "_messages", []) or []
        for msg in reversed(messages):
            if getattr(msg, "role", None) != "assistant":
                continue
            content = getattr(msg, "content", "") or ""
            if isinstance(content, str) and content.strip():
                assistant_text = content.strip()
                break
    except Exception:
        # Defensive — the agent loop must keep running even if the
        # conversation structure changes shape.
        assistant_text = ""

    if not assistant_text:
        assistant_text = "<no preceding reasoning>"

    # Intent = tool descriptor (always intact) + reasoning (truncated).
    head = f"{tool_line}\n\nReasoning before call:\n"
    budget = _INTENT_MAX_CHARS - len(head)
    if budget < 100:
        # Tool descriptor is huge somehow — truncate it.
        return head[:_INTENT_MAX_CHARS]
    if len(assistant_text) > budget:
        assistant_text = assistant_text[: budget - 1] + "…"
    return head + assistant_text


async def caption_tool_image(
    intent: str,
    image_content: list[dict[str, Any]],
    *,
    timeout_s: float = 30.0,
) -> str | None:
    """Caption the given images using the configured ``vision_fallback`` model.

    Returns the model's text response on success, or ``None`` on any
    failure (no config, no API key, timeout, exception, empty
    response). Callers chain to the next stage of the fallback on None.

    Logs each call to ``~/.hive/llm_logs`` via ``log_llm_turn`` so the
    cost / latency / quality are auditable post-hoc, tagged with
    ``execution_id="vision_fallback_subagent"``.
    """
    model = get_vision_fallback_model()
    if not model:
        return None

    api_key = get_vision_fallback_api_key()
    api_base = get_vision_fallback_api_base()
    if not api_key:
        logger.debug("vision_fallback configured but no API key resolved; skipping")
        return None

    try:
        import litellm
    except ImportError:
        return None

    user_blocks: list[dict[str, Any]] = [{"type": "text", "text": intent}]
    user_blocks.extend(image_content)
    messages = [
        {"role": "system", "content": _VISION_SUBAGENT_SYSTEM},
        {"role": "user", "content": user_blocks},
    ]

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": 1024,
        "timeout": timeout_s,
        "api_key": api_key,
    }
    if api_base:
        kwargs["api_base"] = api_base

    started = datetime.now()
    caption: str | None = None
    error_text: str | None = None
    try:
        response = await litellm.acompletion(**kwargs)
        text = (response.choices[0].message.content or "").strip()
        if text:
            caption = text
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        logger.debug("vision_fallback model '%s' failed: %s", model, exc)

    # Best-effort audit log so users can grep ~/.hive/llm_logs/ for
    # vision-fallback subagent calls. Failures here must not bubble.
    try:
        from framework.tracker.llm_debug_logger import log_llm_turn

        # Don't dump the base64 image data into the log file — that
        # would balloon the jsonl with mostly-binary noise.
        elided_blocks: list[dict[str, Any]] = [{"type": "text", "text": intent}]
        elided_blocks.extend({"type": "image_url", "image_url": {"url": "<elided>"}} for _ in range(len(image_content)))
        log_llm_turn(
            node_id="vision_fallback_subagent",
            stream_id="vision_fallback",
            execution_id="vision_fallback_subagent",
            iteration=0,
            system_prompt=_VISION_SUBAGENT_SYSTEM,
            messages=[{"role": "user", "content": elided_blocks}],
            assistant_text=caption or "",
            tool_calls=[],
            tool_results=[],
            token_counts={
                "model": model,
                "elapsed_s": (datetime.now() - started).total_seconds(),
                "error": error_text,
                "num_images": len(image_content),
                "intent_chars": len(intent),
            },
        )
    except Exception:
        pass

    return caption


__all__ = ["caption_tool_image", "extract_intent_for_tool"]
