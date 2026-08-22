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
agent's run. On a None return, the agent-loop call site falls back to
``gemini/gemini-3-flash-preview`` via the ``model_override`` parameter
of :func:`caption_tool_image`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from framework.config import (
    get_aux_max_tokens,
    get_hive_config,
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
# Coordinate labeling: the main agent's ``hive-browser interact`` command
# (left_click / hover / key actions with a ``--coordinate``)
# accepts VIEWPORT FRACTIONS (x, y) in [0..1] where (0,0) is the top-left
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
    "intent (their reasoning + the tool call) is below. The intent "
    "names a specific entity and target element — anchor your "
    "description on that entity, locate the target element, and "
    "provide its coordinates. Describe what the image shows in service "
    "of their intent — concrete, factual, no speculation. If their "
    "intent asks a yes/no question, answer it directly first.\n\n"
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


# Matches the (fx, fy) coordinate labels the vision subagent appends to
# element names, e.g. ``"Submit" button (0.83, 0.92)``. Both components
# are fractions in 0..1 (a bare 0 or 1 is also allowed).
_COORD_LABEL_RE = re.compile(r"\(\s*(\d?\.\d+|[01])\s*,\s*(\d?\.\d+|[01])\s*\)")


def crop_box_from_tool_result(tool_result_text: str | None) -> list[float] | None:
    """Pull a ``crop_box`` ([vx0, vy0, vx1, vy1]) out of an image tool's
    JSON text envelope.

    ``crop_box`` is the viewport-fraction rectangle a non-viewport image
    (zoom crop, element-clip or full_page screenshot) spans. Returns None
    for a plain viewport screenshot — no crop_box, or crop_box covering
    the whole viewport — since there is nothing to remap then. Degrades
    to None on any parse failure.
    """
    if not tool_result_text:
        return None
    try:
        meta = json.loads(tool_result_text.strip())
    except Exception:
        return None
    if not isinstance(meta, dict):
        return None
    cb = meta.get("crop_box")
    if not isinstance(cb, list) or len(cb) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in cb)
    except (TypeError, ValueError):
        return None
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    # Full viewport — coordinates already map 1:1, no remap needed.
    if abs(x0) < 1e-6 and abs(y0) < 1e-6 and abs(x1 - 1) < 1e-6 and abs(y1 - 1) < 1e-6:
        return None
    return [x0, y0, x1, y1]


