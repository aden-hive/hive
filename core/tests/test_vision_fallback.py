"""Tests for vision-fallback crop-coordinate remapping and attachment filter.

When a text-only main model is captioned by the vision subagent, any
image that is a *crop* of the viewport (zoom action, element-clip or
full_page screenshot) makes the subagent emit crop-relative (fx, fy)
labels. ``remap_caption_for_crop`` rewrites those into viewport
fractions using the ``crop_box`` carried in the tool result.

The PDF upload path (chat handler) emits OpenAI ``file`` blocks rather
than rendered PNG image_url blocks so LiteLLM can auto-remap to each
provider's native PDF shape. The sidecar and the injection drain both
have attachment filters that must recognize both block shapes — these
are tested here.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from framework.agent_loop.internals.cursor_persistence import drain_injection_queue
from framework.agent_loop.internals.vision_fallback import (
    crop_box_from_tool_result,
    remap_caption_for_crop,
)


def _meta(**kw) -> str:
    return json.dumps({"ok": True, **kw})


class TestCropBoxExtraction:
    def test_returns_crop_box_when_present(self):
        assert crop_box_from_tool_result(_meta(crop_box=[0.6, 0.1, 0.8, 0.3])) == [0.6, 0.1, 0.8, 0.3]

    def test_full_viewport_box_is_treated_as_none(self):
        # A crop spanning the whole viewport needs no remap.
        assert crop_box_from_tool_result(_meta(crop_box=[0, 0, 1, 1])) is None

    def test_missing_crop_box(self):
        assert crop_box_from_tool_result(_meta(cssWidth=800)) is None

    def test_degraded_inputs_return_none(self):
        for bad in (None, "", "not json", json.dumps([1, 2, 3]), _meta(crop_box=[0, 0])):
            assert crop_box_from_tool_result(bad) is None

    def test_zero_area_box_rejected(self):
        assert crop_box_from_tool_result(_meta(crop_box=[0.5, 0.5, 0.5, 0.8])) is None


class TestCaptionRemap:
    def test_remaps_coordinates_into_viewport_space(self):
        # Image is a crop of viewport region [0.6, 0.1] .. [0.8, 0.3]
        # (0.2 wide, 0.2 tall). A label at the crop centre (0.5, 0.5)
        # is viewport (0.7, 0.2); crop corner (0.0, 1.0) is (0.6, 0.3).
        meta = _meta(action="zoom", crop_box=[0.6, 0.1, 0.8, 0.3])
        caption = 'The "Submit" button (0.5, 0.5) and a link (0.0, 1.0).'
        out = remap_caption_for_crop(caption, meta)
        assert "(0.7, 0.2)" in out
        assert "(0.6, 0.3)" in out

    def test_non_coordinate_parens_untouched(self):
        # A pixel resolution mentioned in prose isn't a 0..1 label.
        meta = _meta(crop_box=[0.6, 0.1, 0.8, 0.3])
        caption = "Captured at (1920, 1080) — button (0.5, 0.5)."
        out = remap_caption_for_crop(caption, meta)
        assert "(1920, 1080)" in out
        assert "(0.7, 0.2)" in out

    def test_full_viewport_caption_unchanged(self):
        caption = "Button (0.5, 0.5)."
        assert remap_caption_for_crop(caption, _meta(crop_box=[0, 0, 1, 1])) == caption

    def test_no_crop_box_caption_unchanged(self):
        caption = "Button (0.5, 0.5)."
        assert remap_caption_for_crop(caption, _meta(cssWidth=800)) == caption

    def test_degraded_tool_result_is_noop(self):
        caption = "Button (0.5, 0.5)."
        for bad in (None, "", "not json"):
            assert remap_caption_for_crop(caption, bad) == caption


# ---------------------------------------------------------------------------
# Attachment-filter recognition tests — these guarantee the sidecar and the
# injection drain both let through OpenAI-native ``file`` blocks (used for
# PDFs since LiteLLM auto-remaps them per provider).
# ---------------------------------------------------------------------------


def _png_image_block(payload: str = "AAAA") -> dict[str, Any]:
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{payload}"},
    }


def _pdf_file_block(payload: str = "JVBE") -> dict[str, Any]:
    return {
        "type": "file",
        "file": {
            "file_data": f"data:application/pdf;base64,{payload}",
            "filename": "doc.pdf",
        },
    }


def _hive_replay_block() -> dict[str, Any]:
    """A block that should be filtered — non-data URI (session-replay style)."""
    return {"type": "image_url", "image_url": {"url": "hive://attachments/old.png"}}


class _FakeLLM:
    """Stands in for ctx.llm; ``model`` attribute is what supports_image_tool_results
    inspects via the model catalog."""

    def __init__(self, model: str) -> None:
        self.model = model


class _FakeCtx:
    def __init__(self, model: str = "claude-sonnet-4-5-20250929") -> None:
        self.llm = _FakeLLM(model)


class _FakeConversation:
    """Captures add_user_message calls so the test can inspect what survived
    the drain filter."""

    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []

    async def add_user_message(
        self,
        content: str,
        *,
        is_client_input: bool = False,
        image_content: list[dict[str, Any]] | None = None,
    ):
        self.added.append({"content": content, "image_content": image_content})


class TestDrainInjectionFilter:
    """drain_injection_queue must keep both image_url and `file` blocks
    while dropping non-data-URI references (hive:// etc.)."""

    @pytest.mark.asyncio
    async def test_image_url_with_data_uri_kept(self):
        queue: asyncio.Queue = asyncio.Queue()
        await queue.put(("hello", True, [_png_image_block()], None))
        conversation = _FakeConversation()
        count = await drain_injection_queue(queue=queue, conversation=conversation, ctx=_FakeCtx())
        assert count == 1
        assert conversation.added[0]["image_content"] is not None
        assert len(conversation.added[0]["image_content"]) == 1

    @pytest.mark.asyncio
    async def test_file_block_with_pdf_data_uri_kept(self):
        """The new branch: a `file` block with a PDF data URI must survive
        the drain filter so LiteLLM can auto-remap it for the active model."""
        queue: asyncio.Queue = asyncio.Queue()
        await queue.put(("summarize", True, [_pdf_file_block()], None))
        conversation = _FakeConversation()
        count = await drain_injection_queue(queue=queue, conversation=conversation, ctx=_FakeCtx())
        assert count == 1
        kept = conversation.added[0]["image_content"]
        assert kept is not None and len(kept) == 1
        assert kept[0]["type"] == "file"
        assert kept[0]["file"]["file_data"].startswith("data:application/pdf;base64,")

    @pytest.mark.asyncio
    async def test_non_data_uri_dropped(self):
        queue: asyncio.Queue = asyncio.Queue()
        await queue.put(("hello", True, [_hive_replay_block()], None))
        conversation = _FakeConversation()
        await drain_injection_queue(queue=queue, conversation=conversation, ctx=_FakeCtx())
        # Block dropped → image_content normalized to None.
        assert conversation.added[0]["image_content"] is None

    @pytest.mark.asyncio
    async def test_mixed_blocks_only_data_uris_kept(self):
        queue: asyncio.Queue = asyncio.Queue()
        blocks = [_png_image_block(), _hive_replay_block(), _pdf_file_block()]
        await queue.put(("multi", True, blocks, None))
        conversation = _FakeConversation()
        await drain_injection_queue(queue=queue, conversation=conversation, ctx=_FakeCtx())
        kept = conversation.added[0]["image_content"]
        assert kept is not None and len(kept) == 2
        kinds = {b["type"] for b in kept}
        assert kinds == {"image_url", "file"}
