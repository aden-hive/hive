"""Tests for the framework-side attach_file chip publisher.

The tool (`aden_tools.tools.attach_file_tool.attach_file_tool.attach_file`)
emits a JSON summary with `attached` entries that include the resolved
absolute path but NOT `hive_attachment_url`. The framework's
`_publish_attach_file_result` is the single owner of chip publishing:
it copies the source into `{session}/data/attachments/<basename>` and
injects the `hive_attachment_url` into each entry.

If publishing can't happen (no conversation store, no `_base`, JSON
parse failure, no entries with a real source path), the helper rewrites
the result into `is_error=True` so the agent surfaces the failure to
the user instead of falsely claiming the file was delivered.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from framework.agent_loop.agent_loop import _publish_attach_file_result
from framework.llm.provider import ToolResult


def _summary(content: str) -> dict:
    """Decode the leading JSON envelope from a ToolResult.content."""
    leading = content.lstrip()
    payload, _ = json.JSONDecoder().raw_decode(leading)
    return payload


def _make_result(payload: dict, trailing: str = "", tool_use_id: str = "tu_test") -> ToolResult:
    return ToolResult(
        tool_use_id=tool_use_id,
        content=json.dumps(payload) + trailing,
        is_error=False,
    )


def _make_store(session_dir: Path) -> SimpleNamespace:
    """Stand-in for ConversationStore with a `_base` of {session}/conversations/."""
    conv_dir = session_dir / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(_base=conv_dir)


class TestPublishAttachFileResult:
    def test_publishes_chip_and_injects_url(self, tmp_path: Path):
        source = tmp_path / "report.pdf"
        source.write_bytes(b"%PDF-1.4\nstub\n%%EOF")
        store = _make_store(tmp_path / "session")

        payload = {
            "attached": [
                {
                    "path": str(source),
                    "resolved": str(source),
                    "kind": "pdf",
                    "mime": "application/pdf",
                    "bytes": source.stat().st_size,
                    "filename": "report.pdf",
                }
            ],
            "errors": [],
        }
        result = _make_result(payload)

        out = _publish_attach_file_result(result, store)
        assert out.is_error is False
        out_payload = _summary(out.content)
        assert out_payload["attached"][0]["hive_attachment_url"] == "hive-attachment://data/attachments/report.pdf"
        copied = tmp_path / "session" / "data" / "attachments" / "report.pdf"
        assert copied.is_file()
        assert copied.read_bytes() == source.read_bytes()

    def test_preserves_trailing_inline_text(self, tmp_path: Path):
        """Text-shaped attachments inline a body after the JSON envelope.
        The helper must keep the trailing text verbatim so the LLM still
        reads the file content on the next turn."""
        source = tmp_path / "note.md"
        source.write_text("hi there", encoding="utf-8")
        store = _make_store(tmp_path / "session")

        payload = {
            "attached": [
                {
                    "path": str(source),
                    "resolved": str(source),
                    "kind": "text",
                    "mime": "text/markdown",
                    "bytes": source.stat().st_size,
                    "filename": "note.md",
                }
            ],
            "errors": [],
        }
        trailing = "[attached note.md (text/markdown)]\n\nhi there"
        result = _make_result(payload, trailing=trailing)

        out = _publish_attach_file_result(result, store)
        # JSON re-emitted plus the same trailing text.
        out_payload = _summary(out.content)
        assert out_payload["attached"][0]["hive_attachment_url"]
        # Trailing body still tacked onto the end after the new JSON.
        re_serialized = json.dumps(out_payload)
        assert out.content == re_serialized + trailing

    def test_none_conversation_store_returns_error_result(self, tmp_path: Path):
        """If there's no conversation store the helper can't publish.
        Old behavior: silently no-op. New behavior: rewrite result to
        is_error=True with a diagnostic so the agent doesn't claim
        success and confuse the user."""
        source = tmp_path / "report.pdf"
        source.write_bytes(b"%PDF-1.4\n%%EOF")
        payload = {
            "attached": [{"path": str(source), "resolved": str(source), "filename": "report.pdf"}],
            "errors": [],
        }
        out = _publish_attach_file_result(_make_result(payload), conversation_store=None)
        assert out.is_error is True
        out_payload = _summary(out.content)
        assert out_payload["attached"] == []
        assert "no conversation store" in out_payload["errors"][0]["error"]

    def test_store_without_base_returns_error_result(self, tmp_path: Path):
        """A store without ``_base`` (test doubles, weird subclasses)
        can't have its session dir derived. Same loud-failure path as
        a None store."""
        store = SimpleNamespace()  # no _base attribute
        source = tmp_path / "report.pdf"
        source.write_bytes(b"%PDF-1.4\n%%EOF")
        payload = {
            "attached": [{"path": str(source), "resolved": str(source), "filename": "report.pdf"}],
            "errors": [],
        }
        out = _publish_attach_file_result(_make_result(payload), store)
        assert out.is_error is True
        out_payload = _summary(out.content)
        assert "no filesystem base" in out_payload["errors"][0]["error"]

    def test_unparseable_content_returns_error_result(self, tmp_path: Path):
        store = _make_store(tmp_path / "session")
        result = ToolResult(tool_use_id="tu", content="not json at all", is_error=False)
        out = _publish_attach_file_result(result, store)
        assert out.is_error is True
        out_payload = _summary(out.content)
        assert "not a JSON summary" in out_payload["errors"][0]["error"]

    def test_empty_attached_passes_through_unchanged(self, tmp_path: Path):
        """When the tool's own summary has no attached entries (all
        paths errored), nothing to publish — return result untouched
        so the agent sees the tool's own error list."""
        store = _make_store(tmp_path / "session")
        payload = {"attached": [], "errors": [{"path": "/nope.pdf", "error": "file not found"}]}
        result = _make_result(payload)
        out = _publish_attach_file_result(result, store)
        assert out is result  # passthrough

    def test_source_vanished_returns_error_result(self, tmp_path: Path):
        """If the source path disappears between tool call and publish
        (race / cleanup), we can't publish any entry — surface failure."""
        store = _make_store(tmp_path / "session")
        ghost = tmp_path / "ghost.pdf"  # never created
        payload = {
            "attached": [{"path": str(ghost), "resolved": str(ghost), "filename": "ghost.pdf"}],
            "errors": [],
        }
        out = _publish_attach_file_result(_make_result(payload), store)
        assert out.is_error is True
        out_payload = _summary(out.content)
        assert "source vanished" in out_payload["errors"][0]["error"]

    def test_multiple_files_all_published(self, tmp_path: Path):
        store = _make_store(tmp_path / "session")
        a = tmp_path / "a.pdf"
        a.write_bytes(b"%PDF-1.4\nA\n%%EOF")
        b = tmp_path / "b.md"
        b.write_text("# B", encoding="utf-8")
        payload = {
            "attached": [
                {"path": str(a), "resolved": str(a), "filename": "a.pdf"},
                {"path": str(b), "resolved": str(b), "filename": "b.md"},
            ],
            "errors": [],
        }
        out = _publish_attach_file_result(_make_result(payload), store)
        assert out.is_error is False
        out_payload = _summary(out.content)
        urls = [e["hive_attachment_url"] for e in out_payload["attached"]]
        assert urls == [
            "hive-attachment://data/attachments/a.pdf",
            "hive-attachment://data/attachments/b.md",
        ]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
