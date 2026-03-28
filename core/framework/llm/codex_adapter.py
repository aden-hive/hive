"""Codex adapter for Hive's LiteLLM provider.

Codex CLI is tool-first and event-structured: tool invocations and tool results
are emitted as explicit response items, not as plain-text workflow narration.
This adapter keeps the ChatGPT Codex backend aligned with Hive's normal
provider contract by normalizing Codex request shaping and response recovery at
the provider boundary.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from framework.llm.codex_backend import (
    build_codex_extra_headers,
    is_codex_api_base,
    merge_codex_allowed_openai_params,
    normalize_codex_api_base,
)
from framework.llm.provider import Tool

if TYPE_CHECKING:
    from collections.abc import Callable

    from framework.llm.litellm import LiteLLMProvider
    from framework.llm.stream_events import StreamEvent

logger = logging.getLogger(__name__)

_CODEX_CRITICAL_TOOL_NAMES = frozenset(
    {
        "ask_user",
        "ask_user_multiple",
        "set_output",
        "escalate",
        "save_agent_draft",
        "confirm_and_build",
        "initialize_and_build_agent",
    }
)
_CODEX_SYSTEM_CHUNK_CHARS = 3500
_CODEX_SYSTEM_PREAMBLE = """# Codex Execution Contract
Follow the system sections below in order.
- Obey every CRITICAL, MUST, NEVER, and ONLY instruction exactly.
- When tools are available, emit structured tool calls instead of replying with plain-text promises.
- Do not skip required workflow boundaries or approval gates.
"""


class CodexResponsesAdapter:
    """Normalize the ChatGPT Codex backend to Hive's standard provider semantics."""

    def __init__(self, provider: LiteLLMProvider):
        self._provider = provider

    @property
    def enabled(self) -> bool:
        """Return True when the provider targets the ChatGPT Codex backend."""
        return is_codex_api_base(self._provider.api_base)

    def chunk_system_prompt(self, system: str) -> list[str]:
        """Break large system prompts into smaller Codex-friendly chunks."""
        normalized = system.replace("\r\n", "\n").strip()
        if not normalized:
            return []

        sections: list[str] = []
        current: list[str] = []
        for line in normalized.splitlines():
            if line.startswith("#") and current:
                sections.append("\n".join(current).strip())
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append("\n".join(current).strip())

        chunks: list[str] = []
        for section in sections:
            if len(section) <= _CODEX_SYSTEM_CHUNK_CHARS:
                chunks.append(section)
                continue

            paragraphs = [
                paragraph.strip() for paragraph in section.split("\n\n") if paragraph.strip()
            ]
            current_chunk = ""
            for paragraph in paragraphs:
                candidate = paragraph if not current_chunk else f"{current_chunk}\n\n{paragraph}"
                if current_chunk and len(candidate) > _CODEX_SYSTEM_CHUNK_CHARS:
                    chunks.append(current_chunk)
                    current_chunk = paragraph
                else:
                    current_chunk = candidate
            if current_chunk:
                chunks.append(current_chunk)

        return chunks or [normalized]

    def build_system_messages(
        self,
        system: str,
        *,
        json_mode: bool,
    ) -> list[dict[str, Any]]:
        """Build Codex system messages in the tool-first format Codex CLI expects."""
        system_messages: list[dict[str, Any]] = []
        if system:
            chunks = self.chunk_system_prompt(system)
            if len(chunks) > 1 or len(chunks[0]) > _CODEX_SYSTEM_CHUNK_CHARS:
                system_messages.append({"role": "system", "content": _CODEX_SYSTEM_PREAMBLE})
            for chunk in chunks:
                system_messages.append({"role": "system", "content": chunk})
        else:
            system_messages.append({"role": "system", "content": "You are a helpful assistant."})

        if json_mode:
            system_messages.append(
                {"role": "system", "content": "Please respond with a valid JSON object."}
            )
        return system_messages

    def derive_tool_choice(
        self,
        messages: list[dict[str, Any]],
        tools: list[Tool] | None,
    ) -> str | dict[str, Any] | None:
        """Force structured tool use when Codex sees critical framework tools."""
        if not tools:
            return None

        tool_names = {tool.name for tool in tools}
        if not (tool_names & _CODEX_CRITICAL_TOOL_NAMES):
            return None

        last_role = next(
            (m.get("role") for m in reversed(messages) if m.get("role") != "system"),
            None,
        )
        if last_role == "assistant":
            return None
        return "required"

    def harden_request_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Strip unsupported params and inject the Codex backend headers."""
        cleaned = dict(kwargs)
        cleaned["api_base"] = normalize_codex_api_base(
            cleaned.get("api_base") or self._provider.api_base
        )
        cleaned["store"] = False
        cleaned["allowed_openai_params"] = merge_codex_allowed_openai_params(
            cleaned.get("allowed_openai_params")
        )
        cleaned.pop("max_tokens", None)
        cleaned.pop("stream_options", None)

        extra_headers = dict(cleaned.get("extra_headers") or {})
        if "ChatGPT-Account-Id" not in extra_headers:
            try:
                from framework.runner.runner import get_codex_account_id

                account_id = get_codex_account_id()
                if account_id:
                    extra_headers["ChatGPT-Account-Id"] = account_id
            except Exception:
                logger.debug("Could not populate ChatGPT-Account-Id", exc_info=True)

        cleaned["extra_headers"] = build_codex_extra_headers(
            self._provider.api_key,
            account_id=extra_headers.get("ChatGPT-Account-Id"),
            extra_headers=extra_headers,
        )
        return cleaned

    async def recover_empty_stream(
        self,
        kwargs: dict[str, Any],
        *,
        last_role: str | None,
        acompletion: Callable[..., Any],
    ) -> list[StreamEvent] | None:
        """Try a non-stream completion when Codex returns an empty stream."""
        fallback_kwargs = dict(kwargs)
        fallback_kwargs.pop("stream", None)
        fallback_kwargs.pop("stream_options", None)
        fallback_kwargs = self._provider._sanitize_request_kwargs(fallback_kwargs, stream=False)

        try:
            response = await acompletion(**fallback_kwargs)
        except Exception as exc:
            logger.debug(
                "[stream-recover] %s non-stream fallback after empty %s stream failed: %s",
                self._provider.model,
                last_role,
                exc,
            )
            return None

        events = self._provider._build_stream_events_from_nonstream_response(response)
        if events:
            logger.info(
                "[stream-recover] %s recovered empty %s stream via non-stream completion",
                self._provider.model,
                last_role,
            )
            return events
        return None

    def merge_tool_call_chunk(
        self,
        tool_calls_acc: dict[int, dict[str, str]],
        tc: Any,
        last_tool_idx: int,
    ) -> int:
        """Merge a streamed tool-call chunk, compensating for broken bridge indexes."""
        idx = tc.index if hasattr(tc, "index") and tc.index is not None else 0
        tc_id = getattr(tc, "id", None) or ""
        func = getattr(tc, "function", None)
        func_name = getattr(func, "name", "") if func is not None else ""
        func_args = getattr(func, "arguments", "") if func is not None else ""

        if tc_id:
            existing_idx = next(
                (key for key, value in tool_calls_acc.items() if value["id"] == tc_id),
                None,
            )
            if existing_idx is not None:
                idx = existing_idx
            elif idx in tool_calls_acc and tool_calls_acc[idx]["id"] not in ("", tc_id):
                idx = max(tool_calls_acc.keys(), default=-1) + 1
            last_tool_idx = idx
        elif func_name:
            if (
                last_tool_idx in tool_calls_acc
                and tool_calls_acc[last_tool_idx]["name"]
                and tool_calls_acc[last_tool_idx]["name"] != func_name
                and tool_calls_acc[last_tool_idx]["arguments"]
            ):
                idx = max(tool_calls_acc.keys(), default=-1) + 1
                last_tool_idx = idx
            else:
                idx = last_tool_idx if tool_calls_acc else idx
        else:
            idx = last_tool_idx if tool_calls_acc else idx

        if idx not in tool_calls_acc:
            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
        if tc_id:
            tool_calls_acc[idx]["id"] = tc_id
        if func_name:
            tool_calls_acc[idx]["name"] = func_name
        if func_args:
            tool_calls_acc[idx]["arguments"] += func_args
        return idx
