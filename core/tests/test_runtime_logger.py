"""Tests for RuntimeLogger and RuntimeLogStore.

Tests incremental JSONL writes (L2/L3), crash resilience, and L1
summary aggregation at end_run().
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from framework.observability import clear_trace_context, set_trace_context
from framework.runtime.runtime_log_schemas import (
    NodeDetail,
    NodeStepLog,
    RunSummaryLog,
    ToolCallLog,
)
from framework.runtime.runtime_log_store import RuntimeLogStore
from framework.runtime.runtime_logger import RuntimeLogger

# ---------------------------------------------------------------------------
# RuntimeLogStore tests
# ---------------------------------------------------------------------------


class TestRuntimeLogStore:
    @pytest.mark.asyncio
    async def test_ensure_run_dir_creates_directory(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")
        store.ensure_run_dir("test_run_1")
        assert (tmp_path / "logs" / "runs" / "test_run_1").is_dir()

    @pytest.mark.asyncio
    async def test_append_and_load_details(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")
        store.ensure_run_dir("test_run_2")

        detail1 = NodeDetail(
            node_id="node-1",
            node_name="Search Node",
            node_type="event_loop",
            success=True,
            total_steps=2,
            exit_status="success",
            accept_count=1,
            retry_count=1,
        )
        detail2 = NodeDetail(
            node_id="node-2",
            node_name="Process Node",
            node_type="event_loop",
            success=True,
            total_steps=1,
        )

        store.append_node_detail("test_run_2", detail1)
        store.append_node_detail("test_run_2", detail2)

        loaded = await store.load_details("test_run_2")
        assert loaded is not None
        assert len(loaded.nodes) == 2
        assert loaded.nodes[0].node_id == "node-1"
        assert loaded.nodes[0].exit_status == "success"
        assert loaded.nodes[1].node_type == "event_loop"

    @pytest.mark.asyncio
    async def test_append_and_load_tool_logs(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")
        store.ensure_run_dir("test_run_3")

        step = NodeStepLog(
            node_id="node-1",
            node_type="event_loop",
            step_index=0,
            llm_text="I will search for the data.",
            tool_calls=[
                ToolCallLog(
                    tool_use_id="tc_1",
                    tool_name="web_search",
                    tool_input={"query": "test"},
                    result="Found 3 results",
                    is_error=False,
                )
            ],
            input_tokens=100,
            output_tokens=50,
            latency_ms=1200,
            verdict="CONTINUE",
        )

        store.append_step("test_run_3", step)

        loaded = await store.load_tool_logs("test_run_3")
        assert loaded is not None
        assert len(loaded.steps) == 1
        assert loaded.steps[0].tool_calls[0].tool_name == "web_search"
        assert loaded.steps[0].input_tokens == 100
        assert loaded.steps[0].node_id == "node-1"

    @pytest.mark.asyncio
    async def test_save_and_load_summary(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")
        summary = RunSummaryLog(
            run_id="test_run_1",
            agent_id="agent-a",
            goal_id="goal-1",
            status="success",
            total_nodes_executed=3,
            node_path=["node-1", "node-2", "node-3"],
            started_at="2025-01-01T00:00:00",
            duration_ms=5000,
            execution_quality="clean",
        )

        await store.save_summary("test_run_1", summary)

        loaded = await store.load_summary("test_run_1")
        assert loaded is not None
        assert loaded.run_id == "test_run_1"
        assert loaded.status == "success"
        assert loaded.total_nodes_executed == 3
        assert loaded.goal_id == "goal-1"
        assert loaded.execution_quality == "clean"

    @pytest.mark.asyncio
    async def test_load_missing_run_returns_none(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")
        assert await store.load_summary("nonexistent") is None
        assert await store.load_details("nonexistent") is None
        assert await store.load_tool_logs("nonexistent") is None

    @pytest.mark.asyncio
    async def test_list_runs_empty(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")
        runs = await store.list_runs()
        assert runs == []

    @pytest.mark.asyncio
    async def test_list_runs_with_filter(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")

        # Save a success run
        store.ensure_run_dir("run_ok")
        await store.save_summary(
            "run_ok",
            RunSummaryLog(
                run_id="run_ok",
                status="success",
                started_at="2025-01-01T00:00:01",
            ),
        )
        # Save a failure run
        store.ensure_run_dir("run_fail")
        await store.save_summary(
            "run_fail",
            RunSummaryLog(
                run_id="run_fail",
                status="failure",
                needs_attention=True,
                started_at="2025-01-01T00:00:02",
            ),
        )

        # All runs
        all_runs = await store.list_runs()
        assert len(all_runs) == 2

        # Filter by status
        success_runs = await store.list_runs(status="success")
        assert len(success_runs) == 1
        assert success_runs[0].run_id == "run_ok"

        # Filter by needs_attention
        attention_runs = await store.list_runs(status="needs_attention")
        assert len(attention_runs) == 1
        assert attention_runs[0].run_id == "run_fail"

    @pytest.mark.asyncio
    async def test_list_runs_sorted_by_timestamp_desc(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")

        for i in range(5):
            run_id = f"run_{i}"
            store.ensure_run_dir(run_id)
            await store.save_summary(
                run_id,
                RunSummaryLog(
                    run_id=run_id,
                    status="success",
                    started_at=f"2025-01-01T00:00:{i:02d}",
                ),
            )

        runs = await store.list_runs()
        # Most recent first
        assert runs[0].run_id == "run_4"
        assert runs[-1].run_id == "run_0"

    @pytest.mark.asyncio
    async def test_list_runs_limit(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")

        for i in range(10):
            run_id = f"run_{i}"
            store.ensure_run_dir(run_id)
            await store.save_summary(
                run_id,
                RunSummaryLog(
                    run_id=run_id,
                    status="success",
                    started_at=f"2025-01-01T00:00:{i:02d}",
                ),
            )

        runs = await store.list_runs(limit=3)
        assert len(runs) == 3

    @pytest.mark.asyncio
    async def test_list_runs_includes_in_progress(self, tmp_path: Path):
        """Directories without summary.json appear as in_progress."""
        store = RuntimeLogStore(tmp_path / "logs")

        # Completed run with summary
        store.ensure_run_dir("run_done")
        await store.save_summary(
            "run_done",
            RunSummaryLog(
                run_id="run_done",
                status="success",
                started_at="2025-01-01T00:00:01",
            ),
        )

        # In-progress run: directory exists but no summary.json
        store.ensure_run_dir("run_active")

        all_runs = await store.list_runs()
        assert len(all_runs) == 2
        run_ids = {r.run_id for r in all_runs}
        assert "run_done" in run_ids
        assert "run_active" in run_ids

        active = next(r for r in all_runs if r.run_id == "run_active")
        assert active.status == "in_progress"

    @pytest.mark.asyncio
    async def test_read_node_details_sync(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")
        store.ensure_run_dir("test_run")

        store.append_node_detail(
            "test_run",
            NodeDetail(
                node_id="n1", node_name="A", success=True, input_tokens=100, output_tokens=50
            ),
        )
        store.append_node_detail(
            "test_run",
            NodeDetail(node_id="n2", node_name="B", success=False, error="oops"),
        )

        details = store.read_node_details_sync("test_run")
        assert len(details) == 2
        assert details[0].node_id == "n1"
        assert details[1].error == "oops"

    @pytest.mark.asyncio
    async def test_corrupt_jsonl_line_skipped(self, tmp_path: Path):
        """A corrupt JSONL line should be skipped without breaking reads."""
        store = RuntimeLogStore(tmp_path / "logs")
        store.ensure_run_dir("test_run")

        # Write a valid line, a corrupt line, then another valid line
        jsonl_path = tmp_path / "logs" / "runs" / "test_run" / "details.jsonl"
        valid1 = json.dumps(NodeDetail(node_id="n1", node_name="A", success=True).model_dump())
        valid2 = json.dumps(NodeDetail(node_id="n2", node_name="B", success=True).model_dump())
        jsonl_path.write_text(f"{valid1}\n{{corrupt line\n{valid2}\n")

        details = store.read_node_details_sync("test_run")
        assert len(details) == 2
        assert details[0].node_id == "n1"
        assert details[1].node_id == "n2"


# ---------------------------------------------------------------------------
# RuntimeLogger tests
# ---------------------------------------------------------------------------


class TestRuntimeLogger:
    @pytest.mark.asyncio
    async def test_start_run_returns_run_id(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")
        rl = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rl.start_run("goal-1")
        assert run_id
        assert len(run_id) > 10  # timestamp + uuid

    @pytest.mark.asyncio
    async def test_start_run_creates_directory(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")
        rl = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rl.start_run("goal-1")
        assert (tmp_path / "logs" / "runs" / run_id).is_dir()

    @pytest.mark.asyncio
    async def test_log_step_writes_to_disk_immediately(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")
        rl = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rl.start_run("goal-1")

        rl.log_step(
            node_id="node-1",
            node_type="event_loop",
            step_index=0,
            llm_text="Searching.",
            input_tokens=100,
            output_tokens=50,
        )

        # Verify the file exists and has one line
        jsonl_path = tmp_path / "logs" / "runs" / run_id / "tool_logs.jsonl"
        assert jsonl_path.exists()
        lines = [line for line in jsonl_path.read_text().strip().split("\n") if line]
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["node_id"] == "node-1"
        assert data["input_tokens"] == 100

    @pytest.mark.asyncio
    async def test_log_node_complete_writes_to_disk_immediately(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")
        rl = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rl.start_run("goal-1")

        rl.log_node_complete(
            node_id="node-1",
            node_name="Search",
            node_type="event_loop",
            success=True,
            exit_status="success",
        )

        jsonl_path = tmp_path / "logs" / "runs" / run_id / "details.jsonl"
        assert jsonl_path.exists()
        lines = [line for line in jsonl_path.read_text().strip().split("\n") if line]
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["node_id"] == "node-1"
        assert data["exit_status"] == "success"

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, tmp_path: Path):
        """Test start_run -> log_step (x3) -> log_node_complete -> end_run."""
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        # Step 0: RETRY (event_loop iteration)
        rt_logger.log_step(
            node_id="node-1",
            node_type="event_loop",
            step_index=0,
            verdict="RETRY",
            verdict_feedback="Missing output keys: ['result']",
            tool_calls=[
                {
                    "tool_use_id": "tc_1",
                    "tool_name": "web_search",
                    "tool_input": {"query": "test"},
                    "content": "Found data",
                    "is_error": False,
                }
            ],
            llm_text="Let me search for that.",
            input_tokens=100,
            output_tokens=50,
            latency_ms=1000,
        )

        # Step 1: CONTINUE (unjudged)
        rt_logger.log_step(
            node_id="node-1",
            node_type="event_loop",
            step_index=1,
            verdict="CONTINUE",
            verdict_feedback="Unjudged",
            tool_calls=[],
            llm_text="Processing...",
            input_tokens=80,
            output_tokens=30,
            latency_ms=500,
        )

        # Step 2: ACCEPT
        rt_logger.log_step(
            node_id="node-1",
            node_type="event_loop",
            step_index=2,
            verdict="ACCEPT",
            verdict_feedback="All outputs set",
            tool_calls=[],
            llm_text="Here is your result.",
            input_tokens=90,
            output_tokens=40,
            latency_ms=800,
        )

        # Log node completion
        rt_logger.log_node_complete(
            node_id="node-1",
            node_name="Search Node",
            node_type="event_loop",
            success=True,
            total_steps=3,
            tokens_used=390,
            input_tokens=270,
            output_tokens=120,
            latency_ms=2300,
            exit_status="success",
            accept_count=1,
            retry_count=1,
            continue_count=1,
        )

        await rt_logger.end_run(
            status="success",
            duration_ms=2300,
            node_path=["node-1"],
            execution_quality="clean",
        )

        # Verify Level 1: Summary
        summary = await store.load_summary(run_id)
        assert summary is not None
        assert summary.status == "success"
        assert summary.total_nodes_executed == 1
        assert summary.total_input_tokens == 270
        assert summary.total_output_tokens == 120
        assert summary.needs_attention is False
        assert summary.duration_ms == 2300
        assert summary.execution_quality == "clean"
        assert summary.node_path == ["node-1"]

        # Verify Level 2: Details
        details = await store.load_details(run_id)
        assert details is not None
        assert len(details.nodes) == 1
        assert details.nodes[0].node_id == "node-1"
        assert details.nodes[0].exit_status == "success"
        assert details.nodes[0].accept_count == 1
        assert details.nodes[0].retry_count == 1

        # Verify Level 3: Tool logs
        tool_logs = await store.load_tool_logs(run_id)
        assert tool_logs is not None
        assert len(tool_logs.steps) == 3
        assert tool_logs.steps[0].tool_calls[0].tool_name == "web_search"
        assert tool_logs.steps[0].input_tokens == 100
        assert tool_logs.steps[0].verdict == "RETRY"
        assert tool_logs.steps[2].verdict == "ACCEPT"

    @pytest.mark.asyncio
    async def test_trace_context_populated_in_l1_l2_l3(self, tmp_path: Path):
        """With trace context set, L3/L2/L1 entries include trace_id, span_id, execution_id."""
        set_trace_context(
            trace_id="a1b2c3d4e5f6789012345678abcdef01",
            execution_id="b2c3d4e5f6789012345678abcdef0123",
        )
        try:
            store = RuntimeLogStore(tmp_path / "logs")
            rl = RuntimeLogger(store=store, agent_id="test-agent")
            run_id = rl.start_run("goal-1")

            rl.log_step(
                node_id="node-1",
                node_type="event_loop",
                step_index=0,
                llm_text="Step.",
                input_tokens=10,
                output_tokens=5,
            )
            rl.log_node_complete(
                node_id="node-1",
                node_name="Search",
                node_type="event_loop",
                success=True,
                exit_status="success",
            )
            await rl.end_run(
                status="success",
                duration_ms=100,
                node_path=["node-1"],
                execution_quality="clean",
            )

            # L3: tool_logs
            tool_logs = await store.load_tool_logs(run_id)
            assert tool_logs is not None
            assert len(tool_logs.steps) == 1
            step = tool_logs.steps[0]
            assert step.trace_id == "a1b2c3d4e5f6789012345678abcdef01"
            assert step.execution_id == "b2c3d4e5f6789012345678abcdef0123"
            assert len(step.span_id) == 16
            assert all(c in "0123456789abcdef" for c in step.span_id)

            # L2: details
            details = await store.load_details(run_id)
            assert details is not None
            assert len(details.nodes) == 1
            nd = details.nodes[0]
            assert nd.trace_id == "a1b2c3d4e5f6789012345678abcdef01"
            assert len(nd.span_id) == 16

            # L1: summary
            summary = await store.load_summary(run_id)
            assert summary is not None
            assert summary.trace_id == "a1b2c3d4e5f6789012345678abcdef01"
            assert summary.execution_id == "b2c3d4e5f6789012345678abcdef0123"
        finally:
            clear_trace_context()

    @pytest.mark.asyncio
    async def test_trace_context_empty_when_not_set(self, tmp_path: Path):
        """Without trace context, L3/L2/L1 trace_id and execution_id are empty."""
        clear_trace_context()
        store = RuntimeLogStore(tmp_path / "logs")
        rl = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rl.start_run("goal-1")

        rl.log_step(
            node_id="node-1",
            node_type="event_loop",
            step_index=0,
            llm_text="Step.",
            input_tokens=10,
            output_tokens=5,
        )
        rl.log_node_complete(
            node_id="node-1",
            node_name="Search",
            node_type="event_loop",
            success=True,
            exit_status="success",
        )
        await rl.end_run(
            status="success",
            duration_ms=100,
            node_path=["node-1"],
            execution_quality="clean",
        )

        # L3: trace_id and execution_id from context should be empty
        tool_logs = await store.load_tool_logs(run_id)
        assert tool_logs is not None
        assert len(tool_logs.steps) == 1
        assert tool_logs.steps[0].trace_id == ""
        assert tool_logs.steps[0].execution_id == ""

        # L2
        details = await store.load_details(run_id)
        assert details is not None
        assert details.nodes[0].trace_id == ""

        # L1
        summary = await store.load_summary(run_id)
        assert summary is not None
        assert summary.trace_id == ""
        assert summary.execution_id == ""

    @pytest.mark.asyncio
    async def test_multi_node_lifecycle(self, tmp_path: Path):
        """Test logging across multiple nodes in a graph run."""
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        # Node 1: event_loop
        rt_logger.log_step(
            node_id="node-1",
            node_type="event_loop",
            step_index=0,
            verdict="ACCEPT",
            llm_text="Done.",
            input_tokens=100,
            output_tokens=50,
        )
        rt_logger.log_node_complete(
            node_id="node-1",
            node_name="Search",
            node_type="event_loop",
            success=True,
            total_steps=1,
            tokens_used=150,
            input_tokens=100,
            output_tokens=50,
            exit_status="success",
            accept_count=1,
        )

        # Node 2: function
        rt_logger.log_step(
            node_id="node-2",
            node_type="event_loop",
            step_index=0,
            latency_ms=50,
        )
        rt_logger.log_node_complete(
            node_id="node-2",
            node_name="Process",
            node_type="event_loop",
            success=True,
            total_steps=1,
            latency_ms=50,
        )

        await rt_logger.end_run(
            status="success",
            duration_ms=1000,
            node_path=["node-1", "node-2"],
            execution_quality="clean",
        )

        summary = await store.load_summary(run_id)
        assert summary.total_nodes_executed == 2
        assert summary.node_path == ["node-1", "node-2"]
        assert summary.total_input_tokens == 100
        assert summary.total_output_tokens == 50

        details = await store.load_details(run_id)
        assert len(details.nodes) == 2

    @pytest.mark.asyncio
    async def test_failed_node_needs_attention(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        rt_logger.log_step(
            node_id="node-1",
            node_type="event_loop",
            step_index=0,
            verdict="ESCALATE",
            verdict_feedback="Cannot proceed, need human input",
            tool_calls=[],
            llm_text="I'm stuck.",
            input_tokens=50,
            output_tokens=20,
            latency_ms=300,
        )

        rt_logger.log_node_complete(
            node_id="node-1",
            node_name="Search",
            node_type="event_loop",
            success=False,
            error="Judge escalated: Cannot proceed",
            total_steps=1,
            tokens_used=70,
            latency_ms=300,
            exit_status="escalated",
            escalate_count=1,
        )

        await rt_logger.end_run(
            status="failure",
            duration_ms=300,
            node_path=["node-1"],
            execution_quality="failed",
        )

        summary = await store.load_summary(run_id)
        assert summary is not None
        assert summary.needs_attention is True
        assert any(
            "failed" in r.lower() or "escalat" in r.lower() for r in summary.attention_reasons
        )

    @pytest.mark.asyncio
    async def test_ensure_node_logged_no_op_if_already_logged(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        # Node logs itself
        rt_logger.log_node_complete(
            node_id="node-1",
            node_name="Search",
            node_type="event_loop",
            success=True,
            exit_status="success",
        )

        # Executor calls ensure_node_logged — should be no-op
        rt_logger.ensure_node_logged(
            node_id="node-1",
            node_name="Search",
            node_type="event_loop",
            success=True,
        )

        # Only one entry on disk
        details = store.read_node_details_sync(run_id)
        assert len(details) == 1

    @pytest.mark.asyncio
    async def test_ensure_node_logged_creates_entry_if_missing(self, tmp_path: Path):
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        # Node didn't log itself — executor calls ensure
        rt_logger.ensure_node_logged(
            node_id="node-1",
            node_name="Search",
            node_type="event_loop",
            success=False,
            error="Crashed",
        )

        details = store.read_node_details_sync(run_id)
        assert len(details) == 1
        assert details[0].error == "Crashed"
        assert details[0].needs_attention is True

    @pytest.mark.asyncio
    async def test_large_data_preserved(self, tmp_path: Path):
        """Large tool input/result/llm_text values should be stored in full."""
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        long_value = "x" * 2000
        rt_logger.log_step(
            node_id="node-1",
            node_type="event_loop",
            step_index=0,
            verdict="ACCEPT",
            tool_calls=[
                {
                    "tool_use_id": "tc_1",
                    "tool_name": "write_file",
                    "tool_input": {"content": long_value},
                    "content": "y" * 5000,
                    "is_error": False,
                }
            ],
            llm_text="z" * 5000,
            input_tokens=100,
            output_tokens=50,
            latency_ms=500,
        )

        rt_logger.log_node_complete(
            node_id="node-1",
            node_name="Writer",
            node_type="event_loop",
            success=True,
            total_steps=1,
            exit_status="success",
        )

        await rt_logger.end_run(
            status="success",
            duration_ms=500,
            node_path=["node-1"],
        )

        tool_logs = await store.load_tool_logs(run_id)
        assert tool_logs is not None
        tc = tool_logs.steps[0].tool_calls[0]
        # Full values preserved
        assert len(tc.tool_input["content"]) == 2000
        assert len(tc.result) == 5000
        assert len(tool_logs.steps[0].llm_text) == 5000

    @pytest.mark.asyncio
    async def test_end_run_does_not_propagate_exceptions(self, tmp_path: Path):
        """end_run must catch all exceptions and never propagate."""
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        rt_logger.start_run("goal-1")

        # Make the store path unwritable to force an error
        import os

        bad_path = tmp_path / "logs" / "runs"
        bad_path.mkdir(parents=True, exist_ok=True)
        # Create a file where directory should be
        run_dir = bad_path / rt_logger._run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        blocker = run_dir / "summary.json"
        blocker.write_text("not json")
        os.chmod(str(run_dir), 0o444)

        try:
            # This should NOT raise, even though writing will fail
            await rt_logger.end_run("success", duration_ms=100)
        finally:
            # Restore permissions for cleanup
            os.chmod(str(run_dir), 0o755)

    @pytest.mark.asyncio
    async def test_crash_resilience_l2_l3_survive(self, tmp_path: Path):
        """L2 and L3 data survives even if end_run() is never called (crash)."""
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        # Log some steps and a node
        rt_logger.log_step(
            node_id="node-1",
            node_type="event_loop",
            step_index=0,
            llm_text="Working...",
            input_tokens=100,
            output_tokens=50,
        )
        rt_logger.log_step(
            node_id="node-1",
            node_type="event_loop",
            step_index=1,
            llm_text="Still working...",
            input_tokens=80,
            output_tokens=30,
        )
        rt_logger.log_node_complete(
            node_id="node-1",
            node_name="Search",
            node_type="event_loop",
            success=True,
            total_steps=2,
            input_tokens=180,
            output_tokens=80,
        )

        # Simulate crash: do NOT call end_run()

        # Verify L2 and L3 are recoverable from disk
        details = await store.load_details(run_id)
        assert details is not None
        assert len(details.nodes) == 1
        assert details.nodes[0].node_id == "node-1"

        tool_logs = await store.load_tool_logs(run_id)
        assert tool_logs is not None
        assert len(tool_logs.steps) == 2

        # But no L1 summary exists
        summary = await store.load_summary(run_id)
        assert summary is None

    @pytest.mark.asyncio
    async def test_in_progress_run_visible_in_list(self, tmp_path: Path):
        """An in-progress run (no summary.json) appears in list_runs."""
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        # Log a step but don't end
        rt_logger.log_step(
            node_id="node-1",
            node_type="event_loop",
            step_index=0,
            llm_text="Working...",
        )

        runs = await store.list_runs()
        assert len(runs) == 1
        assert runs[0].run_id == run_id
        assert runs[0].status == "in_progress"

    @pytest.mark.asyncio
    async def test_log_step_with_error_and_stacktrace(self, tmp_path: Path):
        """Test logging partial steps with errors and stack traces."""
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        # Log a partial step with error
        rt_logger.log_step(
            node_id="node-1",
            node_type="event_loop",
            step_index=0,
            error="LLM call failed: Connection timeout",
            stacktrace=(
                "Traceback (most recent call last):\n"
                "  File test.py line 10\n"
                "    raise TimeoutError()"
            ),
            is_partial=True,
        )

        # Verify the step was logged
        loaded = await store.load_tool_logs(run_id)
        assert loaded is not None
        assert len(loaded.steps) == 1
        step = loaded.steps[0]
        assert step.error == "LLM call failed: Connection timeout"
        assert "TimeoutError" in step.stacktrace
        assert step.is_partial is True

    @pytest.mark.asyncio
    async def test_log_node_complete_with_stacktrace(self, tmp_path: Path):
        """Test logging node completion with stack traces."""
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        # Log node failure with stacktrace
        rt_logger.log_node_complete(
            node_id="node-1",
            node_name="Test Node",
            node_type="event_loop",
            success=False,
            error="Node crashed",
            stacktrace=(
                "Traceback (most recent call last):\n"
                "  File node.py line 42\n"
                "    raise RuntimeError('crash')"
            ),
        )

        # Verify the detail was logged with stacktrace
        loaded = await store.load_details(run_id)
        assert loaded is not None
        assert len(loaded.nodes) == 1
        node = loaded.nodes[0]
        assert node.error == "Node crashed"
        assert "RuntimeError" in node.stacktrace

    @pytest.mark.asyncio
    async def test_attention_flags_excessive_retries(self, tmp_path: Path):
        """Test that excessive retries trigger attention flags."""
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        # Log node with excessive retries
        rt_logger.log_node_complete(
            node_id="node-1",
            node_name="Retry Node",
            node_type="event_loop",
            success=True,
            retry_count=5,  # > 3 threshold
        )

        # Verify attention flag is set
        loaded = await store.load_details(run_id)
        assert loaded is not None
        node = loaded.nodes[0]
        assert node.needs_attention is True
        assert any("Excessive retries" in reason for reason in node.attention_reasons)

    @pytest.mark.asyncio
    async def test_attention_flags_high_latency(self, tmp_path: Path):
        """Test that high latency triggers attention flags."""
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        # Log node with high latency
        rt_logger.log_node_complete(
            node_id="node-1",
            node_name="Slow Node",
            node_type="event_loop",
            success=True,
            latency_ms=65000,  # > 60000 threshold
        )

        # Verify attention flag is set
        loaded = await store.load_details(run_id)
        assert loaded is not None
        node = loaded.nodes[0]
        assert node.needs_attention is True
        assert any("High latency" in reason for reason in node.attention_reasons)

    @pytest.mark.asyncio
    async def test_attention_flags_high_token_usage(self, tmp_path: Path):
        """Test that high token usage triggers attention flags."""
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        # Log node with high token usage
        rt_logger.log_node_complete(
            node_id="node-1",
            node_name="Token Heavy Node",
            node_type="event_loop",
            success=True,
            tokens_used=150000,  # > 100000 threshold
        )

        # Verify attention flag is set
        loaded = await store.load_details(run_id)
        assert loaded is not None
        node = loaded.nodes[0]
        assert node.needs_attention is True
        assert any("High token usage" in reason for reason in node.attention_reasons)

    @pytest.mark.asyncio
    async def test_attention_flags_many_iterations(self, tmp_path: Path):
        """Test that many iterations trigger attention flags."""
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        # Log node with many iterations
        rt_logger.log_node_complete(
            node_id="node-1",
            node_name="Iterative Node",
            node_type="event_loop",
            success=True,
            total_steps=25,  # > 20 threshold
        )

        # Verify attention flag is set
        loaded = await store.load_details(run_id)
        assert loaded is not None
        node = loaded.nodes[0]
        assert node.needs_attention is True
        assert any("Many iterations" in reason for reason in node.attention_reasons)

    @pytest.mark.asyncio
    async def test_guard_failure_exit_status(self, tmp_path: Path):
        """Test that guard failures use the correct exit status."""
        store = RuntimeLogStore(tmp_path / "logs")
        rt_logger = RuntimeLogger(store=store, agent_id="test-agent")
        run_id = rt_logger.start_run("goal-1")

        # Log a guard failure
        rt_logger.log_node_complete(
            node_id="node-1",
            node_name="Guard Node",
            node_type="event_loop",
            success=False,
            error="LLM provider not available",
            exit_status="guard_failure",
        )

        # Verify exit status
        loaded = await store.load_details(run_id)
        assert loaded is not None
        node = loaded.nodes[0]
        assert node.exit_status == "guard_failure"
        assert node.success is False
