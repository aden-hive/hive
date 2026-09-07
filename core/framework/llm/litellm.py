"""LiteLLM provider for pluggable multi-provider LLM support.

LiteLLM provides a unified, OpenAI-compatible interface that supports
multiple LLM providers including OpenAI, Anthropic, Gemini, Mistral,
Groq, and local models.

See: https://docs.litellm.ai/docs/providers
"""

from __future__ import annotations

import ast
import asyncio
import contextvars
import hashlib
import json
import logging
import os
import random
import re
import shlex
import time
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.llm.key_pool import KeyPool

try:
    import litellm
    from litellm.exceptions import RateLimitError
    from litellm.integrations.custom_logger import CustomLogger
except ImportError:
    litellm = None  # type: ignore[assignment]
    RateLimitError = Exception  # type: ignore[assignment, misc]
    CustomLogger = object  # type: ignore[assignment, misc]

from framework.config import HIVE_LLM_ENDPOINT as HIVE_API_BASE, get_aux_max_tokens, get_max_tokens
from framework.llm.model_catalog import get_model_pricing
from framework.llm.provider import LLMProvider, LLMResponse, Tool
from framework.llm.stream_events import StreamEvent

logger = logging.getLogger(__name__)

logging.getLogger("openai._base_client").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def _api_base_needs_bearer_auth(api_base: str | None) -> bool:
    """Return True when api_base points at an Anthropic-compatible endpoint
    that authenticates via ``Authorization: Bearer`` rather than ``x-api-key``.

    The Hive LLM proxy (Rust service in hive-backend/llm/) speaks the
    Anthropic Messages API but mints user-scoped JWTs and validates them
    via Bearer auth. Default upstream Anthropic endpoints (api.anthropic.com,
    Kimi's api.kimi.com/coding) keep using x-api-key, so the override is
    scoped to known hive-proxy hosts plus the env-configured override.
    """
    if not api_base:
        return False
    # Strip protocol, port, and path so a plain hostname compare is enough
    # for the common cases.
    lowered = api_base.lower()
    for host in ("adenhq.com", "open-hive.com", "127.0.0.1:8890", "localhost:8890"):
        if host in lowered:
            return True
    override = os.environ.get("HIVE_LLM_BASE_URL")
    if override and override.lower() in lowered:
        return True
    return False


def _patch_litellm_anthropic_oauth() -> None:
    """Patch litellm's Anthropic header construction to fix OAuth token handling.

    litellm bug: validate_environment() puts the OAuth token into x-api-key,
    but Anthropic's API rejects OAuth tokens in x-api-key. They must be sent
    via Authorization: Bearer only, with x-api-key omitted entirely.

    This patch wraps validate_environment to remove x-api-key when the
    Authorization header carries an OAuth token (sk-ant-oat prefix).

    See: https://github.com/BerriAI/litellm/issues/19618
    """
    try:
        from litellm.llms.anthropic.common_utils import AnthropicModelInfo
        from litellm.types.llms.anthropic import (
            ANTHROPIC_OAUTH_BETA_HEADER,
            ANTHROPIC_OAUTH_TOKEN_PREFIX,
        )
    except ImportError:
        logger.warning(
            "Could not apply litellm Anthropic OAuth patch — litellm internals may have "
            "changed. Anthropic OAuth tokens (Claude Code subscriptions) may fail with 401. "
            "See BerriAI/litellm#19618. Current litellm version: %s",
            getattr(litellm, "__version__", "unknown"),
        )
        return

    original = AnthropicModelInfo.validate_environment

    def _patched_validate_environment(self, headers, model, messages, optional_params, litellm_params, api_key=None, api_base=None):
        result = original(
            self,
            headers,
            model,
            messages,
            optional_params,
            litellm_params,
            api_key=api_key,
            api_base=api_base,
        )
        # Check both authorization header and x-api-key for OAuth tokens.
        # litellm's optionally_handle_anthropic_oauth only checks headers["authorization"],
        # but hive passes OAuth tokens via api_key — so litellm puts them into x-api-key.
        # Anthropic rejects OAuth tokens in x-api-key; they must go in Authorization: Bearer.
        auth = result.get("authorization", "")
        x_api_key = result.get("x-api-key", "")
        oauth_prefix = f"Bearer {ANTHROPIC_OAUTH_TOKEN_PREFIX}"
        auth_is_oauth = auth.startswith(oauth_prefix)
        key_is_oauth = x_api_key.startswith(ANTHROPIC_OAUTH_TOKEN_PREFIX)
        if auth_is_oauth or key_is_oauth:
            token = x_api_key if key_is_oauth else auth.removeprefix("Bearer ").strip()
            result.pop("x-api-key", None)
            result["authorization"] = f"Bearer {token}"
            # Merge the OAuth beta header with any existing beta headers.
            existing_beta = result.get("anthropic-beta", "")
            beta_parts = [b.strip() for b in existing_beta.split(",") if b.strip()] if existing_beta else []
            if ANTHROPIC_OAUTH_BETA_HEADER not in beta_parts:
                beta_parts.append(ANTHROPIC_OAUTH_BETA_HEADER)
            result["anthropic-beta"] = ",".join(beta_parts)
        return result

    AnthropicModelInfo.validate_environment = _patched_validate_environment


def _patch_litellm_metadata_nonetype() -> None:
    """Patch litellm entry points to prevent metadata=None TypeError.

    litellm bug: the @client decorator in utils.py has four places that do
        "model_group" in kwargs.get("metadata", {})
    but kwargs["metadata"] can be explicitly None (set internally by
    litellm_params), causing:
        TypeError: argument of type 'NoneType' is not iterable
    This masks the real API error with a confusing APIConnectionError.

    Fix: wrap the four litellm entry points (completion, acompletion,
    responses, aresponses) to pop metadata=None before the @client
    decorator's error handler can crash on it.
    """
    import functools

    patched_count = 0
    for fn_name in ("completion", "acompletion", "responses", "aresponses"):
        original = getattr(litellm, fn_name, None)
        if original is None:
            continue
        patched_count += 1
        if asyncio.iscoroutinefunction(original):

            @functools.wraps(original)
            async def _async_wrapper(*args, _orig=original, **kwargs):
                if kwargs.get("metadata") is None:
                    kwargs.pop("metadata", None)
                return await _orig(*args, **kwargs)

            setattr(litellm, fn_name, _async_wrapper)
        else:

            @functools.wraps(original)
            def _sync_wrapper(*args, _orig=original, **kwargs):
                if kwargs.get("metadata") is None:
                    kwargs.pop("metadata", None)
                return _orig(*args, **kwargs)

            setattr(litellm, fn_name, _sync_wrapper)

    if patched_count == 0:
        logger.warning(
            "Could not apply litellm metadata=None patch — none of the expected entry "
            "points (completion, acompletion, responses, aresponses) were found. "
            "metadata=None TypeError may occur. Current litellm version: %s",
            getattr(litellm, "__version__", "unknown"),
        )


def _patch_litellm_preserve_credits() -> None:
    """Patch litellm's Anthropic ``calculate_usage`` to preserve ``credits``.

    The Hive proxy returns a non-standard ``credits`` field on each
    ``message_delta.usage`` (cumulative per-request, last-event-wins). Litellm's
    ``AnthropicConfig.calculate_usage`` constructs its ``Usage`` Pydantic model
    with explicit kwargs from a fixed schema — anything outside that schema is
    silently dropped, including ``credits``. Both streaming and non-streaming
    Anthropic paths funnel through this one function, so wrapping it once
    catches both.

    The patched wrapper calls the original, then attaches ``credits`` to the
    returned ``Usage`` as a plain Python attribute (via ``object.__setattr__``
    to bypass Pydantic v2 validation). ``_credits_from_usage`` upstream reads
    it back via ``getattr``.
    """
    try:
        from litellm.llms.anthropic.chat.transformation import AnthropicConfig
    except ImportError:
        logger.warning(
            "Could not apply litellm credits-preservation patch — litellm "
            "internals may have changed. Hive credit accounting will be "
            "unavailable. Current litellm version: %s",
            getattr(litellm, "__version__", "unknown"),
        )
        return

    original = AnthropicConfig.calculate_usage

    def _patched_calculate_usage(self, usage_object, *args, **kwargs):
        usage = original(self, usage_object, *args, **kwargs)
        if isinstance(usage_object, dict):
            raw = usage_object.get("credits")
            logger.debug(
                "[credits] calculate_usage raw=%s credits=%r keys=%s",
                "hive-format" if "credits" in usage_object else "no-credits-key",
                raw,
                sorted(usage_object.keys()),
            )
            if isinstance(raw, (int, float)):
                # Pydantic v2 with extra="allow" stores unknown fields in
                # ``model_extra``. Plain ``setattr`` puts the value in
                # ``__dict__`` only, which gets stripped when downstream
                # code re-validates the Usage (e.g. when it's passed to
                # ``ModelResponseStream(usage=usage)``). Writing into
                # ``model_extra`` survives that round-trip.
                try:
                    extra = usage.model_extra
                    if extra is None:
                        # Defensive: rebuild via constructor so model_extra
                        # gets initialized.
                        from litellm.types.utils import Usage as _U

                        usage = _U(**usage.model_dump(), credits=float(raw))
                    else:
                        extra["credits"] = float(raw)
                        # Mirror to __dict__ so plain ``getattr`` still works.
                        object.__setattr__(usage, "credits", float(raw))
                except Exception:
                    logger.debug("[credits] failed to attach credits", exc_info=True)
        return usage

    AnthropicConfig.calculate_usage = _patched_calculate_usage  # type: ignore[assignment]
    logger.info("[credits] applied calculate_usage patch")


if litellm is not None:
    _patch_litellm_anthropic_oauth()
    _patch_litellm_metadata_nonetype()
    _patch_litellm_preserve_credits()
    # Let litellm silently drop params unsupported by the target provider
    # (e.g. stream_options for Anthropic) instead of forwarding them verbatim.
    litellm.drop_params = True


def _is_ollama_model(model: str) -> bool:
    """Return True for any Ollama model string (ollama/ or ollama_chat/ prefix)."""
    return model.startswith("ollama/") or model.startswith("ollama_chat/")


def _ensure_ollama_chat_prefix(model: str) -> str:
    """Normalise Ollama model strings to use the ollama_chat/ prefix.

    LiteLLM requires the ``ollama_chat/`` prefix (not ``ollama/``) to enable
    native function-calling support.  With ``ollama/``, LiteLLM falls back to
    JSON-mode tool calls, which the framework cannot parse as real tool calls.

    See: https://docs.litellm.ai/docs/providers/ollama#example-usage---tool-calling
    """
    if model.startswith("ollama/"):
        return "ollama_chat/" + model[len("ollama/") :]
    return model


def _log_llm_call(kwargs: dict[str, Any], *, stream: bool = False, attempt: int = 0) -> None:
    """Emit one INFO line per actual provider call.

    Fires immediately before ``litellm.(a)completion`` so a runtime that
    "looks frozen" surfaces as a recent ``[llm] →`` line with the model
    and request shape. Kept terse — model, message count, max_tokens,
    tool count, stream flag, attempt index (only when > 0).
    """
    msgs = kwargs.get("messages") or []
    tools = kwargs.get("tools") or []
    extras: list[str] = []
    if stream:
        extras.append("stream")
    if attempt > 0:
        extras.append(f"attempt={attempt + 1}")
    tail = (" " + " ".join(extras)) if extras else ""
    logger.info(
        "[llm] → model=%s msgs=%d max_tokens=%s tools=%d%s",
        kwargs.get("model", "?"),
        len(msgs),
        kwargs.get("max_tokens", "?"),
        len(tools),
        tail,
    )


def rewrite_proxy_model(model: str, api_key: str | None, api_base: str | None) -> tuple[str, str | None, dict[str, str]]:
    """Apply Hive/Kimi proxy rewrites for any caller of ``litellm.acompletion``.

    Both the Hive LLM proxy (llm.open-hive.com) and Kimi For Coding expose
    Anthropic-API-compatible endpoints. LiteLLM doesn't recognise the
    ``hive/`` or ``kimi/`` prefixes natively, so we rewrite them to
    ``anthropic/`` here. For the Hive proxy we also stamp a Bearer token
    into ``extra_headers`` because litellm's Anthropic handler only
    sends ``x-api-key`` and the proxy expects ``Authorization: Bearer``.

    Single source of truth for proxy-prefix handling. Used by
    ``LiteLLMProvider.__init__`` / ``reconfigure`` *and* by direct
    ``litellm.acompletion`` callers (e.g. the vision-fallback
    subagent in ``caption_tool_image``) so the main agent and any
    ad-hoc LLM call hit the same proxy with the same auth.

    Returns: (rewritten_model, normalised_api_base, extra_headers).
    The ``extra_headers`` dict is non-empty only for the Hive proxy
    (and only when ``api_key`` is provided); callers that resolve
    ``api_key`` later should ignore the returned headers and stamp
    the bearer themselves once the key is known.
    """
    extra_headers: dict[str, str] = {}
    if model.lower().startswith("kimi/"):
        model = "anthropic/" + model[len("kimi/") :]
        if api_base and api_base.rstrip("/").endswith("/v1"):
            api_base = api_base.rstrip("/")[:-3]
    elif model.lower().startswith("hive/"):
        model = "anthropic/" + model[len("hive/") :]
        if api_base and api_base.rstrip("/").endswith("/v1"):
            api_base = api_base.rstrip("/")[:-3]
        # Hive proxy expects Bearer auth; litellm's Anthropic handler
        # only sends x-api-key without this nudge.
        if api_key:
            extra_headers["Authorization"] = f"Bearer {api_key}"
    return model, api_base, extra_headers


RATE_LIMIT_MAX_RETRIES = 10
RATE_LIMIT_BACKOFF_BASE = 2  # seconds
RATE_LIMIT_MAX_DELAY = 120  # seconds - cap to prevent absurd waits
# Separate, much lower cap for "empty response, finish_reason=stop"
# scenarios. Unlike a real 429, these are rarely transient: Gemini
# returns stop+empty on silently-filtered safety blocks, poisoned
# conversation state (dangling tool_result after compaction), or
# malformed tool schemas. Waiting minutes doesn't fix any of those, so
# give up after 3 attempts (2+4+8 = 14s) and surface an actionable
# error instead of burning 12+ minutes on exponential backoff.
EMPTY_RESPONSE_MAX_RETRIES = 3
MINIMAX_API_BASE = "https://api.minimax.io/v1"
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

# Providers that accept cache_control on message content blocks.
# Anthropic: native ephemeral caching. MiniMax & Z-AI/GLM: pass-through to their APIs.
# (OpenAI caches automatically server-side; Groq/Gemini/etc. strip the header.)
_CACHE_CONTROL_PREFIXES = (
    "anthropic/",
    "claude-",
    "minimax/",
    "minimax-",
    "MiniMax-",
    "zai-glm",
    "glm-",
)

# OpenRouter sub-provider prefixes whose upstream API honors `cache_control`.
# OpenRouter passes the marker through to the underlying provider for these.
# (See https://openrouter.ai/docs/guides/best-practices/prompt-caching.)
# OpenAI/DeepSeek/Groq/Grok/Moonshot route through OpenRouter but cache
# automatically server-side — sending cache_control there is a no-op, not a
# win, and they need a separate prefix-stability fix to actually get hits.
_OPENROUTER_CACHE_CONTROL_PREFIXES = (
    "openrouter/anthropic/",
    "openrouter/google/gemini-",
    "openrouter/z-ai/glm",
    "openrouter/minimax/",
)


def _model_supports_cache_control(model: str) -> bool:
    if any(model.startswith(p) for p in _CACHE_CONTROL_PREFIXES):
        return True
    return any(model.startswith(p) for p in _OPENROUTER_CACHE_CONTROL_PREFIXES)