def remap_caption_for_crop(caption: str, tool_result_text: str | None) -> str:
    """Rewrite the vision subagent's (fx, fy) coordinate labels from
    crop-relative fractions into full-viewport fractions.

    When the captioned image was a crop (a ``zoom`` action, or an
    element-clip / full_page screenshot) the subagent — which only ever
    sees "an image" — labels positions relative to that crop. A
    coordinate click expects viewport fractions, so without this a
    text-only main model would click the right fraction of the wrong
    rectangle. The crop's viewport span comes from ``crop_box`` in the
    tool result.

    No-op when the result carries no crop_box (plain viewport
    screenshot) or the caption has no coordinate labels.
    """
    crop_box = crop_box_from_tool_result(tool_result_text)
    if not crop_box:
        return caption
    x0, y0, x1, y1 = crop_box
    w, h = x1 - x0, y1 - y0

    def _remap(m: re.Match[str]) -> str:
        try:
            fx, fy = float(m.group(1)), float(m.group(2))
        except ValueError:
            return m.group(0)
        # Coordinate labels are fractions in 0..1; anything else in
        # parentheses isn't one of ours — leave it untouched.
        if not (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
            return m.group(0)
        return f"({round(x0 + fx * w, 4)}, {round(y0 + fy * h, 4)})"

    return _COORD_LABEL_RE.sub(_remap, caption)


def extract_intent_for_tool(
    conversation: NodeConversation,
    tool_name: str,
    tool_args: dict[str, Any] | None,
) -> str:
    """Build the intent string passed to the vision subagent.

    If the tool call included an explicit ``intent`` argument (e.g. the
    required ``--intent`` flag on ``hive-browser screenshot`` and on
    ``hive-browser interact --action screenshot``), that is used verbatim —
    it already names the entity, target element, and planned action.

    Otherwise falls back to combining the most recent assistant text
    with a structured tool-call descriptor, truncated to
    ``_INTENT_MAX_CHARS``.
    """
    # Explicit intent from tool args (hive-browser screenshot / interact
    # --action screenshot — both take a required ``intent``).
    explicit = (tool_args or {}).get("intent", "").strip()
    if not explicit:
        # Screenshots run via terminal_exec carry their --intent INSIDE the
        # command string (there's no structured `intent` arg on terminal_exec),
        # so pull it out — otherwise the caption a text-only model receives loses
        # the entity/target/action the agent named.
        cmd = (tool_args or {}).get("command")
        if isinstance(cmd, str) and "hive-browser" in cmd:
            mi = re.search(r"--intent(?:=|\s+)(\"[^\"]*\"|'[^']*'|\S+)", cmd)
            if mi:
                explicit = mi.group(1).strip("\"'").strip()
    if explicit:
        return f"Agent intent: {explicit}"

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
        assistant_text = ""

    if not assistant_text:
        assistant_text = "<no preceding reasoning>"

    # Intent = tool descriptor (always intact) + reasoning (truncated).
    head = f"{tool_line}\n\nReasoning before call:\n"
    budget = _INTENT_MAX_CHARS - len(head)
    if budget < 100:
        return head[:_INTENT_MAX_CHARS]
    if len(assistant_text) > budget:
        assistant_text = assistant_text[: budget - 1] + "…"
    return head + assistant_text


async def caption_tool_image(
    intent: str,
    image_content: list[dict[str, Any]],
    *,
    timeout_s: float = 30.0,
    model_override: str | None = None,
) -> tuple[str, str] | None:
    """Caption the given images using the configured ``vision_fallback`` model.

    Returns ``(caption, model)`` on success or ``None`` on any failure
    (no config, no API key, timeout, exception, empty response).

    ``model_override`` swaps in a different litellm model id while
    keeping the configured ``vision_fallback`` ``api_key`` / ``api_base``
    untouched. That's deliberate: Hive subscribers configure
    ``vision_fallback`` to point at the Hive proxy, which routes to
    multiple models including Gemini — so reusing the credentials lets
    a Gemini-3-flash override still work without a separate
    ``GEMINI_API_KEY``. When no creds are configured, litellm falls
    back to env-var resolution.

    Logs each call to ``~/.hive/llm_logs`` via ``log_llm_turn``.
    """
    model = model_override or get_vision_fallback_model()
    if not model:
        return None
    api_key = get_vision_fallback_api_key()
    api_base = get_vision_fallback_api_base()
    if not api_key and not model_override:
        logger.info(
            "vision_fallback configured (%s) but no API key resolved (literal api_key / env %s both empty); skipping",
            model,
            get_hive_config().get("vision_fallback", {}).get("api_key_env_var"),
        )
        return None

    try:
        import litellm
    except ImportError:
        return None

    user_blocks: list[dict[str, Any]] = [{"type": "text", "text": intent}]
    # Only include attachments with valid data URIs — skip hive:// or other
    # non-fetchable URLs that would cause "unsupported image format" errors.
    # Two block shapes are accepted:
    #   * legacy {"type":"image_url","image_url":{"url":"data:image/...|data:application/pdf;..."}}
    #   * native {"type":"file","file":{"file_data":"data:application/pdf;..."}} —
    #     emitted by the chat upload path so LiteLLM auto-remaps to each
    #     provider's native PDF shape (Anthropic `document`, Gemini
    #     `inline_data`, OpenAI native `file`).
    for block in image_content:
        block_type = block.get("type") if isinstance(block, dict) else None
        if block_type == "image_url":
            iu = block.get("image_url")
            url = iu.get("url", "") if isinstance(iu, dict) else ""
            if url.startswith("data:image/") or url.startswith("data:application/pdf"):
                user_blocks.append(block)
        elif block_type == "file":
            file_obj = block.get("file")
            file_data = file_obj.get("file_data", "") if isinstance(file_obj, dict) else ""
            if file_data.startswith("data:application/pdf"):
                user_blocks.append(block)
    if len(user_blocks) <= 1:
        # No valid attachments to describe
        return None
    messages = [
        {"role": "system", "content": _VISION_SUBAGENT_SYSTEM},
        {"role": "user", "content": user_blocks},
    ]

    # Apply the same proxy rewrites the main LLM provider uses so a
    # `hive/...` / `kimi/...` model resolves to the right Anthropic-
    # compatible endpoint with the right auth header. Without this,
    # litellm doesn't know what `hive/kimi-k2.x` is and rejects the call
    # with "LLM Provider NOT provided."
    from framework.llm.litellm import rewrite_proxy_model

    rewritten_model, rewritten_base, extra_headers = rewrite_proxy_model(model, api_key, api_base)

    kwargs: dict[str, Any] = {
        "model": rewritten_model,
        "messages": messages,
        "max_tokens": int(
            get_hive_config().get("vision_fallback", {}).get("max_tokens")
            or get_aux_max_tokens()
        ),
        "timeout": timeout_s,
    }
    # Always pass api_key when we have one, even alongside proxy-rewritten
    # extra_headers. litellm's anthropic handler refuses to dispatch
    # without an api_key (it sends it as x-api-key); the proxy itself
    # authenticates via the Authorization: Bearer header in
    # extra_headers. Both are needed — matches LiteLLMProvider's path.
    if api_key:
        kwargs["api_key"] = api_key
    if rewritten_base:
        kwargs["api_base"] = rewritten_base
    if extra_headers:
        kwargs["extra_headers"] = extra_headers
        # rewrite_proxy_model returns non-empty extra_headers ONLY for
        # Hive-proxy-bound calls, so this is the right gate to stamp
        # X-Hive-Agent for cloud usage attribution. Off for direct
        # Anthropic/Kimi/OpenRouter traffic.
        try:
            from framework.tasks.tools._context import current_usage_agent_id

            agent_id = current_usage_agent_id()
            if agent_id:
                kwargs["extra_headers"] = {**kwargs["extra_headers"], "X-Hive-Agent": agent_id}
        except Exception:
            pass

    # Surface where the request is going so the user can verify the
    # vision fallback is hitting the expected proxy / model. Redacts
    # the API key to a length+head+tail digest matching the
    # [auth] runtime-spawn line so they can be cross-correlated.
    key_digest = f"len={len(api_key)} {api_key[:8]}…{api_key[-4:]}" if api_key and len(api_key) >= 12 else f"len={len(api_key) if api_key else 0}"
    logger.info(
        "[vision_fallback] dispatching: configured_model=%s rewritten_model=%s api_base=%s api_key=%s images=%d intent_chars=%d timeout_s=%.1f",
        model,
        rewritten_model,
        rewritten_base or "<litellm-default>",
        key_digest,
        len(image_content),
        len(intent),
        timeout_s,
    )

    started = datetime.now()
    caption: str | None = None
    error_text: str | None = None
    try:
        from framework.llm.litellm import _log_llm_call

        _log_llm_call(kwargs)
        response = await litellm.acompletion(**kwargs)
        text = (response.choices[0].message.content or "").strip()
        if text:
            caption = text
        logger.info(
            "[vision_fallback] response: model=%s api_base=%s elapsed_s=%.2f chars=%d",
            rewritten_model,
            rewritten_base or "<litellm-default>",
            (datetime.now() - started).total_seconds(),
            len(text),
        )
    except asyncio.CancelledError:
        # CancelledError is BaseException, not Exception — without this
        # branch it would unwind past the audit log below, leaving no
        # record of the cancelled subagent call. Log inline, then
        # re-raise so the parent's cancel propagation is unchanged.
        try:
            from framework.tracker.llm_debug_logger import log_llm_turn

            elided_blocks: list[dict[str, Any]] = [{"type": "text", "text": intent}]
            elided_blocks.extend({"type": "image_url", "image_url": {"url": "<elided>"}} for _ in range(len(image_content)))
            log_llm_turn(
                node_id="vision_fallback_subagent",
                stream_id="vision_fallback",
                execution_id="vision_fallback_subagent",
                iteration=0,
                system_prompt=_VISION_SUBAGENT_SYSTEM,
                messages=[{"role": "user", "content": elided_blocks}],
                assistant_text="",
                tool_calls=[],
                tool_results=[],
                token_counts={
                    "model": model,
                    "elapsed_s": (datetime.now() - started).total_seconds(),
                    "error": "cancelled",
                    "stop_reason": "cancelled",
                    "num_images": len(image_content),
                    "intent_chars": len(intent),
                },
            )
        except Exception:
            pass
        raise
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "[vision_fallback] failed: model=%s api_base=%s error=%s",
            rewritten_model,
            rewritten_base or "<litellm-default>",
            error_text,
        )

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

    if caption is None:
        return None
    return caption, model


__all__ = ["caption_tool_image", "extract_intent_for_tool"]
