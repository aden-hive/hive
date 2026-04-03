"""Tests verifying that all spillover writes use atomic_write.

Each test monkeypatches atomic_write in the target module to record which
paths were written through the crash-safe utility.  The actual atomic_write
is still called so file content is correct — we're only asserting that the
code *routes through* the utility rather than calling Path.write_text().

Covers all 7 locations fixed in issue #6805.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from framework.utils.io import atomic_write

# ---------------------------------------------------------------------------
# Helper: recording wrapper around atomic_write
# ---------------------------------------------------------------------------


def _make_recording_atomic_write(record: list[Path]):
    """Return an atomic_write replacement that records paths and delegates."""

    @contextmanager
    def recording_atomic_write(*args, **kwargs):
        path = Path(args[0] if args else kwargs["path"])
        record.append(path)
        with atomic_write(*args, **kwargs) as f:
            yield f

    return recording_atomic_write


# ---------------------------------------------------------------------------
# 1. tool_result_handler — truncate_tool_result (spillover write)
# ---------------------------------------------------------------------------


class TestToolResultSpillover:
    """truncate_tool_result must write results through atomic_write."""

    def test_tool_result_spillover_uses_atomic_write(self, tmp_path, monkeypatch):
        from framework.graph.event_loop.tool_result_handler import truncate_tool_result
        from framework.llm.provider import ToolResult

        record: list[Path] = []
        monkeypatch.setattr(
            "framework.graph.event_loop.tool_result_handler.atomic_write",
            _make_recording_atomic_write(record),
        )

        spillover_dir = str(tmp_path / "spill")
        result = ToolResult(
            tool_use_id="tc_1",
            content="short result from web_search",
            is_error=False,
        )
        counter = 1

        truncate_tool_result(
            result,
            "web_search",
            max_tool_result_chars=50_000,
            spillover_dir=spillover_dir,
            next_spill_filename_fn=lambda name: f"{name}_{counter}.txt",
        )

        assert len(record) == 1, f"Expected 1 atomic_write call, got {len(record)}"
        assert record[0].name == "web_search_1.txt"
        # Verify the file was actually written
        assert record[0].exists()
        assert record[0].read_text(encoding="utf-8") == "short result from web_search"

    def test_large_tool_result_spillover_uses_atomic_write(self, tmp_path, monkeypatch):
        """Large results that get previewed should still be written atomically."""
        from framework.graph.event_loop.tool_result_handler import truncate_tool_result
        from framework.llm.provider import ToolResult

        record: list[Path] = []
        monkeypatch.setattr(
            "framework.graph.event_loop.tool_result_handler.atomic_write",
            _make_recording_atomic_write(record),
        )

        spillover_dir = str(tmp_path / "spill")
        # Create a result larger than the limit
        large_content = "x" * 50_000
        result = ToolResult(
            tool_use_id="tc_2",
            content=large_content,
            is_error=False,
        )

        truncated = truncate_tool_result(
            result,
            "big_tool",
            max_tool_result_chars=1_000,
            spillover_dir=spillover_dir,
            next_spill_filename_fn=lambda name: f"{name}_1.txt",
        )

        assert len(record) == 1
        assert record[0].name == "big_tool_1.txt"
        # The returned result should be a preview, not the full content
        assert len(truncated.content) < len(large_content)
        # But the file should contain the full content
        assert record[0].read_text(encoding="utf-8") == large_content

    def test_json_tool_result_pretty_printed(self, tmp_path, monkeypatch):
        """JSON results should be pretty-printed in the spillover file."""
        from framework.graph.event_loop.tool_result_handler import truncate_tool_result
        from framework.llm.provider import ToolResult

        record: list[Path] = []
        monkeypatch.setattr(
            "framework.graph.event_loop.tool_result_handler.atomic_write",
            _make_recording_atomic_write(record),
        )

        spillover_dir = str(tmp_path / "spill")
        json_content = json.dumps({"key": "value", "items": [1, 2, 3]})
        result = ToolResult(
            tool_use_id="tc_3",
            content=json_content,
            is_error=False,
        )

        truncate_tool_result(
            result,
            "api_call",
            max_tool_result_chars=50_000,
            spillover_dir=spillover_dir,
            next_spill_filename_fn=lambda name: f"{name}_1.txt",
        )

        assert len(record) == 1
        written = record[0].read_text(encoding="utf-8")
        # Should be pretty-printed (indented)
        assert "  " in written
        assert json.loads(written) == {"key": "value", "items": [1, 2, 3]}


# ---------------------------------------------------------------------------
# 2. tool_result_handler — record_learning (adapt.md)
# ---------------------------------------------------------------------------


class TestRecordLearning:
    """record_learning must write adapt.md through atomic_write."""

    def test_record_learning_uses_atomic_write(self, tmp_path, monkeypatch):
        from framework.graph.event_loop.tool_result_handler import record_learning

        record: list[Path] = []
        monkeypatch.setattr(
            "framework.graph.event_loop.tool_result_handler.atomic_write",
            _make_recording_atomic_write(record),
        )

        spillover_dir = str(tmp_path / "data")
        record_learning("summary", "The agent completed the task.", spillover_dir)

        assert len(record) == 1
        assert record[0].name == "adapt.md"
        content = record[0].read_text(encoding="utf-8")
        assert "summary: The agent completed the task." in content

    def test_record_learning_updates_existing(self, tmp_path, monkeypatch):
        """Calling record_learning twice for the same key should update, not duplicate."""
        from framework.graph.event_loop.tool_result_handler import record_learning

        record: list[Path] = []
        monkeypatch.setattr(
            "framework.graph.event_loop.tool_result_handler.atomic_write",
            _make_recording_atomic_write(record),
        )

        spillover_dir = str(tmp_path / "data")
        record_learning("status", "in_progress", spillover_dir)
        record_learning("status", "done", spillover_dir)

        # Should have been called twice (once per record_learning call)
        assert len(record) == 2
        content = record[0].parent.joinpath("adapt.md").read_text(encoding="utf-8")
        # Should only have one "status:" entry (updated, not duplicated)
        assert content.count("- status:") == 1
        assert "done" in content


# ---------------------------------------------------------------------------
# 3. types.py — OutputAccumulator._auto_spill
# ---------------------------------------------------------------------------


class TestEventLoopNodeSeedSpillover:
    """EventLoopNode must write the adapt.md seed atomically."""

    @pytest.mark.asyncio
    async def test_event_loop_node_seed_uses_atomic_write(self, tmp_path, monkeypatch):
        from framework.graph.event_loop.types import LoopConfig
        from framework.graph.event_loop_node import EventLoopNode
        from framework.graph.node import NodeContext, NodeSpec

        record: list[Path] = []
        monkeypatch.setattr(
            "framework.utils.io.atomic_write",
            _make_recording_atomic_write(record),
        )

        spillover_dir = str(tmp_path / "spill")
        node = EventLoopNode(config=LoopConfig(spillover_dir=spillover_dir))

        from unittest.mock import MagicMock
        
        # Create minimal NodeContext to reach the seed-writing logic
        ctx = MagicMock()
        ctx.node_id = "test"
        ctx.node_spec.name = "Test"
        ctx.node_spec.node_type = "event_loop"
        ctx.node_spec.system_prompt = ""
        ctx.node_spec.output_keys = []
        ctx.is_restored_conversation = False
        ctx.identity_prompt = ""
        ctx.narrative = ""
        ctx.accounts_prompt = ""
        ctx.skills_catalog_prompt = ""
        ctx.protocols_prompt = ""
        ctx.is_subagent_mode = False
        ctx.inherited_conversation = None
        
        # execution path accesses ctx.runtime.logger.info
        ctx.runtime = MagicMock()

        # Monkeypatch NodeConversation to abort execute() immediately after the seed is written
        def mock_node_conversation(*args, **kwargs):
            raise RuntimeError("Abort loop")
        
        monkeypatch.setattr("framework.graph.event_loop_node.NodeConversation", mock_node_conversation)

        try:
            # Depending on how the method handles initialization failures, this may bubble up
            await node.execute(ctx)
        except RuntimeError:
            pass # We successfully aborted the loop after adapt.md was written

        assert len(record) == 1
        assert record[0].name == "adapt.md"
        assert "Session Working Memory" in record[0].read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 4. types.py — OutputAccumulator._auto_spill
# ---------------------------------------------------------------------------


class TestOutputAccumulatorSpill:
    """OutputAccumulator._auto_spill must write through atomic_write."""

    def test_auto_spill_uses_atomic_write(self, tmp_path, monkeypatch):
        from framework.graph.event_loop.types import OutputAccumulator

        record: list[Path] = []
        monkeypatch.setattr(
            "framework.graph.event_loop.types.atomic_write",
            _make_recording_atomic_write(record),
        )

        acc = OutputAccumulator(
            spillover_dir=str(tmp_path / "spill"),
            max_value_chars=10,  # Trigger spill for anything > 10 chars
        )

        # Value longer than max_value_chars triggers spill
        result = acc._auto_spill("report", "This is a long report that exceeds the limit")

        assert len(record) == 1
        assert record[0].name == "output_report.txt"
        assert "[Saved to" in result  # Should return a reference string

    def test_auto_spill_json_uses_atomic_write(self, tmp_path, monkeypatch):
        """Dict/list values should be pretty-printed JSON in spillover file."""
        from framework.graph.event_loop.types import OutputAccumulator

        record: list[Path] = []
        monkeypatch.setattr(
            "framework.graph.event_loop.types.atomic_write",
            _make_recording_atomic_write(record),
        )

        acc = OutputAccumulator(
            spillover_dir=str(tmp_path / "spill"),
            max_value_chars=10,
        )

        data = {"findings": ["item1", "item2", "item3"]}
        acc._auto_spill("data", data)

        assert len(record) == 1
        assert record[0].name == "output_data.json"
        written = record[0].read_text(encoding="utf-8")
        assert json.loads(written) == data

    def test_small_value_skips_spill(self, tmp_path, monkeypatch):
        """Values under the threshold should NOT be spilled."""
        from framework.graph.event_loop.types import OutputAccumulator

        record: list[Path] = []
        monkeypatch.setattr(
            "framework.graph.event_loop.types.atomic_write",
            _make_recording_atomic_write(record),
        )

        acc = OutputAccumulator(
            spillover_dir=str(tmp_path / "spill"),
            max_value_chars=1000,
        )

        result = acc._auto_spill("small", "ok")

        assert len(record) == 0  # No spill for small values
        assert result == "ok"  # Value returned as-is


# ---------------------------------------------------------------------------
# 4. conversation.py — compact_preserving_structure
# ---------------------------------------------------------------------------


class TestConversationCompactSpillover:
    """compact_preserving_structure must write conversation files atomically."""

    @pytest.mark.asyncio
    async def test_compact_preserving_structure_uses_atomic_write(self, tmp_path, monkeypatch):
        from framework.graph.conversation import NodeConversation

        record: list[Path] = []
        monkeypatch.setattr(
            "framework.utils.io.atomic_write",
            _make_recording_atomic_write(record),
        )

        conv = NodeConversation(
            system_prompt="Test",
            max_context_tokens=100,
            compaction_threshold=0.1,
        )

        # Add enough messages to trigger compaction
        for i in range(10):
            await conv.add_user_message(f"User message {i} with enough content to matter")
            await conv.add_assistant_message(f"Assistant response {i}")

        spillover_dir = str(tmp_path / "spill")
        await conv.compact_preserving_structure(
            spillover_dir=spillover_dir,
            keep_recent=2,
        )

        assert len(record) >= 1, "Expected at least 1 atomic_write for conversation file"
        assert any("conversation_" in p.name for p in record)


# ---------------------------------------------------------------------------
# 5. prompt_composer.py — build_transition_marker
# ---------------------------------------------------------------------------


class TestPromptComposerSpillover:
    """build_transition_marker must write large values through atomic_write."""

    def test_transition_marker_large_value_uses_atomic_write(self, tmp_path, monkeypatch):
        from framework.graph.node import NodeSpec, SharedMemory
        from framework.graph.prompt_composer import build_transition_marker

        record: list[Path] = []
        monkeypatch.setattr(
            "framework.utils.io.atomic_write",
            _make_recording_atomic_write(record),
        )

        prev_node = NodeSpec(
            id="node_a",
            name="Research",
            description="Gather data",
        )
        next_node = NodeSpec(
            id="node_b",
            name="Synthesis",
            description="Synthesize findings",
        )
        memory = SharedMemory()
        # Write a large value that will trigger spillover (> 300 chars)
        memory.write("big_output", "x" * 500)

        data_dir = tmp_path / "data"

        build_transition_marker(
            previous_node=prev_node,
            next_node=next_node,
            memory=memory,
            cumulative_tool_names=["web_search"],
            data_dir=data_dir,
        )

        assert len(record) == 1
        assert record[0].name == "output_big_output.txt"
        assert record[0].read_text(encoding="utf-8") == "x" * 500


# ---------------------------------------------------------------------------
# 6. compaction.py — write_compaction_debug_log
# ---------------------------------------------------------------------------


class TestCompactionDebugLog:
    """write_compaction_debug_log must write through atomic_write."""

    def test_debug_log_uses_atomic_write(self, tmp_path, monkeypatch):
        from framework.graph.event_loop.compaction import write_compaction_debug_log

        record: list[Path] = []
        monkeypatch.setattr(
            "framework.utils.io.atomic_write",
            _make_recording_atomic_write(record),
        )

        # Mock a minimal NodeContext
        ctx = MagicMock()
        ctx.node_id = "test_node"
        ctx.node_spec.name = "TestNode"
        ctx.stream_id = "queen"

        # Redirect log_dir to tmp_path
        monkeypatch.setattr(
            "framework.graph.event_loop.compaction.Path.home",
            lambda: tmp_path,
        )

        write_compaction_debug_log(
            ctx,
            before_pct=95,
            after_pct=42,
            level="llm",
            inventory=None,
        )

        assert len(record) == 1
        assert ".md" in record[0].name
        content = record[0].read_text(encoding="utf-8")
        assert "Compaction Debug" in content
        assert "95%" in content


# ---------------------------------------------------------------------------
# 7. Regression: error results must NOT trigger spillover
# ---------------------------------------------------------------------------


class TestErrorResultsNotSpilled:
    """Error results should pass through unchanged — no atomic_write call."""

    def test_error_result_not_spilled(self, tmp_path, monkeypatch):
        from framework.graph.event_loop.tool_result_handler import truncate_tool_result
        from framework.llm.provider import ToolResult

        record: list[Path] = []
        monkeypatch.setattr(
            "framework.graph.event_loop.tool_result_handler.atomic_write",
            _make_recording_atomic_write(record),
        )

        result = ToolResult(
            tool_use_id="tc_err",
            content="Error: something went wrong",
            is_error=True,
        )

        returned = truncate_tool_result(
            result,
            "failing_tool",
            max_tool_result_chars=50_000,
            spillover_dir=str(tmp_path / "spill"),
            next_spill_filename_fn=lambda name: f"{name}_1.txt",
        )

        assert len(record) == 0  # Error results pass through, no file written
        assert returned.content == "Error: something went wrong"
        assert returned.is_error is True