def _build_system_message(
    system: str,
    system_dynamic_suffix: str | None,
    model: str,
) -> dict[str, Any] | None:
    """Construct the system-role message for the chat completion.

    Returns ``None`` when there is nothing to send.

    Two-block split path — used when the caller supplied a non-empty
    ``system_dynamic_suffix`` AND the provider honors ``cache_control``
    (Anthropic, MiniMax, Z-AI/GLM). We emit ``content`` as a list of two
    text blocks with an ephemeral ``cache_control`` marker on the first
    block only. The prompt cache keeps the static prefix warm across
    turns and across iterations within a turn; only the small dynamic
    tail is recomputed on every request.

    Single-string path — used for every other case (no suffix provided,
    or provider doesn't honor ``cache_control``). We concatenate
    ``system`` + ``\\n\\n`` + ``system_dynamic_suffix`` and attach
    ``cache_control`` to the whole message when the provider supports
    it. This is byte-identical to the pre-split behavior for all
    non-cache-control providers (OpenAI, Gemini, Groq, Ollama, etc.).
    """
    if not system and not system_dynamic_suffix:
        return None
    if system_dynamic_suffix and _model_supports_cache_control(model):
        content_blocks: list[dict[str, Any]] = []
        if system:
            content_blocks.append(
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            )
        content_blocks.append({"type": "text", "text": system_dynamic_suffix})
        return {"role": "system", "content": content_blocks}
    # Single-string path (legacy or no-cache-control provider).
    combined = system
    if system_dynamic_suffix:
        combined = f"{system}\n\n{system_dynamic_suffix}" if system else system_dynamic_suffix
    sys_msg: dict[str, Any] = {"role": "system", "content": combined}
    if _model_supports_cache_control(model):
        sys_msg["cache_control"] = {"type": "ephemeral"}
    return sys_msg


def _append_json_instruction(full_messages: list[dict[str, Any]]) -> None:
    """Ask for JSON output via prompt engineering (works across providers).

    Appends to the leading system message when present, otherwise inserts
    one. Handles both system-content shapes: plain string, and the
    two-block list form produced by ``_build_system_message`` (where a
    bare ``+=`` would extend the list with individual characters).
    """
    json_instruction = "\n\nPlease respond with a valid JSON object."
    if full_messages and full_messages[0]["role"] == "system":
        content = full_messages[0]["content"]
        if isinstance(content, list):
            content.append({"type": "text", "text": json_instruction.strip()})
        else:
            full_messages[0]["content"] = content + json_instruction
    else:
        full_messages.insert(0, {"role": "system", "content": json_instruction.strip()})


def _history_cache_breakpoint_index(messages: list[dict[str, Any]], model: str) -> int:
    """Return the index in ``messages`` where the rolling cache breakpoint
    WOULD be placed, or ``-1`` when no breakpoint is placed.

    Non-mutating mirror of ``_apply_history_cache_breakpoint``. Exposed so
    the AgentLoop can record the anchor position in diagnostic events
    without re-implementing the selection rule. Both functions must stay
    in lock-step — change one, change the other.
    """
    if not _model_supports_cache_control(model):
        return -1
    anchor_idx = len(messages) - 1
    if anchor_idx < 0:
        return -1
    if messages[anchor_idx].get("role") == "system":
        return -1
    return anchor_idx


def _apply_history_cache_breakpoint(full_messages: list[dict[str, Any]], model: str) -> None:
    """Attach a rolling Anthropic ``cache_control`` marker on the LAST message.

    Anthropic permits up to 4 ephemeral cache breakpoints per request; we
    use one on the static system block (``_build_system_message``) and this
    rolling one at the very end of the history — whatever role the final
    message has (user turn, assistant reply, or tool result).

    Anchoring at the end is what makes long tool-use turns cacheable: an
    agent iteration appends one assistant + one tool-result message and
    re-sends the request, and Anthropic's automatic prefix checking (which
    looks back up to ~20 content blocks from each explicit breakpoint)
    finds the previous iteration's cached prefix, so each request reads
    the whole prior history from cache and writes only the new tail. The
    previous anchor rule ("message before the last user turn") never
    advanced inside a turn — for a worker whose only user message is its
    initial task, it landed on the system message and bailed, leaving the
    entire growing tool loop uncached on every iteration.

    On compaction the prefix bytes shift and we eat one cache-miss turn
    (then re-warm at the smaller size); a one-turn cost amortised across
    many warm turns.

    Skips when:
      * the provider doesn't honor ``cache_control`` (gated by
        ``_model_supports_cache_control``);
      * there are no messages, or the last message is the system block
        (already cached separately by ``_build_system_message``).
    """
    if not _model_supports_cache_control(model):
        return
    anchor_idx = len(full_messages) - 1
    if anchor_idx < 0:
        return
    anchor = full_messages[anchor_idx]
    if anchor.get("role") == "system":
        return
    anchor["cache_control"] = {"type": "ephemeral"}


# Kimi For Coding uses an Anthropic-compatible endpoint (no /v1 suffix).
# Claude Code integration uses this format; the /v1 OpenAI-compatible endpoint
# enforces a coding-agent whitelist that blocks unknown User-Agents.
KIMI_API_BASE = "https://api.kimi.com/coding"

# Claude Code OAuth subscription: the Anthropic API requires a specific
# User-Agent and a billing integrity header for OAuth-authenticated requests.
CLAUDE_CODE_VERSION = "2.1.76"
CLAUDE_CODE_USER_AGENT = f"claude-code/{CLAUDE_CODE_VERSION}"
_CLAUDE_CODE_BILLING_SALT = "59cf53e54c78"


def _sample_js_code_unit(text: str, idx: int) -> str:
    """Return the character at UTF-16 code unit index *idx*, matching JS semantics."""
    encoded = text.encode("utf-16-le")
    unit_offset = idx * 2
    if unit_offset + 2 > len(encoded):
        return "0"
    code_unit = int.from_bytes(encoded[unit_offset : unit_offset + 2], "little")
    return chr(code_unit)


def _claude_code_billing_header(messages: list[dict[str, Any]]) -> str:
    """Build the billing integrity system block required by Anthropic's OAuth path."""
    # Find the first user message text
    first_text = ""
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            first_text = content
            break
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                    first_text = block["text"]
                    break
            if first_text:
                break

    sampled = "".join(_sample_js_code_unit(first_text, i) for i in (4, 7, 20))
    version_hash = hashlib.sha256(f"{_CLAUDE_CODE_BILLING_SALT}{sampled}{CLAUDE_CODE_VERSION}".encode()).hexdigest()
    entrypoint = os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").strip() or "cli"
    return f"x-anthropic-billing-header: cc_version={CLAUDE_CODE_VERSION}.{version_hash[:3]}; cc_entrypoint={entrypoint}; cch=00000;"


# Empty-stream retries use a short fixed delay, not the rate-limit backoff.
# Conversation-structure issues are deterministic — long waits don't help.
EMPTY_STREAM_MAX_RETRIES = 3
EMPTY_STREAM_RETRY_DELAY = 1.0  # seconds
OPENROUTER_TOOL_COMPAT_ERROR_SNIPPETS = (
    "no endpoints found that support tool use",
    "no endpoints available that support tool use",
    "provider routing",
)
OPENROUTER_TOOL_CALL_RE = re.compile(
    r"<\|tool_call_start\|>\s*(.*?)\s*<\|tool_call_end\|>",
    re.DOTALL,
)
OPENROUTER_TOOL_COMPAT_CACHE_TTL_SECONDS = 3600
# OpenRouter routing can change over time, so tool-compat caching must expire.
OPENROUTER_TOOL_COMPAT_MODEL_CACHE: dict[str, float] = {}

# Transient stream errors (network blips, timeouts) use a separate cap
# from rate-limit retries — 3 retries is sufficient for connection failures.
STREAM_TRANSIENT_MAX_RETRIES = 3


# Directory for dumping failed requests. Resolved lazily so HIVE_HOME
# overrides (set by the desktop shell) take effect even if this module
# is imported before framework.config picks up the override.
def _failed_requests_dir() -> Path:
    from framework.config import HIVE_HOME

    return HIVE_HOME / "failed_requests"


# ---------------------------------------------------------------------------
# Failed-request curl capture
#
# To make a dumped failure reproducible, we record the exact request litellm
# built for each call. litellm's pre-call hook fires after the request body
# and headers are assembled but before the HTTP send, so it sees litellm's
# real, post-transform request.
#
# Propagation is tricky: litellm runs that hook inside its own copied
# contextvars Context, so a ContextVar.set() there never reaches the caller.
# Instead the caller installs an *empty holder dict* in the ContextVar before
# each call (_install_request_holder); litellm's copied context inherits the
# very same dict object, and the hook *mutates it in place*. Dict mutation
# crosses the context boundary; a ContextVar reassignment would not. The
# per-call holder also keeps concurrent agent tasks isolated.
# ---------------------------------------------------------------------------
_last_llm_request: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("hive_last_llm_request", default=None)


def _install_request_holder() -> None:
    """Install a fresh holder dict for _RequestCaptureLogger to fill in.

    Must be called immediately before each litellm completion/acompletion
    invocation, in the same task/thread that issues the call.
    """
    _last_llm_request.set({})


class _RequestCaptureLogger(CustomLogger):  # type: ignore[misc,valid-type]
    """litellm callback that records the outgoing request into the holder dict."""

    def log_pre_api_call(self, model: str, messages: list, kwargs: dict) -> None:
        try:
            holder = _last_llm_request.get()
            if holder is None:
                return  # No holder installed for this call — nothing to fill.
            aa = kwargs.get("additional_args") or {}
            holder.update(
                {
                    "api_base": aa.get("api_base"),
                    "headers": aa.get("headers"),
                    "body": aa.get("complete_input_dict"),
                    "api_key": kwargs.get("api_key"),
                }
            )
        except Exception:
            pass  # Capture is best-effort — never disrupt the LLM call.


# litellm only invokes log_pre_api_call for callbacks present in input_callback.
if litellm is not None and not any(isinstance(c, _RequestCaptureLogger) for c in litellm.input_callback):
    litellm.input_callback.append(_RequestCaptureLogger())


# Maximum number of dump files to retain in $HIVE_HOME/failed_requests/.
# Older files are pruned automatically to prevent unbounded disk growth.
MAX_FAILED_REQUEST_DUMPS = 50


def _cost_from_catalog_pricing(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """Last-resort cost calculation using curated catalog pricing.

    Consulted only when the provider response carries no native cost and
    LiteLLM's own catalog has no pricing for ``model``. Reads
    ``pricing_usd_per_mtok`` from ``model_catalog.json``. Rates are USD per
    million tokens.

    ``cached_tokens`` and ``cache_creation_tokens`` are subsets of
    ``input_tokens`` (see ``_extract_cache_tokens``), so subtract them from
    the base input count to avoid double-billing. If a cache rate is absent,
    fall back to the plain input rate.
    """
    if not model or (input_tokens == 0 and output_tokens == 0):
        return 0.0
    pricing = get_model_pricing(model)
    if pricing is None and "/" in model:
        # LiteLLM prefixes some ids (e.g. "openrouter/z-ai/glm-5.1"); the
        # catalog stores the bare form ("z-ai/glm-5.1"). Strip one segment.
        pricing = get_model_pricing(model.split("/", 1)[1])
    if pricing is None:
        return 0.0

    per_mtok_in = pricing.get("input", 0.0)
    per_mtok_out = pricing.get("output", 0.0)
    per_mtok_cache_read = pricing.get("cache_read", per_mtok_in)
    per_mtok_cache_write = pricing.get("cache_creation", per_mtok_in)

    plain_input = max(input_tokens - cached_tokens - cache_creation_tokens, 0)
    total = (
        plain_input * per_mtok_in + cached_tokens * per_mtok_cache_read + cache_creation_tokens * per_mtok_cache_write + output_tokens * per_mtok_out
    ) / 1_000_000
    return float(total) if total > 0 else 0.0


def _extract_cost(response: Any, model: str) -> float:
    """Pull the USD cost for a non-streaming completion response.

    Sources checked, in priority order:
      1. ``usage.cost`` — populated when OpenRouter returns native cost via
         ``usage: {include: true}`` or when ``litellm.include_cost_in_streaming_usage``
         is on.
      2. ``response._hidden_params["response_cost"]`` — set by LiteLLM's
         logging layer after most successful completions.
      3. ``litellm.completion_cost(...)`` — computes from the model pricing
         table; works across Anthropic, OpenAI, and OpenRouter as long as the
         model is in LiteLLM's catalog.
      4. ``pricing_usd_per_mtok`` from the curated model catalog — covers
         models (e.g. GLM, Kimi, MiniMax) that LiteLLM doesn't price.

    Returns 0.0 for unpriced models or unexpected response shapes — cost is a
    display concern, never let it break the hot path. For streaming paths
    where the aggregate response isn't a full ``ModelResponse``, use
    :func:`_cost_from_tokens` with the already-extracted token counts.
    """
    if response is None:
        return 0.0
    usage = getattr(response, "usage", None)
    usage_cost = getattr(usage, "cost", None) if usage is not None else None
    if isinstance(usage_cost, (int, float)) and usage_cost > 0:
        return float(usage_cost)

    hidden = getattr(response, "_hidden_params", None)
    if isinstance(hidden, dict):
        hp_cost = hidden.get("response_cost")
        if isinstance(hp_cost, (int, float)) and hp_cost > 0:
            return float(hp_cost)

    try:
        import litellm as _litellm

        computed = _litellm.completion_cost(completion_response=response, model=model)
        if isinstance(computed, (int, float)) and computed > 0:
            return float(computed)
    except Exception as exc:
        logger.debug("[cost] completion_cost failed for %s: %s", model, exc)

    if usage is not None:
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        cache_read, cache_creation = _extract_cache_tokens(usage)
        fallback = _cost_from_catalog_pricing(model, input_tokens, output_tokens, cache_read, cache_creation)
        if fallback > 0:
            return fallback
    return 0.0


def _credits_from_usage(usage: Any) -> float | None:
    """Read ``usage.credits`` (Hive proxy field). Returns None if absent.

    Only the Hive proxy populates this — direct provider models never carry
    it. ``None`` means "no estimate" (per the proxy spec), not zero. The
    value is cumulative for the whole request: in streaming, each event's
    ``credits`` is the running total, last-event-wins.

    LiteLLM's ``Usage`` is a Pydantic v2 model with ``extra="allow"``. Unknown
    fields like ``credits`` may sit on the instance as a direct attribute, in
    ``model_extra``, or only survive in ``model_dump()`` — depending on which
    code path inside litellm constructed the object. We try all of them.
    """
    if usage is None:
        return None
    raw: Any = None
    # 1. Direct attribute (Pydantic v2 with extra="allow" surfaces extras here
    #    when set via __init__; not always populated when set via field-copy).
    raw = getattr(usage, "credits", None)
    # 2. Pydantic v2 model_extra dict.
    if raw is None:
        extra = getattr(usage, "model_extra", None)
        if isinstance(extra, dict):
            raw = extra.get("credits")
    # 3. dict-style access (some usage shapes are plain dicts).
    if raw is None and hasattr(usage, "get"):
        try:
            raw = usage.get("credits")
        except Exception:
            raw = None
    if raw is None and hasattr(usage, "__getitem__"):
        try:
            raw = usage["credits"]
        except Exception:
            raw = None
    # 4. model_dump round-trip — last resort, but most reliable when extras
    #    are stored opaquely.
    if raw is None and hasattr(usage, "model_dump"):
        try:
            dumped = usage.model_dump()
            if isinstance(dumped, dict):
                raw = dumped.get("credits")
        except Exception:
            pass
    # 5. __dict__ for non-Pydantic shapes.
    if raw is None:
        d = getattr(usage, "__dict__", None)
        if isinstance(d, dict):
            raw = d.get("credits")
    if isinstance(raw, (int, float)):
        return float(raw)
    # Quiet on non-Hive models (where credits absence is expected). Hive-
    # aliased calls go through ``_patch_litellm_preserve_credits`` which
    # stashes credits as a direct attribute, so reaching this point on a
    # hive-* request indicates the patch failed.
    if logger.isEnabledFor(logging.DEBUG):
        try:
            snapshot: Any
            if hasattr(usage, "model_dump"):
                snapshot = usage.model_dump()
            elif hasattr(usage, "__dict__"):
                snapshot = dict(getattr(usage, "__dict__", {}) or {})
            else:
                snapshot = repr(usage)
            logger.debug("[credits] not found on usage; shape=%s", snapshot)
        except Exception:
            pass
    return None


def _extract_credits(response: Any) -> float | None:
    """Pull credits from a non-streaming response's usage block."""
    if response is None:
        return None
    return _credits_from_usage(getattr(response, "usage", None))


def _cost_from_tokens(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """Compute USD cost from already-normalized token counts.

    Used on streaming paths where the aggregate ``response`` is the stream
    wrapper (not a full ``ModelResponse``) and ``litellm.completion_cost`` on
    it either no-ops or raises. Calls ``litellm.cost_per_token`` directly
    with the cache-aware inputs so Anthropic's 5-min-write / cache-read
    multipliers are applied correctly.
    """
    if not model or (input_tokens == 0 and output_tokens == 0):
        return 0.0
    try:
        import litellm as _litellm

        prompt_cost, completion_cost = _litellm.cost_per_token(
            model=model,
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            cache_read_input_tokens=cached_tokens,
            cache_creation_input_tokens=cache_creation_tokens,
        )
        total = (prompt_cost or 0.0) + (completion_cost or 0.0)
        if total > 0:
            return float(total)
    except Exception as exc:
        logger.debug("[cost] cost_per_token failed for %s: %s", model, exc)
    return _cost_from_catalog_pricing(model, input_tokens, output_tokens, cached_tokens, cache_creation_tokens)


def _extract_cache_tokens(usage: Any) -> tuple[int, int]:
    """Pull (cache_read, cache_creation) from a LiteLLM usage object.

    Both are subsets of ``prompt_tokens`` already — providers count them
    inside the input total. Surface separately for visibility, never sum.

    Field names vary by provider/proxy; check the known shapes in priority
    order and fall back to 0:

    cache_read:
      - ``prompt_tokens_details.cached_tokens`` — OpenAI-shape; also what
        LiteLLM normalizes Anthropic and OpenRouter into.
      - ``cache_read_input_tokens`` — raw Anthropic field name.

    cache_creation:
      - ``prompt_tokens_details.cache_write_tokens`` — OpenRouter's
        normalized field for cache writes (verified empirically against
        ``openrouter/anthropic/*`` and ``openrouter/z-ai/*`` responses).
      - ``cache_creation_input_tokens`` — raw Anthropic top-level field.
    """
    if not usage:
        return 0, 0
    _details = getattr(usage, "prompt_tokens_details", None)
    cache_read = getattr(_details, "cached_tokens", 0) or 0 if _details is not None else getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_creation = (getattr(_details, "cache_write_tokens", 0) or 0 if _details is not None else 0) or (
        getattr(usage, "cache_creation_input_tokens", 0) or 0
    )
    return cache_read, cache_creation


def _estimate_tokens(model: str, messages: list[dict]) -> tuple[int, str]:
    """Estimate token count for messages. Returns (token_count, method)."""
    # Try litellm's token counter first
    if litellm is not None:
        try:
            count = litellm.token_counter(model=model, messages=messages)
            return count, "litellm"
        except Exception:
            pass

    # Fallback: rough estimate based on character count (~4 chars per token)
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    return total_chars // 4, "estimate"


def _prune_failed_request_dumps(max_files: int = MAX_FAILED_REQUEST_DUMPS) -> None:
    """Remove oldest dump files when the count exceeds *max_files*.

    Best-effort: never raises — a pruning failure must not break retry logic.
    """
    try:
        all_dumps = sorted(
            _failed_requests_dir().glob("*.json"),
            key=lambda f: f.stat().st_mtime,
        )
        excess = len(all_dumps) - max_files
        if excess > 0:
            for old_file in all_dumps[:excess]:
                old_file.unlink(missing_ok=True)
    except Exception:
        pass  # Best-effort — never block the caller


def _remember_openrouter_tool_compat_model(model: str) -> None:
    """Cache OpenRouter tool-compat fallback for a bounded time window."""
    OPENROUTER_TOOL_COMPAT_MODEL_CACHE[model] = time.monotonic() + OPENROUTER_TOOL_COMPAT_CACHE_TTL_SECONDS


def _is_openrouter_tool_compat_cached(model: str) -> bool:
    """Return True when the cached OpenRouter compat entry is still fresh."""
    expires_at = OPENROUTER_TOOL_COMPAT_MODEL_CACHE.get(model)
    if expires_at is None:
        return False
    if expires_at <= time.monotonic():
        OPENROUTER_TOOL_COMPAT_MODEL_CACHE.pop(model, None)
        return False
    return True


def _build_failed_request_curl() -> str | None:
    """Render the current task's last LLM request as a runnable curl command.

    Uses the request captured by :class:`_RequestCaptureLogger`. The body is
    litellm's exact post-transform payload. On the Anthropic-style path (the
    Hive proxy included) litellm also exposes the full URL and headers, so the
    curl is byte-faithful — real API key included. On the OpenAI-SDK path
    headers aren't visible pre-call, so the endpoint path and auth header are
    reconstructed from the api_base and api_key.

    Returns None when no request was captured (hook never ran).
    """
    req = _last_llm_request.get()
    if not req:
        return None
    # api_base may arrive as a str, a urllib ParseResult, or an httpx.URL
    # depending on the provider handler — normalize to a plain string.
    raw_base = req.get("api_base") or ""
    if isinstance(raw_base, str):
        api_base = raw_base
    elif hasattr(raw_base, "geturl"):
        api_base = raw_base.geturl()
    else:
        api_base = str(raw_base)
    headers = dict(req.get("headers") or {})
    body = req.get("body")
    api_key = req.get("api_key")

    # OpenAI-SDK providers pass extra_body as a nested dict the SDK merges
    # into the JSON body; flatten it so the curl body matches the wire bytes.
    if isinstance(body, dict) and isinstance(body.get("extra_body"), dict):
        merged = {k: v for k, v in body.items() if k != "extra_body"}
        merged.update(body["extra_body"])
        body = merged

    # Headers present => Anthropic-style path: api_base is already the full
    # endpoint URL. Headers absent => OpenAI-SDK path: api_base is a bare base,
    # so append the chat-completions path and synthesize the auth header.
    if headers:
        url = api_base
    else:
        url = api_base.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    parts = ["curl -X POST " + shlex.quote(url)]
    for key, value in headers.items():
        parts.append("-H " + shlex.quote(f"{key}: {value}"))
    if body is not None:
        parts.append("-d " + shlex.quote(json.dumps(body, default=str)))
    return " \\\n  ".join(parts)


def _dump_failed_request(
    model: str,
    kwargs: dict[str, Any],
    error_type: str,
    attempt: int,
) -> str:
    """Dump failed request to a file for debugging. Returns the file path."""
    try:
        dump_dir = _failed_requests_dir()
        dump_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{error_type}_{model.replace('/', '_')}_{timestamp}.json"
        filepath = dump_dir / filename

        # Build dump data
        messages = kwargs.get("messages", [])
        dump_data = {
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "error_type": error_type,
            "attempt": attempt,
            "estimated_tokens": _estimate_tokens(model, messages),
            "num_messages": len(messages),
            "api_base": kwargs.get("api_base"),
            "request_keys": sorted(kwargs.keys()),
            "messages": messages,
            "tools": kwargs.get("tools"),
            "max_tokens": kwargs.get("max_tokens"),
            "temperature": kwargs.get("temperature"),
            "stream": kwargs.get("stream"),
            "tool_choice": kwargs.get("tool_choice"),
            "response_format": kwargs.get("response_format"),
            # Runnable curl reproducing the exact request litellm sent.
            "curl": _build_failed_request_curl(),
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(dump_data, f, indent=2, default=str)

        # Prune old dumps to prevent unbounded disk growth
        _prune_failed_request_dumps()

        return str(filepath)
    except OSError as e:
        logger.warning(f"Failed to dump request debug log to {_failed_requests_dir()}: {e}")
        return "log_write_failed"


def _summarize_message_content(content: Any) -> dict[str, Any]:
    """Return a structural summary of one message content payload."""
    if isinstance(content, str):
        return {
            "content_kind": "string",
            "text_chars": len(content),
        }

    if isinstance(content, list):
        block_types: list[str] = []
        text_chars = 0
        for block in content:
            if isinstance(block, dict):
                block_type = str(block.get("type", "unknown"))
                block_types.append(block_type)
                if block_type == "text":
                    text_chars += len(str(block.get("text", "")))
                elif block_type == "tool_result":
                    block_content = block.get("content")
                    if isinstance(block_content, str):
                        text_chars += len(block_content)
                    elif isinstance(block_content, list):
                        for inner in block_content:
                            if isinstance(inner, dict) and inner.get("type") == "text":
                                text_chars += len(str(inner.get("text", "")))
            else:
                block_types.append(type(block).__name__)
        return {
            "content_kind": "list",
            "blocks": len(content),
            "block_types": block_types,
            "text_chars": text_chars,
        }

    return {
        "content_kind": type(content).__name__,
    }


def _summarize_messages_for_log(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a high-signal, no-secret summary of the outgoing messages payload."""
    summary: list[dict[str, Any]] = []
    for idx, message in enumerate(messages):
        item: dict[str, Any] = {
            "idx": idx,
            "role": message.get("role"),
            "keys": sorted(message.keys()),
        }
        item.update(_summarize_message_content(message.get("content")))
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            item["tool_calls"] = len(tool_calls)
            tool_names = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    fn = tc.get("function")
                    if isinstance(fn, dict) and fn.get("name"):
                        tool_names.append(str(fn["name"]))
            if tool_names:
                item["tool_call_names"] = tool_names
        if message.get("cache_control"):
            item["cache_control"] = True
        if message.get("tool_call_id"):
            item["tool_call_id"] = str(message.get("tool_call_id"))
        summary.append(item)
    return summary


def _summarize_request_for_log(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return a compact structural summary of a LiteLLM request payload."""
    tools = kwargs.get("tools")
    tool_names: list[str] = []
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict):
                fn = tool.get("function")
                if isinstance(fn, dict) and fn.get("name"):
                    tool_names.append(str(fn["name"]))

    messages = kwargs.get("messages", [])
    if isinstance(messages, list):
        non_system_roles = [m.get("role") for m in messages if m.get("role") != "system"]
    else:
        non_system_roles = []
    return {
        "model": kwargs.get("model"),
        "api_base": kwargs.get("api_base"),
        "stream": kwargs.get("stream"),
        "max_tokens": kwargs.get("max_tokens"),
        "tool_count": len(tools) if isinstance(tools, list) else 0,
        "tool_names": tool_names,
        "tool_choice": kwargs.get("tool_choice"),
        "response_format": bool(kwargs.get("response_format")),
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "non_system_message_count": len(non_system_roles),
        "first_non_system_role": non_system_roles[0] if non_system_roles else None,
        "last_non_system_role": non_system_roles[-1] if non_system_roles else None,
        "system_only": bool(messages) and not non_system_roles,
        "messages": _summarize_messages_for_log(messages if isinstance(messages, list) else []),
    }


def _exception_headers(exception: BaseException) -> Any:
    """Return whatever dict-like headers the exception exposes, or None.

    LiteLLM constructs RateLimitError with a synthetic httpx.Response whose
    headers are only populated when the upstream response was attached. The
    Anthropic handler often raises without attaching it, so also check
    ``exception.headers`` (set directly on some litellm subclasses).
    """
    response = getattr(exception, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None)
        if headers:
            return headers
    headers = getattr(exception, "headers", None)
    if headers:
        return headers
    return None


def _parse_retry_after(headers: Any, max_delay: float) -> float | None:
    """Parse retry-after-ms / retry-after from a header mapping.

    Returns the delay in seconds clamped to [0, max_delay], or None when no
    usable header is present.
    """
    retry_after_ms = headers.get("retry-after-ms")
    if retry_after_ms is not None:
        try:
            return min(max(float(retry_after_ms) / 1000.0, 0), max_delay)
        except (ValueError, TypeError):
            pass

    retry_after = headers.get("retry-after")
    if retry_after is not None:
        try:
            return min(max(float(retry_after), 0), max_delay)
        except (ValueError, TypeError):
            pass

        try:
            from email.utils import parsedate_to_datetime

            retry_date = parsedate_to_datetime(retry_after)
            now = datetime.now(retry_date.tzinfo)
            return min(max((retry_date - now).total_seconds(), 0), max_delay)
        except (ValueError, TypeError, OverflowError):
            pass

    return None


# Floor used when the proxy's backpressure error has stripped Retry-After:
# the Hive proxy's only signal is `{"type":"backpressure"}` so treat it as
# "try again very soon" rather than falling through to exponential backoff.
_BACKPRESSURE_RETRY_FLOOR = 1.0
# Below this threshold we treat a server-provided Retry-After as "short" and
# add positive jitter so N concurrent retrying clients don't all wake up
# together. Long upstream values (Anthropic/OpenAI quota windows) are kept
# verbatim.
_SHORT_RETRY_AFTER_THRESHOLD = 5.0


def _compute_retry_delay(
    attempt: int,
    exception: BaseException | None = None,
    backoff_base: int = RATE_LIMIT_BACKOFF_BASE,
    max_delay: int = RATE_LIMIT_MAX_DELAY,
    jitter: bool = False,
) -> float:
    """Compute retry delay, preferring server-provided Retry-After headers.

    Priority:
    1. retry-after-ms header (milliseconds, float)
    2. retry-after header as seconds (float)
    3. retry-after header as HTTP-date (RFC 7231)
    4. Implicit short retry when the error body identifies as proxy backpressure
    5. Exponential backoff: backoff_base * 2^attempt

    ``jitter`` desynchronizes lockstep retries from concurrent callers: when
    True, short delays gain positive jitter and the exponential fallback gains
    bidirectional jitter. Long upstream Retry-After values are kept verbatim.
    All values are capped at ``max_delay`` seconds.
    """
    if exception is not None:
        headers = _exception_headers(exception)
        if headers is not None:
            delay = _parse_retry_after(headers, max_delay)
            if delay is not None:
                if jitter and delay < _SHORT_RETRY_AFTER_THRESHOLD:
                    delay = delay * random.uniform(1.0, 1.5) + random.uniform(0, 0.5)
                    delay = min(delay, max_delay)
                return delay

        # No headers — check whether this looks like Hive proxy backpressure.
        # The proxy emits {"type":"error","error":{"type":"backpressure",...}}
        # with retry-after:1, but LiteLLM may strip headers before raising.
        if "backpressure" in str(exception).lower():
            delay = _BACKPRESSURE_RETRY_FLOOR
            if jitter:
                delay = delay * random.uniform(1.0, 1.5) + random.uniform(0, 0.5)
            return min(delay, max_delay)

    delay = backoff_base * (2**attempt)
    delay = min(delay, max_delay)
    if jitter:
        delay *= random.uniform(0.75, 1.25)
    return delay


def _is_stream_transient_error(exc: BaseException) -> bool:
    """Classify whether a streaming exception is transient (recoverable).

    Transient errors (recoverable=True): network issues, server errors, timeouts.
    Permanent errors (recoverable=False): auth, bad request, context window, etc.

    NOTE: "Failed to parse tool call arguments" (malformed LLM output) is NOT
    transient at the stream level — retrying with the same messages produces the
    same malformed output.  This error is handled at the EventLoopNode level
    where the conversation can be modified before retrying.
    """
    # Billing/credit errors are permanent — retrying a 0-balance account just
    # produces the same 402. LiteLLM masks the proxy's 402 as APIConnectionError
    # (see module note), so check the classification AND the message body.
    err_type, status = _classify_llm_error(exc)
    if err_type == "payment_required" or status == 402:
        return False
    if "insufficient_credits" in str(exc).lower():
        return False

    try:
        from litellm.exceptions import (
            APIConnectionError,
            BadGatewayError,
            InternalServerError,
            ServiceUnavailableError,
        )

        transient_types: tuple[type[BaseException], ...] = (
            APIConnectionError,
            InternalServerError,
            BadGatewayError,
            ServiceUnavailableError,
            TimeoutError,
            ConnectionError,
            OSError,
        )
    except ImportError:
        transient_types = (TimeoutError, ConnectionError, OSError)

    return isinstance(exc, transient_types)


def _classify_llm_error(exc: BaseException) -> tuple[str | None, int | None]:
    """Classify an LLM-call exception into (error_type, upstream_status).

    The ``error_type`` is a stable, coarse category the desktop client can
    branch on without parsing free-form messages. ``upstream_status`` is the
    HTTP status from the LLM provider when available.

    Today we only emit ``"payment_required"`` for 402s (the Hive LLM proxy
    returns this when the user's team has no active plan / has exhausted
    credits) and ``"rate_limit"`` for 429s. Extend as new categories surface.
    """
    status: int | None = None
    for attr in ("status_code", "http_status", "code"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            status = v
            break
    # LiteLLM wraps the upstream httpx response on .response.status_code.
    if status is None:
        resp = getattr(exc, "response", None)
        if resp is not None:
            v = getattr(resp, "status_code", None)
            if isinstance(v, int):
                status = v
    # Fall back to the chained cause (httpx.HTTPStatusError, etc.).
    if status is None and exc.__cause__ is not None:
        v = getattr(exc.__cause__, "status_code", None)
        if isinstance(v, int):
            status = v
        else:
            resp = getattr(exc.__cause__, "response", None)
            if resp is not None:
                v = getattr(resp, "status_code", None)
                if isinstance(v, int):
                    status = v

    if status == 402:
        return "payment_required", 402
    if status == 429 or isinstance(exc, RateLimitError):
        return "rate_limit", status or 429
    return None, status


def _is_hive_stream_token_invalid(exc: BaseException) -> bool:
    """Detect the specific failure mode that warrants an in-VM
    streamToken refresh + LLM retry. The Rust LLM proxy returns

        HTTP 401 Unauthorized
        {"error":{"type":"hive_stream_token_invalid", ...}}

    when the runtime's ``hive`` credential is past exp or sid-revoked.
    Without this detector, a stale token kills every LLM call until
    either the periodic refresh loop ticks (~hours) or the desktop
    re-pushes — both unacceptable when a queen needs to recover NOW.

    Matches on the error-body marker, not just the status — a 401 from
    upstream Anthropic/OpenAI is a DIFFERENT problem (real auth
    failure, not a refreshable token), and we don't want to force-
    refresh against the wrong provider's key."""
    msg = str(exc).lower()
    if "hive_stream_token_invalid" in msg:
        return True
    # Cover the case where the marker is in the wrapped response body
    # but not in str(exc) — e.g. LiteLLM strips it from the message.
    for attr in ("response", "__cause__", "_cause__"):
        nested = getattr(exc, attr, None)
        if nested is None:
            continue
        nested_text = ""
        text_fn = getattr(nested, "text", None)
        if callable(text_fn):
            try:
                nested_text = text_fn() or ""
            except Exception:
                nested_text = ""
        elif isinstance(text_fn, str):
            nested_text = text_fn
        if "hive_stream_token_invalid" in nested_text.lower():
            return True
    return False


def _extract_text_tool_calls(
    text: str,
) -> tuple[list, str]:
    """Extract hallucinated tool calls from ``<tool_code>`` blocks in LLM text.

    Some models (notably Gemini) emit tool invocations as text instead of using
    the structured function-calling API.  This function parses those blocks and
    returns ``(tool_call_events, cleaned_text)`` where *cleaned_text* has the
    ``<tool_code>`` blocks removed.

    Expected format::

        <tool_code>
        {
          "tool_name": { ...args }
        }
        </tool_code>
    """
    from framework.llm.stream_events import ToolCallEvent

    pattern = re.compile(r"<tool_code>\s*(.*?)\s*</tool_code>", re.DOTALL)
    events: list[ToolCallEvent] = []
    cleaned = text

    for match in pattern.finditer(text):
        raw = match.group(1).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("[_extract_text_tool_calls] failed to parse JSON: %s", raw[:200])
            continue

        if not isinstance(payload, dict):
            continue

        for tool_name, tool_args in payload.items():
            key = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
            digest = hashlib.md5(key.encode()).hexdigest()[:12]
            call_id = f"synth_{digest}"
            events.append(
                ToolCallEvent(
                    tool_use_id=call_id,
                    tool_name=tool_name,
                    tool_input=tool_args if isinstance(tool_args, dict) else {},
                )
            )

    if events:
        cleaned = pattern.sub("", text).strip()

    return events, cleaned


class LiteLLMProvider(LLMProvider):
    """
    LiteLLM-based LLM provider for multi-provider support.

    Supports any model that LiteLLM supports, including:
    - OpenAI: gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo
    - Anthropic: claude-3-opus, claude-3-sonnet, claude-3-haiku
    - Google: gemini-pro, gemini-1.5-pro, gemini-1.5-flash
    - DeepSeek: deepseek-chat, deepseek-coder, deepseek-reasoner
    - Mistral: mistral-large, mistral-medium, mistral-small
    - Groq: llama3-70b, mixtral-8x7b
    - Local: ollama/llama3, ollama/mistral
    - And many more...

    Usage:
        # OpenAI
        provider = LiteLLMProvider(model="gpt-4o-mini")

        # Anthropic
        provider = LiteLLMProvider(model="claude-3-haiku-20240307")

        # Google Gemini
        provider = LiteLLMProvider(model="gemini/gemini-1.5-flash")

        # DeepSeek
        provider = LiteLLMProvider(model="deepseek/deepseek-chat")

        # Local Ollama
        provider = LiteLLMProvider(model="ollama/llama3")

        # With custom API base
        provider = LiteLLMProvider(
            model="gpt-4o-mini",
            api_base="https://my-proxy.com/v1"
        )
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        api_base: str | None = None,
        api_keys: list[str] | None = None,
        api_key_resolver: Callable[[], str | None] | None = None,
        **kwargs: Any,
    ):
        """
        Initialize the LiteLLM provider.

        Args:
            model: Model identifier (e.g., "gpt-4o-mini", "claude-3-haiku-20240307")
                   LiteLLM auto-detects the provider from the model name.
            api_key: API key for the provider. If not provided, LiteLLM will
                     look for the appropriate env var (OPENAI_API_KEY,
                     ANTHROPIC_API_KEY, etc.)
            api_base: Custom API base URL (for proxies or local deployments)
            api_keys: Optional list of API keys for key-pool rotation. When
                      provided with 2+ keys, a :class:`KeyPool` is created and
                      keys are rotated on rate-limit errors.
            api_key_resolver: Optional callable invoked before each LLM call
                      to re-resolve the current api_key (e.g. from the
                      credential store after a desktop streamToken refresh).
                      When set, the snapshot in ``self.api_key`` is treated
                      as a default — actual call sites pull the latest value
                      via :meth:`_refresh_api_key` so refreshes propagate
                      without needing ``_hot_swap_sessions`` to visit every
                      live provider.
            **kwargs: Additional arguments passed to litellm.completion()
        """
        self._api_key_resolver = api_key_resolver
        # Track whether the model uses the Hive LLM proxy. The bearer
        # header it requires is stamped after api_key resolution below
        # (we may not have api_key yet — could come from a key pool).
        _original_model = model
        self._hive_proxy_auth = bool(model.lower().startswith("hive/"))
        if _is_ollama_model(model):
            model = _ensure_ollama_chat_prefix(model)
        else:
            # rewrite_proxy_model handles the kimi/ → anthropic/ and
            # hive/ → anthropic/ rewrites and normalises api_base. We
            # pass api_key=None because the key pool isn't resolved
            # yet; the returned extra_headers is therefore empty for
            # hive — we stamp the bearer below once api_key is known.
            model, api_base, _ = rewrite_proxy_model(model, None, api_base)
        self.model = model
        # Key pool: when multiple keys are provided, enable rotation.
        self._key_pool: KeyPool | None = None
        if api_keys and len(api_keys) > 1:
            from framework.llm.key_pool import KeyPool

            self._key_pool = KeyPool(api_keys)
            self.api_key = api_keys[0]  # default for OAuth detection below
            logger.info(
                "[litellm] Key pool enabled with %d keys for model %s",
                len(api_keys),
                model,
            )
        else:
            self.api_key = api_key or (api_keys[0] if api_keys else None)
        self.api_base = api_base or self._default_api_base_for_model(_original_model)
        self.extra_kwargs = kwargs
        if self._hive_proxy_auth and self.api_key:
            eh = self.extra_kwargs.setdefault("extra_headers", {})
            eh["Authorization"] = f"Bearer {self.api_key}"
        # Detect Claude Code OAuth subscription by checking the api_key prefix.
        self._claude_code_oauth = bool(self.api_key and self.api_key.startswith("sk-ant-oat"))
        if self._claude_code_oauth:
            # Anthropic requires a specific User-Agent for OAuth requests.
            eh = self.extra_kwargs.setdefault("extra_headers", {})
            eh.setdefault("user-agent", CLAUDE_CODE_USER_AGENT)
        # The Codex ChatGPT backend (chatgpt.com/backend-api/codex) rejects
        # several standard OpenAI params: max_output_tokens, stream_options.
        self._codex_backend = bool(self.api_base and "chatgpt.com/backend-api/codex" in self.api_base)
        # Antigravity routes through a local OpenAI-compatible proxy — no patches needed.
        self._antigravity = bool(self.api_base and "localhost:8069" in self.api_base)

        if litellm is None:
            raise ImportError("LiteLLM is not installed. Please install it with: uv pip install litellm")

    def _refresh_api_key(self) -> None:
        """Re-resolve api_key from the configured resolver before each call.

        Lets desktop streamToken refreshes propagate to every live provider
        without _hot_swap_sessions needing to visit them. No-op when no
        resolver was supplied (legacy behavior, snapshot wins).
        """
        if not self._api_key_resolver:
            return
        try:
            fresh = self._api_key_resolver()
        except Exception:
            return
        if not fresh or fresh == self.api_key:
            return
        self.api_key = fresh
        if self._hive_proxy_auth:
            # Keep the Bearer header in sync — initially stamped at
            # __init__ (lines ~1411–1413) and rewritten by reconfigure().
            eh = self.extra_kwargs.setdefault("extra_headers", {})
            eh["Authorization"] = f"Bearer {fresh}"

    def reconfigure(self, model: str, api_key: str | None = None, api_base: str | None = None) -> None:
        """Hot-swap the model, API key, and/or base URL on this provider instance.

        Since the same LiteLLMProvider object is shared by reference across the
        session, queen runner, agent runtime, and execution streams, mutating
        these attributes in-place propagates to all callers on the next LLM call.
        """
        _original_model = model
        self._hive_proxy_auth = bool(model.lower().startswith("hive/"))
        if _is_ollama_model(model):
            model = _ensure_ollama_chat_prefix(model)
            proxy_headers: dict[str, str] = {}
        else:
            model, api_base, proxy_headers = rewrite_proxy_model(model, api_key, api_base)
        self.model = model
        self.api_key = api_key
        self.api_base = api_base or self._default_api_base_for_model(_original_model)
        self._claude_code_oauth = bool(api_key and api_key.startswith("sk-ant-oat"))
        if self._claude_code_oauth:
            eh = self.extra_kwargs.setdefault("extra_headers", {})
            eh.setdefault("user-agent", CLAUDE_CODE_USER_AGENT)
        if self._hive_proxy_auth:
            eh = self.extra_kwargs.setdefault("extra_headers", {})
            # rewrite_proxy_model fills proxy_headers when api_key is
            # set; when api_key was cleared we explicitly drop the stale
            # bearer so the next call doesn't reuse the prior token.
            if proxy_headers.get("Authorization"):
                eh["Authorization"] = proxy_headers["Authorization"]
            else:
                eh.pop("Authorization", None)
        self._codex_backend = bool(self.api_base and "chatgpt.com/backend-api/codex" in self.api_base)
        self._antigravity = bool(self.api_base and "localhost:8069" in self.api_base)

        # Note: The Codex ChatGPT backend is a Responses API endpoint at
        # chatgpt.com/backend-api/codex/responses.  LiteLLM's model registry
        # correctly marks codex models with mode="responses", so we do NOT
        # override the mode.  The responses_api_bridge in litellm handles
        # converting Chat Completions requests to Responses API format.

    def _apply_usage_agent_header(self, kwargs: dict[str, Any]) -> None:
        """Stamp ``X-Hive-Agent`` / ``X-Hive-Session`` for Hive-LLM-proxy-bound calls.

        The Rust LLM proxy reads these headers and writes them into
        ``llm_events`` for per-agent / per-session cloud usage
        attribution. Off for direct Anthropic / Kimi / OpenRouter /
        Ollama traffic — only the Hive proxy expects (and reads) them.

        We mutate a fresh copy of ``extra_headers`` rather than the dict
        that came in via ``**self.extra_kwargs`` so the per-call values
        do not leak into the next call. Reads ``usage_agent_id`` and
        ``session_id`` from the task-tools execution context (set by
        queen_orchestrator and worker.py before each agent's iteration).
        """
        if not self._hive_proxy_auth:
            return
        try:
            from framework.tasks.tools._context import current_session_id, current_usage_agent_id

            agent_id = current_usage_agent_id()
            session_id = current_session_id()
        except Exception:
            return
        if not agent_id and not session_id:
            return
        existing = kwargs.get("extra_headers") or {}
        headers = {**existing}
        if agent_id:
            headers["X-Hive-Agent"] = agent_id
        if session_id and "X-Hive-Session" not in headers:
            headers["X-Hive-Session"] = session_id
        kwargs["extra_headers"] = headers

    @staticmethod
    def _default_api_base_for_model(model: str) -> str | None:
        """Return provider-specific default API base when required."""
        model_lower = model.lower()
        if model_lower.startswith("minimax/") or model_lower.startswith("minimax-"):
            return MINIMAX_API_BASE
        if model_lower.startswith("openrouter/"):
            return OPENROUTER_API_BASE
        if model_lower.startswith("kimi/"):
            return KIMI_API_BASE
        if model_lower.startswith("hive/"):
            return HIVE_API_BASE
        return None

    def _completion_with_rate_limit_retry(self, max_retries: int | None = None, **kwargs: Any) -> Any:
        """Call litellm.completion with retry on 429 rate limit errors and empty responses.

        When a :class:`KeyPool` is configured, rate-limited keys are rotated
        automatically so the next attempt uses a different key -- no sleep
        needed between attempts.
        """
        self._apply_usage_agent_header(kwargs)
        model = kwargs.get("model", self.model)
        retries = max_retries if max_retries is not None else RATE_LIMIT_MAX_RETRIES
        for attempt in range(retries + 1):
            # Rotate key from pool when available.
            current_key: str | None = None
            if self._key_pool:
                current_key = self._key_pool.get_key()
                kwargs["api_key"] = current_key
            # Token fingerprint at the moment of the call. When the Hive
            # proxy rejects a token, we cross-reference this fp against
            # the most-recent ``configureLocalLlm`` push fp on the
            # desktop side to tell whether the runtime is holding a
            # stale spawn-time snapshot.
            _call_key = kwargs.get("api_key")
            _call_key_fp = f"len={len(_call_key)} {_call_key[:6]}…{_call_key[-4:]}" if isinstance(_call_key, str) and _call_key else "<empty>"
            logger.debug(
                "[hive-auth] LLM call: model=%s api_key=%s hive_proxy=%s",
                kwargs.get("model"),
                _call_key_fp,
                self._hive_proxy_auth,
            )
            try:
                _install_request_holder()
                _log_llm_call(kwargs, attempt=attempt)
                response = litellm.completion(**kwargs)  # type: ignore[union-attr]

                # Some providers (e.g. Gemini) return 200 with empty content on
                # rate limit / quota exhaustion instead of a proper 429.  Treat
                # empty responses the same as a rate-limit error and retry.
                content = response.choices[0].message.content if response.choices else None
                has_tool_calls = bool(response.choices and response.choices[0].message.tool_calls)
                if not content and not has_tool_calls:
                    # If the conversation ends with an assistant message,
                    # an empty response is expected — don't retry.
                    messages = kwargs.get("messages", [])
                    last_role = next(
                        (m["role"] for m in reversed(messages) if m.get("role") != "system"),
                        None,
                    )
                    if last_role == "assistant":
                        logger.debug("[retry] Empty response after assistant message — expected, not retrying.")
                        return response

                    finish_reason = response.choices[0].finish_reason if response.choices else "unknown"
                    # Dump full request to file for debugging
                    token_count, token_method = _estimate_tokens(model, messages)
                    dump_path = _dump_failed_request(
                        model=model,
                        kwargs=kwargs,
                        error_type="empty_response",
                        attempt=attempt,
                    )
                    logger.warning(
                        f"[retry] Empty response - {len(messages)} messages, "
                        f"~{token_count} tokens ({token_method}). "
                        f"Full request dumped to: {dump_path}"
                    )

                    # finish_reason=length means the model exhausted max_tokens
                    # before producing content. Retrying with the same max_tokens
                    # will never help — return immediately instead of looping.
                    if finish_reason == "length":
                        max_tok = kwargs.get("max_tokens", "unset")
                        logger.error(
                            f"[retry] {model} returned empty content with "
                            f"finish_reason=length (max_tokens={max_tok}). "
                            f"The model exhausted its token budget before "
                            f"producing visible output. Increase max_tokens "
                            f"or use a different model. Not retrying."
                        )
                        return response

                    empty_cap = min(retries, EMPTY_RESPONSE_MAX_RETRIES)
                    if attempt >= empty_cap:
                        logger.error(
                            f"[retry] GAVE UP on {model} after "
                            f"{attempt + 1} attempts — empty response "
                            f"(finish_reason={finish_reason}, "
                            f"choices={len(response.choices) if response.choices else 0}). "
                            f"This is almost never a rate limit despite the "
                            f"earlier log message — check the dumped request "
                            f"at {dump_path} for poisoned conversation state "
                            f"(dangling tool_result after compaction), a "
                            f"safety-filter trigger in the prompt, or a "
                            f"malformed tool schema."
                        )
                        return response
                    wait = _compute_retry_delay(attempt)
                    logger.warning(
                        f"[retry] {model} returned empty response "
                        f"(finish_reason={finish_reason}, "
                        f"choices={len(response.choices) if response.choices else 0}). "
                        f"Retrying in {wait}s "
                        f"(attempt {attempt + 1}/{empty_cap}). "
                        f"Note: empty-response retries are capped at "
                        f"{EMPTY_RESPONSE_MAX_RETRIES} because this is rarely "
                        f"a transient rate limit on small payloads."
                    )
                    time.sleep(wait)
                    continue

                if self._key_pool and current_key:
                    self._key_pool.mark_success(current_key)
                return response
            except RateLimitError as e:
                # Key pool: mark the offending key and rotate immediately.
                if self._key_pool and current_key:
                    self._key_pool.mark_rate_limited(current_key, retry_after=60.0)
                    # When we have other healthy keys, skip the sleep -- the
                    # next iteration will pick a different key automatically.
                    if attempt < retries:
                        logger.info(
                            "[retry] Key pool rotating away from ...%s on 429",
                            current_key[-6:],
                        )
                        continue

                # Dump full request to file for debugging
                messages = kwargs.get("messages", [])
                token_count, token_method = _estimate_tokens(model, messages)
                dump_path = _dump_failed_request(
                    model=model,
                    kwargs=kwargs,
                    error_type="rate_limit",
                    attempt=attempt,
                )
                if attempt == retries:
                    logger.error(
                        f"[retry] GAVE UP on {model} after {retries + 1} "
                        f"attempts -- rate limit error: {e!s}. "
                        f"~{token_count} tokens ({token_method}). "
                        f"Full request dumped to: {dump_path}"
                    )
                    raise
                wait = _compute_retry_delay(attempt, exception=e, jitter=True)
                logger.warning(
                    f"[retry] {model} rate limited (429): {e!s}. "
                    f"~{token_count} tokens ({token_method}). "
                    f"Full request dumped to: {dump_path}. "
                    f"Retrying in {wait}s "
                    f"(attempt {attempt + 1}/{retries})"
                )
                time.sleep(wait)
            except Exception as auth_exc:
                # Smoking-gun log line on auth rejections (401/403). The
                # captured fp here is what the runtime actually sent —
                # cross-reference with the desktop's most-recent
                # ``[auth] configureLocalLlm pushing streamToken=…`` log
                # to tell whether the runtime is holding a stale token
                # snapshot vs. the proxy revoking a token within its TTL.
                _err_type, _status = _classify_llm_error(auth_exc)
                if _status in (401, 403):
                    logger.error(
                        "[hive-auth] LLM call rejected: model=%s status=%s api_key=%s hive_proxy=%s err=%s",
                        kwargs.get("model"),
                        _status,
                        _call_key_fp,
                        self._hive_proxy_auth,
                        str(auth_exc)[:200],
                    )
                raise
        # unreachable, but satisfies type checker
        raise RuntimeError("Exhausted rate limit retries")

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
    ) -> LLMResponse:
        """Generate a completion using LiteLLM.

        ``max_tokens=None`` resolves to ``llm.aux_max_tokens`` (config) so an
        unspecified budget can't silently starve a thinking model.
        """
        if max_tokens is None:
            max_tokens = get_aux_max_tokens()
        self._refresh_api_key()
        # Codex ChatGPT backend requires streaming — delegate to the unified
        # async streaming path which properly handles tool calls.
        if self._codex_backend:
            return asyncio.run(
                self.acomplete(
                    messages=messages,
                    system=system,
                    tools=tools,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    json_mode=json_mode,
                    max_retries=max_retries,
                )
            )

        # Prepare messages with system prompt
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)
        _apply_history_cache_breakpoint(full_messages, self.model)

        # Add JSON mode via prompt engineering (works across all providers)
        if json_mode:
            _append_json_instruction(full_messages)

        # Build kwargs
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            **self.extra_kwargs,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base

        # Add tools if provided
        if tools:
            kwargs["tools"] = [self._tool_to_openai_format(t) for t in tools]
            if _is_ollama_model(self.model):
                # Ollama requires explicit tool_choice=auto for function calling
                # so future readers don't have to guess.
                kwargs.setdefault("tool_choice", "auto")
            elif self._hive_proxy_auth:
                # The Hive LLM proxy fronts GLM, which drifts into "explain
                # the plan" mode on long-context turns instead of emitting
                # tool_use blocks (verified 2026-04-28: tool_choice=null →
                # text-only stop=stop; tool_choice=required → clean
                # tool_use). Force a tool call when tools are available
                # so queens can't get stuck in chat mode. Callers that
                # legitimately want a non-tool turn can override via
                # extra_kwargs.
                kwargs.setdefault("tool_choice", "required")

        # Add response_format for structured output
        # LiteLLM passes this through to the underlying provider
        if response_format:
            kwargs["response_format"] = response_format

        # Make the call
        response = self._completion_with_rate_limit_retry(max_retries=max_retries, **kwargs)

        # Extract content
        content = response.choices[0].message.content or ""

        # Get usage info.
        # NOTE: completion_tokens includes reasoning/thinking tokens for models
        # that use them (o1, gpt-5-mini, etc.). LiteLLM does not reliably expose
        # usage.completion_tokens_details.reasoning_tokens across all providers.
        # This means output_tokens may be inflated for reasoning models.
        # Compaction is unaffected — it uses prompt_tokens (input-side only).
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        cached_tokens, cache_creation_tokens = _extract_cache_tokens(usage)
        cost_usd = _extract_cost(response, self.model)
        credits = _extract_credits(response)

        return LLMResponse(
            content=content,
            model=response.model or self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cost_usd=cost_usd,
            credits=credits,
            stop_reason=response.choices[0].finish_reason or "",
            raw_response=response,
        )

    # ------------------------------------------------------------------
    # Async variants — non-blocking on the event loop
    # ------------------------------------------------------------------

    async def _acompletion_with_rate_limit_retry(self, max_retries: int | None = None, **kwargs: Any) -> Any:
        """Async version of _completion_with_rate_limit_retry.

        Uses litellm.acompletion and asyncio.sleep instead of blocking calls.
        When a :class:`KeyPool` is configured, rate-limited keys are rotated.
        """
        self._apply_usage_agent_header(kwargs)
        model = kwargs.get("model", self.model)
        retries = max_retries if max_retries is not None else RATE_LIMIT_MAX_RETRIES
        for attempt in range(retries + 1):
            # Rotate key from pool when available.
            current_key: str | None = None
            if self._key_pool:
                current_key = self._key_pool.get_key()
                kwargs["api_key"] = current_key
            try:
                _install_request_holder()
                _log_llm_call(kwargs, attempt=attempt)
                try:
                    response = await litellm.acompletion(**kwargs)  # type: ignore[union-attr]
                except Exception as llm_exc:
                    # Hive streamToken expired/revoked? Force a refresh
                    # right now and retry this same LLM call ONCE with
                    # the new token. Guards against the race where the
                    # background streamtoken_refresh loop hasn't ticked
                    # yet but the proxy already rejected. Single retry
                    # so a persistent backend outage doesn't loop.
                    if _is_hive_stream_token_invalid(llm_exc) and not kwargs.get("_hive_token_refresh_attempted"):
                        kwargs["_hive_token_refresh_attempted"] = True
                        try:
                            from framework.server.streamtoken_refresh import (
                                try_refresh_now,
                            )

                            new_token = await try_refresh_now()
                        except Exception:
                            logger.warning(
                                "[hive-auth] try_refresh_now import/call failed",
                                exc_info=True,
                            )
                            new_token = None
                        if new_token:
                            logger.info(
                                "[hive-auth] hive_stream_token_invalid on %s → refreshed token + retrying ONCE",
                                kwargs.get("model"),
                            )
                            kwargs["api_key"] = new_token
                            response = await litellm.acompletion(**kwargs)  # type: ignore[union-attr]
                        else:
                            # Refresh failed → bubble the original auth
                            # error so the queen surfaces it cleanly.
                            raise
                    else:
                        raise
                # ``_hive_token_refresh_attempted`` is a per-call flag, not
                # a per-key flag; strip before any subsequent retry so it
                # doesn't get passed to litellm as an unknown kwarg the
                # next loop iteration. (litellm.acompletion ignores unknown
                # kwargs today, but the cleanup is defensive.)
                kwargs.pop("_hive_token_refresh_attempted", None)

                content = response.choices[0].message.content if response.choices else None
                has_tool_calls = bool(response.choices and response.choices[0].message.tool_calls)
                if not content and not has_tool_calls:
                    messages = kwargs.get("messages", [])
                    last_role = next(
                        (m["role"] for m in reversed(messages) if m.get("role") != "system"),
                        None,
                    )
                    if last_role == "assistant":
                        logger.debug("[async-retry] Empty response after assistant message — expected, not retrying.")
                        return response

                    finish_reason = response.choices[0].finish_reason if response.choices else "unknown"
                    token_count, token_method = _estimate_tokens(model, messages)
                    dump_path = _dump_failed_request(
                        model=model,
                        kwargs=kwargs,
                        error_type="empty_response",
                        attempt=attempt,
                    )
                    logger.warning(
                        f"[async-retry] Empty response - {len(messages)} messages, "
                        f"~{token_count} tokens ({token_method}). "
                        f"Full request dumped to: {dump_path}"
                    )

                    # finish_reason=length means the model exhausted max_tokens
                    # before producing content. Retrying with the same max_tokens
                    # will never help — return immediately instead of looping.
                    if finish_reason == "length":
                        max_tok = kwargs.get("max_tokens", "unset")
                        logger.error(
                            f"[async-retry] {model} returned empty content with "
                            f"finish_reason=length (max_tokens={max_tok}). "
                            f"The model exhausted its token budget before "
                            f"producing visible output. Increase max_tokens "
                            f"or use a different model. Not retrying."
                        )
                        return response

                    # Use a much lower retry cap for empty-response
                    # recoveries than for real exceptions. These are
                    # almost never transient (see EMPTY_RESPONSE_MAX_RETRIES
                    # rationale at the top of the file).
                    empty_cap = min(retries, EMPTY_RESPONSE_MAX_RETRIES)
                    if attempt >= empty_cap:
                        logger.error(
                            f"[async-retry] GAVE UP on {model} after "
                            f"{attempt + 1} attempts — empty response "
                            f"(finish_reason={finish_reason}, "
                            f"choices={len(response.choices) if response.choices else 0}). "
                            f"This is almost never a rate limit despite the "
                            f"earlier log message — check the dumped request "
                            f"at {dump_path} for poisoned conversation state "
                            f"(dangling tool_result after compaction), a "
                            f"safety-filter trigger in the prompt, or a "
                            f"malformed tool schema."
                        )
                        return response
                    wait = _compute_retry_delay(attempt)
                    logger.warning(
                        f"[async-retry] {model} returned empty response "
                        f"(finish_reason={finish_reason}, "
                        f"choices={len(response.choices) if response.choices else 0}). "
                        f"Retrying in {wait}s "
                        f"(attempt {attempt + 1}/{empty_cap}). "
                        f"Note: empty-response retries are capped at "
                        f"{EMPTY_RESPONSE_MAX_RETRIES} because this is rarely "
                        f"a transient rate limit on small payloads."
                    )
                    await asyncio.sleep(wait)
                    continue

                if self._key_pool and current_key:
                    self._key_pool.mark_success(current_key)
                return response
            except RateLimitError as e:
                # Key pool: mark the offending key and rotate immediately.
                if self._key_pool and current_key:
                    self._key_pool.mark_rate_limited(current_key, retry_after=60.0)
                    if attempt < retries:
                        logger.info(
                            "[async-retry] Key pool rotating away from ...%s on 429",
                            current_key[-6:],
                        )
                        continue

                messages = kwargs.get("messages", [])
                token_count, token_method = _estimate_tokens(model, messages)
                dump_path = _dump_failed_request(
                    model=model,
                    kwargs=kwargs,
                    error_type="rate_limit",
                    attempt=attempt,
                )
                if attempt == retries:
                    logger.error(
                        f"[async-retry] GAVE UP on {model} after {retries + 1} "
                        f"attempts -- rate limit error: {e!s}. "
                        f"~{token_count} tokens ({token_method}). "
                        f"Full request dumped to: {dump_path}"
                    )
                    raise
                wait = _compute_retry_delay(attempt, exception=e, jitter=True)
                logger.warning(
                    f"[async-retry] {model} rate limited (429): {e!s}. "
                    f"~{token_count} tokens ({token_method}). "
                    f"Full request dumped to: {dump_path}. "
                    f"Retrying in {wait}s "
                    f"(attempt {attempt + 1}/{retries})"
                )
                await asyncio.sleep(wait)
        raise RuntimeError("Exhausted rate limit retries")

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
        system_dynamic_suffix: str | None = None,
    ) -> LLMResponse:
        """Async version of complete(). Uses litellm.acompletion — non-blocking.

        ``max_tokens=None`` resolves to ``llm.aux_max_tokens`` (config).

        ``system_dynamic_suffix`` is an optional per-turn tail. When set and
        the provider honors ``cache_control``, ``system`` is sent as the
        cached prefix and the suffix trails as an uncached second content
        block. Otherwise the two strings are concatenated into a single
        system message (legacy behavior).
        """
        if max_tokens is None:
            max_tokens = get_aux_max_tokens()
        self._refresh_api_key()
        # Codex ChatGPT backend requires streaming — route through stream() which
        # already handles Codex quirks and has proper tool call accumulation.
        if self._codex_backend:
            stream_iter = self.stream(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
                response_format=response_format,
                json_mode=json_mode,
                system_dynamic_suffix=system_dynamic_suffix,
            )
            return await self._collect_stream_to_response(stream_iter)

        full_messages: list[dict[str, Any]] = []
        if self._claude_code_oauth:
            billing = _claude_code_billing_header(messages)
            full_messages.append({"role": "system", "content": billing})
        sys_msg = _build_system_message(system, system_dynamic_suffix, self.model)
        if sys_msg is not None:
            full_messages.append(sys_msg)
        full_messages.extend(messages)
        _apply_history_cache_breakpoint(full_messages, self.model)

        if json_mode:
            _append_json_instruction(full_messages)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            **self.extra_kwargs,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if tools:
            kwargs["tools"] = [self._tool_to_openai_format(t) for t in tools]
            if _is_ollama_model(self.model):
                # Ollama requires explicit tool_choice=auto for function calling
                # so future readers don't have to guess.
                kwargs.setdefault("tool_choice", "auto")
            elif self._hive_proxy_auth:
                # See `complete()` for the rationale: GLM behind the Hive
                # proxy needs forcing or it goes chat-mode on long contexts.
                kwargs.setdefault("tool_choice", "required")
        if response_format:
            kwargs["response_format"] = response_format

        response = await self._acompletion_with_rate_limit_retry(max_retries=max_retries, **kwargs)

        content = response.choices[0].message.content or ""
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        cached_tokens, cache_creation_tokens = _extract_cache_tokens(usage)
        cost_usd = _extract_cost(response, self.model)
        credits = _extract_credits(response)

        return LLMResponse(
            content=content,
            model=response.model or self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cost_usd=cost_usd,
            credits=credits,
            stop_reason=response.choices[0].finish_reason or "",
            raw_response=response,
        )

    def _tool_to_openai_format(self, tool: Tool) -> dict[str, Any]:
        """Convert Tool to OpenAI function calling format.

        Tool descriptions and parameter docstrings are sent verbatim to
        the LLM. Many of them mention ``~/.hive/...`` as the canonical
        location of colonies/skills/memories, but on the desktop the
        runtime's HIVE_HOME lives elsewhere — so we rewrite ``~/.hive``
        to the active HIVE_HOME on the way out, deeply (descriptions
        nested inside ``parameters.properties`` are common).
        """
        from framework.config import resolve_hive_paths_deep

        return resolve_hive_paths_deep(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": tool.parameters.get("properties", {}),
                        "required": tool.parameters.get("required", []),
                    },
                },
            }
        )

    def _is_anthropic_model(self) -> bool:
        """Return True when the configured model targets Anthropic."""
        model = (self.model or "").lower()
        return model.startswith("anthropic/") or model.startswith("claude-")

    def _is_minimax_model(self) -> bool:
        """Return True when the configured model targets MiniMax."""
        model = (self.model or "").lower()
        return model.startswith("minimax/") or model.startswith("minimax-")

    def _is_openrouter_model(self) -> bool:
        """Return True when the configured model targets OpenRouter."""
        model = (self.model or "").lower()
        if model.startswith("openrouter/"):
            return True
        api_base = (self.api_base or "").lower()
        return "openrouter.ai/api/v1" in api_base

    def _is_zai_openai_backend(self) -> bool:
        """Return True when using Z-AI's OpenAI-compatible chat endpoint."""
        model = (self.model or "").lower()
        api_base = (self.api_base or "").lower()
        return "api.z.ai" in api_base or model.startswith("openai/glm-") or model == "glm-5"

    def _should_use_openrouter_tool_compat(
        self,
        error: BaseException,
        tools: list[Tool] | None,
    ) -> bool:
        """Return True when OpenRouter rejects native tool use for the model."""
        if not tools or not self._is_openrouter_model():
            return False
        error_text = str(error).lower()
        return "openrouter" in error_text and any(snippet in error_text for snippet in OPENROUTER_TOOL_COMPAT_ERROR_SNIPPETS)

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any] | None:
        """Extract the first JSON object from a model response."""
        candidates = [text.strip()]

        stripped = text.strip()
        if stripped.startswith("```"):
            fence_lines = stripped.splitlines()
            if len(fence_lines) >= 3:
                candidates.append("\n".join(fence_lines[1:-1]).strip())

        decoder = json.JSONDecoder()
        for candidate in candidates:
            if not candidate:
                continue
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                return parsed

            for start_idx, char in enumerate(candidate):
                if char != "{":
                    continue
                try:
                    parsed, _ = decoder.raw_decode(candidate[start_idx:])
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
        return None

    def _parse_openrouter_tool_compat_response(
        self,
        content: str,
        tools: list[Tool],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Parse JSON tool-compat output into assistant text and tool calls."""
        payload = self._extract_json_object(content)
        if payload is None:
            text_tool_content, text_tool_calls = self._parse_openrouter_text_tool_calls(
                content,
                tools,
            )
            if text_tool_calls:
                logger.info(
                    "[openrouter-tool-compat] Parsed textual tool-call markers for %s",
                    self.model,
                )
                return text_tool_content, text_tool_calls
            logger.info(
                "[openrouter-tool-compat] %s returned non-JSON fallback content; treating it as plain text.",
                self.model,
            )
            return content.strip(), []

        assistant_text = payload.get("assistant_response")
        if not isinstance(assistant_text, str):
            assistant_text = payload.get("content")
        if not isinstance(assistant_text, str):
            assistant_text = payload.get("response")
        if not isinstance(assistant_text, str):
            assistant_text = ""

        tool_calls_raw = payload.get("tool_calls")
        if not tool_calls_raw and {"name", "arguments"} <= payload.keys():
            tool_calls_raw = [payload]
        elif isinstance(payload.get("tool_call"), dict):
            tool_calls_raw = [payload["tool_call"]]

        if not isinstance(tool_calls_raw, list):
            tool_calls_raw = []

        allowed_tool_names = {tool.name for tool in tools}
        tool_calls: list[dict[str, Any]] = []
        compat_prefix = f"openrouter_compat_{time.time_ns()}"

        for idx, raw_call in enumerate(tool_calls_raw):
            if not isinstance(raw_call, dict):
                continue

            function_block = raw_call.get("function")
            function_name = (
                raw_call.get("name") or raw_call.get("tool_name") or (function_block.get("name") if isinstance(function_block, dict) else None)
            )
            if not isinstance(function_name, str) or function_name not in allowed_tool_names:
                if function_name:
                    logger.warning(
                        "[openrouter-tool-compat] Ignoring unknown tool '%s' for model %s",
                        function_name,
                        self.model,
                    )
                continue

            arguments = raw_call.get("arguments")
            if arguments is None:
                arguments = raw_call.get("tool_input")
            if arguments is None:
                arguments = raw_call.get("input")
            if arguments is None and isinstance(function_block, dict):
                arguments = function_block.get("arguments")
            if arguments is None:
                arguments = {}

            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"_raw": arguments}
            elif not isinstance(arguments, dict):
                arguments = {"value": arguments}

            tool_calls.append(
                {
                    "id": f"{compat_prefix}_{idx}",
                    "name": function_name,
                    "input": arguments,
                }
            )

        return assistant_text.strip(), tool_calls

    @staticmethod
    def _close_truncated_json_fragment(fragment: str) -> str:
        """Close a truncated JSON fragment by balancing quotes/brackets."""
        stack: list[str] = []
        in_string = False
        escaped = False
        normalized = fragment.rstrip()

        while normalized and normalized[-1] in ",:{[":
            normalized = normalized[:-1].rstrip()

        for char in normalized:
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char in "{[":
                stack.append(char)
            elif char == "}" and stack and stack[-1] == "{":
                stack.pop()
            elif char == "]" and stack and stack[-1] == "[":
                stack.pop()

        if in_string:
            if escaped:
                normalized = normalized[:-1]
            normalized += '"'

        for opener in reversed(stack):
            normalized += "}" if opener == "{" else "]"

        return normalized

    def _repair_truncated_tool_arguments(self, raw_arguments: str) -> dict[str, Any] | None:
        """Try to recover a truncated JSON object from tool-call arguments."""
        stripped = raw_arguments.strip()
        if not stripped or stripped[0] != "{":
            return None

        max_trim = min(len(stripped), 256)
        for trim in range(max_trim + 1):
            candidate = stripped[: len(stripped) - trim].rstrip()
            if not candidate:
                break
            candidate = self._close_truncated_json_fragment(candidate)
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _parse_tool_call_arguments(self, raw_arguments: str, tool_name: str) -> dict[str, Any]:
        """Parse streamed tool arguments, repairing truncation when possible."""
        try:
            parsed = json.loads(raw_arguments) if raw_arguments else {}
        except json.JSONDecodeError:
            parsed = None

        if isinstance(parsed, dict):
            return parsed

        repaired = self._repair_truncated_tool_arguments(raw_arguments)
        if repaired is not None:
            logger.warning(
                "[tool-args] Recovered truncated arguments for %s on %s",
                tool_name,
                self.model,
            )
            return repaired

        raise ValueError(f"Failed to parse tool call arguments for '{tool_name}' (likely truncated JSON).")

    def _parse_openrouter_text_tool_calls(
        self,
        content: str,
        tools: list[Tool],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Parse textual OpenRouter tool calls into synthetic tool calls.

        Supports both:
        - Marker wrapped payloads: <|tool_call_start|>...<|tool_call_end|>
        - Plain one-line tool calls: ask_user("...", ["..."])
        """
        tools_by_name = {tool.name: tool for tool in tools}
        compat_prefix = f"openrouter_compat_{time.time_ns()}"
        tool_calls: list[dict[str, Any]] = []
        segment_index = 0

        for match in OPENROUTER_TOOL_CALL_RE.finditer(content):
            parsed_calls = self._parse_openrouter_text_tool_call_block(
                block=match.group(1),
                tools_by_name=tools_by_name,
                compat_prefix=f"{compat_prefix}_{segment_index}",
            )
            if parsed_calls:
                segment_index += 1
                tool_calls.extend(parsed_calls)

        stripped_content = OPENROUTER_TOOL_CALL_RE.sub("", content)
        retained_lines: list[str] = []
        for line in stripped_content.splitlines():
            stripped_line = line.strip()
            if not stripped_line:
                retained_lines.append(line)
                continue

            candidate = stripped_line
            if candidate.startswith("`") and candidate.endswith("`") and len(candidate) > 1:
                candidate = candidate[1:-1].strip()

            parsed_calls = self._parse_openrouter_text_tool_call_block(
                block=candidate,
                tools_by_name=tools_by_name,
                compat_prefix=f"{compat_prefix}_{segment_index}",
            )
            if parsed_calls:
                segment_index += 1
                tool_calls.extend(parsed_calls)
                continue

            retained_lines.append(line)

        stripped_text = "\n".join(retained_lines).strip()
        return stripped_text, tool_calls

    def _parse_openrouter_text_tool_call_block(
        self,
        block: str,
        tools_by_name: dict[str, Tool],
        compat_prefix: str,
    ) -> list[dict[str, Any]]:
        """Parse a single textual tool-call block like [tool(arg='x')]."""
        try:
            parsed = ast.parse(block.strip(), mode="eval").body
        except SyntaxError:
            return []

        call_nodes = parsed.elts if isinstance(parsed, ast.List) else [parsed]
        tool_calls: list[dict[str, Any]] = []

        for call_index, call_node in enumerate(call_nodes):
            if not isinstance(call_node, ast.Call) or not isinstance(call_node.func, ast.Name):
                continue

            tool_name = call_node.func.id
            tool = tools_by_name.get(tool_name)
            if tool is None:
                continue

            try:
                tool_input = self._parse_openrouter_text_tool_call_arguments(
                    call_node=call_node,
                    tool=tool,
                )
            except (ValueError, SyntaxError):
                continue

            tool_calls.append(
                {
                    "id": f"{compat_prefix}_{call_index}",
                    "name": tool_name,
                    "input": tool_input,
                }
            )

        return tool_calls

    @staticmethod
    def _parse_openrouter_text_tool_call_arguments(
        call_node: ast.Call,
        tool: Tool,
    ) -> dict[str, Any]:
        """Parse positional/keyword args from a textual tool call."""
        properties = tool.parameters.get("properties", {})
        positional_keys = list(properties.keys())
        tool_input: dict[str, Any] = {}

        if len(call_node.args) > len(positional_keys):
            raise ValueError("Too many positional args for textual tool call")

        for idx, arg_node in enumerate(call_node.args):
            tool_input[positional_keys[idx]] = ast.literal_eval(arg_node)

        for kwarg in call_node.keywords:
            if kwarg.arg is None:
                raise ValueError("Star args are not supported in textual tool calls")
            tool_input[kwarg.arg] = ast.literal_eval(kwarg.value)

        return tool_input

    def _build_openrouter_tool_compat_messages(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        system_dynamic_suffix: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build a JSON-only prompt for models without native tool support."""
        tool_specs = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in tools
        ]
        compat_instruction = (
            "Tool compatibility mode is active because this OpenRouter model does not support "
            "native function calling on the routed provider.\n"
            "Return exactly one JSON object and nothing else.\n"
            'Schema: {"assistant_response": string, '
            '"tool_calls": [{"name": string, "arguments": object}]}\n'
            "Rules:\n"
            "- If a tool is required, put one or more entries in tool_calls "
            "and do not invent tool results.\n"
            "- If no tool is required, set tool_calls to [] and put the full "
            "answer in assistant_response.\n"
            "- Only use tool names from the allowed tool list.\n"
            "- arguments must always be valid JSON objects.\n"
            f"Allowed tools:\n{json.dumps(tool_specs, ensure_ascii=True)}"
        )
        compat_system = compat_instruction if not system else f"{system}\n\n{compat_instruction}"

        # If the routed sub-provider honors cache_control (e.g.
        # openrouter/anthropic/*), split the static prefix from the dynamic
        # suffix so the prefix stays cache-warm across turns. Otherwise fall
        # back to a single concatenated string.
        system_message = _build_system_message(
            compat_system,
            system_dynamic_suffix,
            self.model,
        )

        full_messages: list[dict[str, Any]] = []
        if system_message is not None:
            full_messages.append(system_message)
        full_messages.extend(messages)
        _apply_history_cache_breakpoint(full_messages, self.model)
        return [
            message
            for message in full_messages
            if not (message.get("role") == "assistant" and not message.get("content") and not message.get("tool_calls"))
        ]

    async def _acomplete_via_openrouter_tool_compat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        max_tokens: int,
        system_dynamic_suffix: str | None = None,
    ) -> LLMResponse:
        """Emulate tool calling via JSON when OpenRouter rejects native tools.

        When the routed sub-provider honors ``cache_control`` (e.g.
        ``openrouter/anthropic/*``), the message builder splits the static
        prefix from the dynamic suffix so the prefix stays cache-warm.
        Otherwise the suffix is concatenated into a single system string.
        """
        full_messages = self._build_openrouter_tool_compat_messages(
            messages,
            system,
            tools,
            system_dynamic_suffix=system_dynamic_suffix,
        )
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            **self.extra_kwargs,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base

        response = await self._acompletion_with_rate_limit_retry(**kwargs)
        raw_content = response.choices[0].message.content or ""
        assistant_text, tool_calls = self._parse_openrouter_tool_compat_response(
            raw_content,
            tools,
        )
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        cached_tokens, cache_creation_tokens = _extract_cache_tokens(usage)
        cost_usd = _extract_cost(response, self.model)
        credits = _extract_credits(response)
        stop_reason = "tool_calls" if tool_calls else (response.choices[0].finish_reason or "stop")

        return LLMResponse(
            content=assistant_text,
            model=response.model or self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cost_usd=cost_usd,
            credits=credits,
            stop_reason=stop_reason,
            raw_response={
                "compat_mode": "openrouter_tool_emulation",
                "tool_calls": tool_calls,
                "response": response,
            },
        )

    async def _stream_via_openrouter_tool_compat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        max_tokens: int,
        system_dynamic_suffix: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Fallback stream for OpenRouter models without native tool support."""
        from framework.llm.stream_events import (
            FinishEvent,
            StreamErrorEvent,
            TextDeltaEvent,
            TextEndEvent,
            ToolCallEvent,
        )

        logger.info(
            "[openrouter-tool-compat] Using compatibility mode for %s",
            self.model,
        )
        try:
            response = await self._acomplete_via_openrouter_tool_compat(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
                system_dynamic_suffix=system_dynamic_suffix,
            )
        except Exception as e:
            err_type, upstream = _classify_llm_error(e)
            yield StreamErrorEvent(
                error=str(e),
                recoverable=False,
                error_type=err_type,
                upstream_status=upstream,
            )
            return

        raw_response = response.raw_response if isinstance(response.raw_response, dict) else {}
        tool_calls = raw_response.get("tool_calls", [])

        if response.content:
            yield TextDeltaEvent(content=response.content, snapshot=response.content)
            yield TextEndEvent(full_text=response.content)

        for tool_call in tool_calls:
            yield ToolCallEvent(
                tool_use_id=tool_call["id"],
                tool_name=tool_call["name"],
                tool_input=tool_call["input"],
            )

        yield FinishEvent(
            stop_reason=response.stop_reason,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cached_tokens=response.cached_tokens,
            cache_creation_tokens=response.cache_creation_tokens,
            cost_usd=response.cost_usd,
            credits=response.credits,
            model=response.model,
        )

    async def _stream_via_nonstream_completion(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool] | None,
        max_tokens: int,
        response_format: dict[str, Any] | None,
        json_mode: bool,
        system_dynamic_suffix: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Fallback path: convert non-stream completion to stream events.

        Some providers currently fail in LiteLLM's chunk parser for stream=True.
        For those providers we do a regular async completion and emit equivalent
        stream events so higher layers continue to work.
        """
        from framework.llm.stream_events import (
            FinishEvent,
            StreamErrorEvent,
            TextDeltaEvent,
            TextEndEvent,
            ToolCallEvent,
        )

        try:
            response = await self.acomplete(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
                response_format=response_format,
                json_mode=json_mode,
                system_dynamic_suffix=system_dynamic_suffix,
            )
        except Exception as e:
            err_type, upstream = _classify_llm_error(e)
            yield StreamErrorEvent(
                error=str(e),
                recoverable=False,
                error_type=err_type,
                upstream_status=upstream,
            )
            return

        raw = response.raw_response
        tool_calls = []
        if raw and hasattr(raw, "choices") and raw.choices:
            msg = raw.choices[0].message
            tool_calls = msg.tool_calls or []

        for tc in tool_calls:
            args = tc.function.arguments if tc.function else ""
            parsed_args = self._parse_tool_call_arguments(
                args,
                tc.function.name if tc.function else "",
            )
            yield ToolCallEvent(
                tool_use_id=getattr(tc, "id", ""),
                tool_name=tc.function.name if tc.function else "",
                tool_input=parsed_args,
            )

        if response.content:
            yield TextDeltaEvent(content=response.content, snapshot=response.content)
            yield TextEndEvent(full_text=response.content)

        yield FinishEvent(
            stop_reason=response.stop_reason or "stop",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cached_tokens=response.cached_tokens,
            cache_creation_tokens=response.cache_creation_tokens,
            cost_usd=response.cost_usd,
            credits=response.credits,
            model=response.model,
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        system_dynamic_suffix: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a completion via litellm.acompletion(stream=True).

        ``max_tokens=None`` resolves to ``llm.max_tokens`` via get_max_tokens().

        Yields StreamEvent objects as chunks arrive from the provider.
        Tool call arguments are accumulated across chunks and yielded as
        a single ToolCallEvent with fully parsed JSON when complete.

        Empty responses (e.g. Gemini stealth rate-limits that return 200
        with no content) are retried with exponential backoff, mirroring
        the retry behaviour of ``_completion_with_rate_limit_retry``.

        ``system_dynamic_suffix`` is an optional per-turn tail. See
        ``acomplete`` docstring for the two-block split semantics.
        """
        if max_tokens is None:
            max_tokens = get_max_tokens()
        self._refresh_api_key()
        from framework.llm.stream_events import (
            FinishEvent,
            ReasoningDeltaEvent,
            StreamErrorEvent,
            TextDeltaEvent,
            TextEndEvent,
            ToolCallEvent,
        )

        # MiniMax currently fails in litellm's stream chunk parser for some
        # responses (missing "id" in stream chunks). Use non-stream fallback.
        if self._is_minimax_model():
            async for event in self._stream_via_nonstream_completion(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
                response_format=response_format,
                json_mode=json_mode,
                system_dynamic_suffix=system_dynamic_suffix,
            ):
                yield event
            return

        if tools and self._is_openrouter_model() and _is_openrouter_tool_compat_cached(self.model):
            async for event in self._stream_via_openrouter_tool_compat(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
                system_dynamic_suffix=system_dynamic_suffix,
            ):
                yield event
            return

        full_messages: list[dict[str, Any]] = []
        if self._claude_code_oauth:
            billing = _claude_code_billing_header(messages)
            full_messages.append({"role": "system", "content": billing})
        sys_msg = _build_system_message(system, system_dynamic_suffix, self.model)
        if sys_msg is not None:
            full_messages.append(sys_msg)
        full_messages.extend(messages)
        _apply_history_cache_breakpoint(full_messages, self.model)

        if logger.isEnabledFor(logging.DEBUG) and full_messages:
            import json as _json
            from datetime import datetime as _dt

            from framework.config import HIVE_HOME as _HIVE_HOME

            _debug_dir = _HIVE_HOME / "debug_logs"
            _debug_dir.mkdir(parents=True, exist_ok=True)
            _ts = _dt.now().strftime("%Y%m%d_%H%M%S_%f")
            _dump_file = _debug_dir / f"llm_request_{_ts}.json"
            _summary = []
            for _mi, _m in enumerate(full_messages):
                _role = _m.get("role", "?")
                _c = _m.get("content")
                _tc = _m.get("tool_calls")
                _tcid = _m.get("tool_call_id")
                _summary.append(
                    {
                        "idx": _mi,
                        "role": _role,
                        "content_length": len(str(_c)) if _c else 0,
                        "content_preview": str(_c)[:200] if _c else repr(_c),
                        "has_tool_calls": bool(_tc),
                        "tool_call_count": len(_tc) if _tc else 0,
                        "tool_call_id": _tcid,
                    }
                )
            try:
                _dump_file.write_text(_json.dumps(_summary, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.debug("[LLM-MSG] %d messages dumped to %s", len(full_messages), _dump_file)
            except Exception:
                pass

        # Codex Responses API requires an `instructions` field (system prompt).
        # Inject a minimal one when callers don't provide a system message.
        if self._codex_backend and not any(m["role"] == "system" for m in full_messages):
            full_messages.insert(0, {"role": "system", "content": "You are a helpful assistant."})

        # Add JSON mode via prompt engineering (works across all providers)
        if json_mode:
            _append_json_instruction(full_messages)

        # Remove ghost empty assistant messages (content="" and no tool_calls).
        # These arise when a model returns an empty stream after a tool result
        # (an "expected" no-op turn). Keeping them in history confuses some
        # models (notably Codex/gpt-5.3) and causes cascading empty streams.
        full_messages = [m for m in full_messages if not (m.get("role") == "assistant" and not m.get("content") and not m.get("tool_calls"))]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "stream": True,
            **self.extra_kwargs,
        }
        # stream_options is OpenAI-specific; Anthropic rejects it with 400.
        # Only include it for providers that support it.
        if not self._is_anthropic_model():
            kwargs["stream_options"] = {"include_usage": True}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if tools:
            kwargs["tools"] = [self._tool_to_openai_format(t) for t in tools]
            if _is_ollama_model(self.model):
                # Ollama requires explicit tool_choice=auto for function calling
                # so future readers don't have to guess.
                kwargs.setdefault("tool_choice", "auto")
            elif self._hive_proxy_auth:
                # See `complete()` for the rationale: GLM behind the Hive
                # proxy needs forcing or it goes chat-mode on long contexts.
                kwargs.setdefault("tool_choice", "required")
        if response_format:
            kwargs["response_format"] = response_format
        if logger.isEnabledFor(logging.DEBUG):
            _tool_names_sample = sorted(t.name for t in (tools or []))[:8]
            _has_suggest_colony = any(t.name == "suggest_colony" for t in (tools or []))
            logger.debug(
                "[stream] model=%s hive_proxy=%s tool_count=%d tool_choice=%r has_suggest_colony=%s tool_names_sample=%s",
                self.model,
                self._hive_proxy_auth,
                len(tools or []),
                kwargs.get("tool_choice"),
                _has_suggest_colony,
                _tool_names_sample,
            )
        # The Codex ChatGPT backend (Responses API) rejects several params.
        if self._codex_backend:
            kwargs.pop("max_tokens", None)
            kwargs.pop("stream_options", None)
            # Pass store directly to OpenAI in case litellm drops it as unknown
            if "extra_body" not in kwargs:
                kwargs["extra_body"] = {}
            kwargs["extra_body"]["store"] = False

        request_summary = _summarize_request_for_log(kwargs)
        if request_summary["system_only"]:
            logger.warning(
                "[stream] %s request has no non-system chat messages "
                "(api_base=%s tools=%d system_chars=%d). "
                "Some chat-completions backends reject system-only payloads.",
                self.model,
                self.api_base,
                request_summary["tool_count"],
                sum(message.get("text_chars", 0) for message in request_summary["messages"] if message.get("role") == "system"),
            )
            if self._is_zai_openai_backend():
                logger.warning(
                    "[stream] %s appears to be using Z-AI/GLM's OpenAI-compatible backend. "
                    "This backend has rejected system-only payloads with "
                    "'The messages parameter is illegal.' in prior requests.",
                    self.model,
                )

        self._apply_usage_agent_header(kwargs)

        # Tracked across the outer loop so an empty stream immediately after a
        # 429 can adopt the rate-limit backoff instead of the fast 1s retry.
        last_rate_limit_attempt: int | None = None
        last_rate_limit_exc: BaseException | None = None

        for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
            # Post-stream events (ToolCall, TextEnd, Finish) are buffered
            # because they depend on the full stream.  TextDeltaEvents are
            # yielded immediately so callers see tokens in real time.
            tail_events: list[StreamEvent] = []
            accumulated_text = ""
            tool_calls_acc: dict[int, dict[str, str]] = {}
            _last_tool_idx = 0  # tracks most recently opened tool call slot
            # Reasoning/`thinking` blocks streamed by reasoning models.
            # ``thinking_acc`` holds blocks whose signature has fully
            # arrived (safe to echo back); ``_thinking_current`` is the
            # block still being assembled from deltas.
            thinking_acc: list[dict[str, Any]] = []
            _thinking_current: dict[str, Any] | None = None
            _saw_reasoning = False  # logged once when reasoning deltas first appear
            input_tokens = 0
            output_tokens = 0
            stream_finish_reason: str | None = None

            try:
                _install_request_holder()
                _log_llm_call(kwargs, stream=True, attempt=attempt)
                response = await litellm.acompletion(**kwargs)  # type: ignore[union-attr]

                async for chunk in response:
                    # Capture usage from the trailing usage-only chunk that
                    # stream_options={"include_usage": True} sends with empty choices.
                    if not chunk.choices:
                        usage = getattr(chunk, "usage", None)
                        if usage:
                            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                            output_tokens = getattr(usage, "completion_tokens", 0) or 0
                            logger.debug(
                                "[tokens] trailing usage chunk: input=%d output=%d model=%s",
                                input_tokens,
                                output_tokens,
                                self.model,
                            )
                        else:
                            logger.debug(
                                "[tokens] empty-choices chunk with no usage (model=%s)",
                                self.model,
                            )
                        continue
                    choice = chunk.choices[0]

                    delta = choice.delta

                    # --- Text content — yield immediately for real-time streaming ---
                    if delta and delta.content:
                        accumulated_text += delta.content
                        yield TextDeltaEvent(
                            content=delta.content,
                            snapshot=accumulated_text,
                        )

                    # --- Reasoning / `thinking` blocks (accumulate across chunks) ---
                    # Reasoning models (DeepSeek, GLM via the hive-2.1 alias)
                    # emit `thinking` content blocks that MUST be echoed back
                    # verbatim — signature included — or the next request 400s.
                    # litellm streams them as incremental ``thinking_blocks``
                    # deltas; reassemble each block here and finalise it when
                    # its ``signature`` arrives.
                    # ``_reason_chunk`` collects reasoning text that arrived this
                    # chunk (from either transport below) so we can surface it as
                    # a ReasoningDeltaEvent — the visible-reasoning path for
                    # thinking models whose reasoning never lands in ``content``.
                    _reason_chunk = ""
                    _tb_delta = getattr(delta, "thinking_blocks", None) if delta else None
                    if _tb_delta:
                        for tb in _tb_delta:
                            if not isinstance(tb, dict):
                                tb = dict(tb)
                            btype = tb.get("type") or "thinking"
                            if btype == "redacted_thinking":
                                # Self-contained; no incremental signature.
                                thinking_acc.append({"type": "redacted_thinking", "data": tb.get("data", "")})
                                continue
                            if _thinking_current is None:
                                _thinking_current = {
                                    "type": "thinking",
                                    "thinking": "",
                                    "signature": "",
                                }
                            if tb.get("thinking"):
                                _thinking_current["thinking"] += tb["thinking"]
                                _reason_chunk += tb["thinking"]
                            if tb.get("signature"):
                                # Signature delta closes the block.
                                _thinking_current["signature"] = tb["signature"]
                                thinking_acc.append(_thinking_current)
                                _thinking_current = None
                    else:
                        # Some providers (z.ai GLM, DeepSeek) expose reasoning
                        # only via the OpenAI-compat ``reasoning_content`` string
                        # delta rather than Anthropic-style ``thinking_blocks``.
                        _rc = getattr(delta, "reasoning_content", None) if delta else None
                        if _rc:
                            _reason_chunk += _rc

                    if _reason_chunk:
                        if not _saw_reasoning:
                            _saw_reasoning = True
                            logger.info(
                                "[reasoning] model=%s streaming reasoning deltas (surfacing as ReasoningDeltaEvent)",
                                self.model,
                            )
                        yield ReasoningDeltaEvent(content=_reason_chunk)

                    # --- Tool calls (accumulate across chunks) ---
                    # The Codex/Responses API bridge (litellm bug) hardcodes
                    # index=0 on every ChatCompletionToolCallChunk, even for
                    # parallel tool calls.  We work around this by using tc.id
                    # (set on output_item.added events) as a "new tool call"
                    # signal and tracking the most recently opened slot for
                    # argument deltas that arrive with id=None.
                    if delta and delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index if hasattr(tc, "index") and tc.index is not None else 0

                            if tc.id:
                                # New tool call announced (or done event re-sent).
                                # Check if this id already has a slot.
                                existing_idx = next(
                                    (k for k, v in tool_calls_acc.items() if v["id"] == tc.id),
                                    None,
                                )
                                if existing_idx is not None:
                                    idx = existing_idx
                                elif idx in tool_calls_acc and tool_calls_acc[idx]["id"] not in (
                                    "",
                                    tc.id,
                                ):
                                    # Slot taken by a different call — assign new index
                                    idx = max(tool_calls_acc.keys()) + 1
                                _last_tool_idx = idx
                            else:
                                # Argument delta with no id — route to last opened slot
                                idx = _last_tool_idx

                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                            if tc.id:
                                tool_calls_acc[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls_acc[idx]["name"] = tc.function.name
                                if tc.function.arguments:
                                    tool_calls_acc[idx]["arguments"] += tc.function.arguments

                    # --- Finish ---
                    if choice.finish_reason:
                        # Kimi's 'pause_turn' means the model emitted tool
                        # calls and expects results — equivalent to 'tool_calls'.
                        if choice.finish_reason == "pause_turn":
                            choice.finish_reason = "tool_calls" if tool_calls_acc else "stop"
                        stream_finish_reason = choice.finish_reason
                        for _idx, tc_data in sorted(tool_calls_acc.items()):
                            parsed_args = self._parse_tool_call_arguments(
                                tc_data.get("arguments", ""),
                                tc_data.get("name", ""),
                            )
                            tail_events.append(
                                ToolCallEvent(
                                    tool_use_id=tc_data["id"],
                                    tool_name=tc_data["name"],
                                    tool_input=parsed_args,
                                )
                            )

                        if accumulated_text:
                            tail_events.append(TextEndEvent(full_text=accumulated_text))

                        # litellm's ``CustomStreamWrapper`` strips ``usage``
                        # from every chunk it yields to us, so ``chunk.usage``
                        # is always None at finish time for Anthropic streams.
                        # The original Usage objects survive on
                        # ``response.chunks`` (the internal pre-yield stash);
                        # scan there for the most recent one. This is also
                        # where ``credits`` (attached by the
                        # ``calculate_usage`` patch via ``model_extra``) lives.
                        usage = getattr(chunk, "usage", None)
                        if usage is None:
                            for _raw in reversed(getattr(response, "chunks", None) or []):
                                _u = getattr(_raw, "usage", None)
                                if _u is not None:
                                    usage = _u
                                    break
                        logger.debug(
                            "[tokens] finish-chunk raw usage: %r (type=%s)",
                            usage,
                            type(usage).__name__,
                        )
                        cached_tokens = 0
                        cache_creation_tokens = 0
                        if usage:
                            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                            output_tokens = getattr(usage, "completion_tokens", 0) or 0
                            cached_tokens, cache_creation_tokens = _extract_cache_tokens(usage)
                            logger.debug(
                                "[tokens] finish-chunk usage: input=%d output=%d cached=%d cache_creation=%d model=%s",
                                input_tokens,
                                output_tokens,
                                cached_tokens,
                                cache_creation_tokens,
                                self.model,
                            )

                        logger.debug(
                            "[tokens] finish event: input=%d output=%d cached=%d cache_creation=%d stop=%s model=%s",
                            input_tokens,
                            output_tokens,
                            cached_tokens,
                            cache_creation_tokens,
                            choice.finish_reason,
                            self.model,
                        )
                        cost_usd = _cost_from_tokens(
                            self.model,
                            input_tokens,
                            output_tokens,
                            cached_tokens,
                            cache_creation_tokens,
                        )
                        credits = _credits_from_usage(usage)
                        logger.debug(
                            "[credits] streaming finish-chunk: model=%s credits=%r usage_type=%s",
                            self.model,
                            credits,
                            type(usage).__name__ if usage is not None else None,
                        )
                        # A leftover ``_thinking_current`` with no signature
                        # cannot be echoed back (the API rejects unsigned
                        # thinking) — drop it and keep only finalised blocks.
                        tail_events.append(
                            FinishEvent(
                                stop_reason=choice.finish_reason,
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                cached_tokens=cached_tokens,
                                cache_creation_tokens=cache_creation_tokens,
                                cost_usd=cost_usd,
                                credits=credits,
                                model=self.model,
                                thinking_blocks=list(thinking_acc),
                            )
                        )

                # Fallback: LiteLLM strips usage from yielded chunks before
                # returning them to us, but appends the original chunk (with
                # usage intact) to response.chunks first.  Use LiteLLM's own
                # calculate_total_usage() on that accumulated list.
                if input_tokens == 0 and output_tokens == 0:
                    try:
                        from litellm.litellm_core_utils.streaming_handler import (
                            calculate_total_usage,
                        )

                        _chunks = getattr(response, "chunks", None)
                        if _chunks:
                            _usage = calculate_total_usage(chunks=_chunks)
                            input_tokens = _usage.prompt_tokens or 0
                            output_tokens = _usage.completion_tokens or 0
                            # `calculate_total_usage` aggregates token totals
                            # but discards `prompt_tokens_details` — which is
                            # where OpenRouter puts `cached_tokens` and
                            # `cache_write_tokens`. Recover them directly
                            # from the most recent chunk that carries usage.
                            # Same trick for ``credits`` (Hive proxy field):
                            # cumulative per-request, last value wins.
                            cached_tokens, cache_creation_tokens = 0, 0
                            credits: float | None = None
                            for _raw in reversed(_chunks):
                                _raw_usage = getattr(_raw, "usage", None)
                                if _raw_usage is None:
                                    continue
                                if credits is None:
                                    credits = _credits_from_usage(_raw_usage)
                                _cr, _cc = _extract_cache_tokens(_raw_usage)
                                if _cr or _cc:
                                    cached_tokens, cache_creation_tokens = _cr, _cc
                                    break
                            logger.debug(
                                "[tokens] post-loop chunks fallback: input=%d output=%d cached=%d cache_creation=%d model=%s",
                                input_tokens,
                                output_tokens,
                                cached_tokens,
                                cache_creation_tokens,
                                self.model,
                            )
                            cost_usd = _cost_from_tokens(
                                self.model,
                                input_tokens,
                                output_tokens,
                                cached_tokens,
                                cache_creation_tokens,
                            )
                            # Patch the FinishEvent already queued with 0 tokens
                            for _i, _ev in enumerate(tail_events):
                                if isinstance(_ev, FinishEvent) and _ev.input_tokens == 0:
                                    tail_events[_i] = FinishEvent(
                                        stop_reason=_ev.stop_reason,
                                        input_tokens=input_tokens,
                                        output_tokens=output_tokens,
                                        cached_tokens=cached_tokens,
                                        cache_creation_tokens=cache_creation_tokens,
                                        cost_usd=cost_usd,
                                        credits=credits if credits is not None else _ev.credits,
                                        model=_ev.model,
                                        thinking_blocks=_ev.thinking_blocks,
                                    )
                                    break
                    except Exception as _e:
                        logger.debug("[tokens] chunks fallback failed: %s", _e)

                # Check whether the stream produced any real content.
                # (If text deltas were yielded above, has_content is True
                # and we skip the retry path — nothing was yielded in vain.)
                has_content = accumulated_text or tool_calls_acc
                if not has_content:
                    # finish_reason=length means the model exhausted
                    # max_tokens before producing content. Retrying with
                    # the same max_tokens will never help.
                    if stream_finish_reason == "length":
                        max_tok = kwargs.get("max_tokens", "unset")
                        logger.error(
                            f"[stream] {self.model} returned empty content "
                            f"with finish_reason=length "
                            f"(max_tokens={max_tok}). The model exhausted "
                            f"its token budget before producing visible "
                            f"output. Increase max_tokens or use a "
                            f"different model. Not retrying."
                        )
                        for event in tail_events:
                            yield event
                        return

                    # Empty stream — always retry regardless of last message
                    # role.  Ghost empty streams after tool results are NOT
                    # expected no-ops; they create infinite loops when the
                    # conversation doesn't change between iterations.
                    # After retries, return the empty result and let the
                    # caller (EventLoopNode) decide how to handle it.
                    last_role = next(
                        (m["role"] for m in reversed(full_messages) if m.get("role") != "system"),
                        None,
                    )
                    if attempt < EMPTY_STREAM_MAX_RETRIES:
                        token_count, token_method = _estimate_tokens(
                            self.model,
                            full_messages,
                        )
                        # If a 429 just landed in the same loop, the empty
                        # response is likely backpressure-adjacent — use the
                        # rate-limit backoff (jittered) instead of 1s.
                        if last_rate_limit_attempt is not None and attempt - last_rate_limit_attempt <= 1:
                            wait = _compute_retry_delay(
                                attempt,
                                exception=last_rate_limit_exc,
                                jitter=True,
                            )
                        else:
                            wait = EMPTY_STREAM_RETRY_DELAY
                        logger.warning(
                            f"[stream-retry] {self.model} returned empty stream "
                            f"after {last_role} message — "
                            f"~{token_count} tokens ({token_method}). "
                            f"Retrying in {wait:.1f}s "
                            f"(attempt {attempt + 1}/{EMPTY_STREAM_MAX_RETRIES})"
                        )
                        await asyncio.sleep(wait)
                        continue

                    # All retries exhausted — dump the request for postmortem
                    # and log.  EventLoopNode's empty response guard will
                    # accept if all outputs are set, or handle the ghost
                    # stream case if outputs are still missing.
                    dump_path = _dump_failed_request(
                        model=self.model,
                        kwargs=kwargs,
                        error_type="empty_stream",
                        attempt=attempt,
                    )
                    logger.error(
                        f"[stream] {self.model} returned empty stream after "
                        f"{EMPTY_STREAM_MAX_RETRIES} retries "
                        f"(last_role={last_role}). Request dumped to: "
                        f"{dump_path}. Returning empty result."
                    )

                # Gemini sometimes outputs tool calls as text in
                # <tool_code>{"name": {...args}}</tool_code> blocks
                # instead of using the function-calling API.  Extract
                # these as real ToolCallEvents and strip them from the
                # text so the rest of the system treats them normally.
                if accumulated_text and "<tool_code>" in accumulated_text:
                    extracted, cleaned = _extract_text_tool_calls(accumulated_text)
                    if extracted:
                        tool_names = [tc.tool_name for tc in extracted]
                        logger.info(
                            "[stream] Model emitted %d tool call(s) as <tool_code> text "
                            "instead of structured function calls; converting to "
                            "synthetic ToolCallEvents: %s",
                            len(extracted),
                            tool_names,
                        )
                        accumulated_text = cleaned
                        # Emit a corrected TextDeltaEvent so the caller's
                        # accumulated_text is overwritten with the cleaned text.
                        yield TextDeltaEvent(content="", snapshot=cleaned)
                        # Insert synthetic ToolCallEvents before FinishEvent.
                        finish_idx = next(
                            (i for i, ev in enumerate(tail_events) if isinstance(ev, FinishEvent)),
                            len(tail_events),
                        )
                        for tc_ev in reversed(extracted):
                            tail_events.insert(finish_idx, tc_ev)
                        # Update TextEndEvent if present.
                        for _i, _ev in enumerate(tail_events):
                            if isinstance(_ev, TextEndEvent):
                                tail_events[_i] = TextEndEvent(full_text=cleaned)
                                break

                # Success (or empty after exhausted retries) — flush events.
                for event in tail_events:
                    yield event
                return

            except RateLimitError as e:
                if attempt < RATE_LIMIT_MAX_RETRIES:
                    wait = _compute_retry_delay(attempt, exception=e, jitter=True)
                    logger.warning(
                        f"[stream-retry] {self.model} rate limited (429): {e!s}. "
                        f"Retrying in {wait:.1f}s "
                        f"(attempt {attempt + 1}/{RATE_LIMIT_MAX_RETRIES})"
                    )
                    last_rate_limit_attempt = attempt
                    last_rate_limit_exc = e
                    await asyncio.sleep(wait)
                    continue
                err_type, upstream = _classify_llm_error(e)
                yield StreamErrorEvent(
                    error=str(e),
                    recoverable=False,
                    error_type=err_type,
                    upstream_status=upstream,
                )
                return

            except Exception as e:
                # Some providers return non-standard finish_reason values
                # (e.g., Kimi K2.x sends 'pause_turn') that LiteLLM's
                # internal stream_chunk_builder rejects via Pydantic
                # validation.  If we already accumulated content and built
                # tail_events before the error, the stream was successful —
                # yield what we have instead of discarding it.
                if (accumulated_text or tool_calls_acc) and tail_events:
                    # LiteLLM may wrap the original ValidationError in an
                    # APIError with a different message.  Check the full
                    # exception chain (str(e) + str(__cause__)).
                    _err_chain = f"{e} {e.__cause__}" if e.__cause__ else str(e)
                    _is_finish_reason_err = ("finish_reason" in _err_chain and "validation error" in _err_chain.lower()) or (
                        # Fallback: the APIError wrapper message for chunk-building failures
                        "building chunks" in str(e).lower() and (accumulated_text or tool_calls_acc)
                    )
                    if _is_finish_reason_err:
                        logger.warning(
                            "[stream] %s: LiteLLM finish_reason validation "
                            "error (non-standard provider value). "
                            "Content was streamed successfully — "
                            "using accumulated result. Error: %s",
                            self.model,
                            e,
                        )
                        for event in tail_events:
                            yield event
                        return

                if self._should_use_openrouter_tool_compat(e, tools):
                    _remember_openrouter_tool_compat_model(self.model)
                    async for event in self._stream_via_openrouter_tool_compat(
                        messages=messages,
                        system=system,
                        tools=tools or [],
                        max_tokens=max_tokens,
                    ):
                        yield event
                    return
                if _is_stream_transient_error(e) and attempt < STREAM_TRANSIENT_MAX_RETRIES:
                    wait = _compute_retry_delay(attempt, exception=e, jitter=True)
                    logger.warning(
                        f"[stream-retry] {self.model} transient error "
                        f"({type(e).__name__}): {e!s}. "
                        f"Retrying in {wait:.1f}s "
                        f"(attempt {attempt + 1}/{STREAM_TRANSIENT_MAX_RETRIES})"
                    )
                    await asyncio.sleep(wait)
                    continue
                dump_path = _dump_failed_request(
                    model=self.model,
                    kwargs=kwargs,
                    error_type=f"stream_exception_{type(e).__name__.lower()}",
                    attempt=attempt,
                )
                logger.error(
                    "[stream] %s request failed with %s: %s | request=%s | dump=%s",
                    self.model,
                    type(e).__name__,
                    e,
                    json.dumps(_summarize_request_for_log(kwargs), default=str),
                    dump_path,
                )
                recoverable = _is_stream_transient_error(e)
                err_type, upstream = _classify_llm_error(e)
                yield StreamErrorEvent(
                    error=str(e),
                    recoverable=recoverable,
                    error_type=err_type,
                    upstream_status=upstream,
                )
                return

    async def _collect_stream_to_response(
        self,
        stream: AsyncIterator[StreamEvent],
    ) -> LLMResponse:
        """Consume a stream() iterator and collect it into a single LLMResponse.

        Used by acomplete() to route through the unified streaming path so that
        all backends (including Codex) get proper tool call handling.
        """
        from framework.llm.stream_events import (
            FinishEvent,
            StreamErrorEvent,
            TextDeltaEvent,
            ToolCallEvent,
        )

        content = ""
        tool_calls: list[dict[str, Any]] = []
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        cache_creation_tokens = 0
        stop_reason = ""
        model = self.model

        async for event in stream:
            if isinstance(event, TextDeltaEvent):
                content = event.snapshot  # snapshot is the accumulated text
            elif isinstance(event, ToolCallEvent):
                tool_calls.append(
                    {
                        "id": event.tool_use_id,
                        "name": event.tool_name,
                        "input": event.tool_input,
                    }
                )
            elif isinstance(event, FinishEvent):
                input_tokens = event.input_tokens
                output_tokens = event.output_tokens
                cached_tokens = event.cached_tokens
                cache_creation_tokens = event.cache_creation_tokens
                stop_reason = event.stop_reason
                if event.model:
                    model = event.model
            elif isinstance(event, StreamErrorEvent):
                if not event.recoverable:
                    raise RuntimeError(f"Stream error: {event.error}")

        return LLMResponse(
            content=content,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens,
            stop_reason=stop_reason,
            raw_response={"tool_calls": tool_calls} if tool_calls else None,
        )
