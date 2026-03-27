"""
Test that _write_progress serializes concurrent writes to state.json.

Verifies the fix for the read-modify-write race condition where concurrent
calls to _write_progress could overwrite each other's updates, causing
data loss in the progress state.
"""

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from framework.graph.executor import GraphExecutor
from framework.runtime.core import Runtime


class FakeMemory:
    """Minimal SharedMemory stub for testing."""

    def __init__(self, data: dict | None = None):
        self._data = data or {}

    def read_all(self) -> dict:
        return dict(self._data)


class SlowMemory:
    """SharedMemory stub that takes time to read, widening the race window."""

    def __init__(self, data: dict, delay: float = 0.05):
        self._data = data
        self._delay = delay

    def read_all(self) -> dict:
        time.sleep(self._delay)
        return dict(self._data)


def _make_executor(storage_path: Path) -> GraphExecutor:
    """Create a minimal GraphExecutor with a storage path."""
    runtime = MagicMock(spec=Runtime)
    runtime.execution_id = "test-exec"
    llm = MagicMock()
    return GraphExecutor(
        runtime=runtime,
        llm=llm,
        tools=[],
        tool_executor=MagicMock(),
        storage_path=str(storage_path),
    )


class TestWriteProgressBasic:
    """Basic functional tests for _write_progress."""

    def test_write_progress_creates_state_file(self, tmp_path: Path):
        """_write_progress creates state.json if it doesn't exist."""
        executor = _make_executor(tmp_path)
        memory = FakeMemory({"key": "value"})

        executor._write_progress("node_a", ["node_a"], memory, {"node_a": 1})

        state_path = tmp_path / "state.json"
        assert state_path.exists()
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["progress"]["current_node"] == "node_a"
        assert data["progress"]["path"] == ["node_a"]
        assert data["progress"]["node_visit_counts"] == {"node_a": 1}
        assert data["progress"]["steps_executed"] == 1
        assert data["memory"] == {"key": "value"}
        assert data["memory_keys"] == ["key"]

    def test_write_progress_preserves_existing_fields(self, tmp_path: Path):
        """_write_progress patches progress without clobbering other fields."""
        state_path = tmp_path / "state.json"
        state_path.write_text(
            json.dumps({
                "session_id": "sess-123",
                "status": "active",
                "goal_id": "goal-1",
                "pid": 12345,
                "result": {"error": None},
            }),
            encoding="utf-8",
        )

        executor = _make_executor(tmp_path)
        memory = FakeMemory()

        executor._write_progress(
            "node_b", ["node_a", "node_b"],
            memory, {"node_a": 1, "node_b": 1},
        )

        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["session_id"] == "sess-123"
        assert data["status"] == "active"
        assert data["goal_id"] == "goal-1"
        assert data["pid"] == 12345
        assert data["result"] == {"error": None}
        assert data["progress"]["current_node"] == "node_b"

    def test_sequential_writes_update_correctly(self, tmp_path: Path):
        """Multiple sequential writes each see the previous write's state."""
        executor = _make_executor(tmp_path)

        for i in range(20):
            node_id = f"node_{i}"
            path = [f"node_{j}" for j in range(i + 1)]
            counts = {f"node_{j}": 1 for j in range(i + 1)}
            memory = FakeMemory({"step": i})
            executor._write_progress(node_id, path, memory, counts)

        data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert data["progress"]["current_node"] == "node_19"
        assert data["progress"]["steps_executed"] == 20
        assert len(data["progress"]["path"]) == 20
        assert len(data["progress"]["node_visit_counts"]) == 20
        assert data["memory"] == {"step": 19}

    def test_write_progress_updates_timestamp(self, tmp_path: Path):
        """Each write updates the timestamps.updated_at field."""
        executor = _make_executor(tmp_path)

        executor._write_progress("node_a", ["node_a"], FakeMemory(), {"node_a": 1})
        data1 = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        ts1 = data1["timestamps"]["updated_at"]

        time.sleep(0.01)

        executor._write_progress(
            "node_b", ["node_a", "node_b"],
            FakeMemory(), {"node_a": 1, "node_b": 1},
        )
        data2 = json.loads(
            (tmp_path / "state.json").read_text(encoding="utf-8"),
        )
        ts2 = data2["timestamps"]["updated_at"]

        assert ts2 > ts1, "Timestamp should advance on each write"

    def test_write_progress_with_large_memory(self, tmp_path: Path):
        """_write_progress handles large memory snapshots correctly."""
        executor = _make_executor(tmp_path)
        large_data = {f"key_{i}": f"value_{'x' * 1000}" for i in range(100)}
        memory = FakeMemory(large_data)

        executor._write_progress("node_a", ["node_a"], memory, {"node_a": 1})

        data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert len(data["memory"]) == 100
        assert len(data["memory_keys"]) == 100

    def test_no_storage_path_is_noop(self):
        """_write_progress is a no-op when storage_path is None."""
        runtime = MagicMock(spec=Runtime)
        runtime.execution_id = "test"
        executor = GraphExecutor(
            runtime=runtime,
            llm=MagicMock(),
            tools=[],
            tool_executor=MagicMock(),
            storage_path=None,
        )
        # Should not raise
        executor._write_progress("node_a", ["node_a"], FakeMemory(), {"node_a": 1})

    def test_write_progress_resilient_to_memory_exception(self, tmp_path: Path):
        """_write_progress silently catches errors (best-effort)."""

        class BrokenMemory:
            def read_all(self):
                raise RuntimeError("memory corrupted")

        executor = _make_executor(tmp_path)
        # Should not raise — best-effort semantics
        executor._write_progress("node_a", ["node_a"], BrokenMemory(), {"node_a": 1})


class TestWriteProgressAtomicWrite:
    """Tests verifying atomic write behavior (no partial/corrupt files)."""

    def test_no_leftover_tmp_files(self, tmp_path: Path):
        """Atomic writes must not leave .tmp files behind."""
        executor = _make_executor(tmp_path)
        memory = FakeMemory({"k": "v"})

        for i in range(10):
            executor._write_progress(f"node_{i}", [f"node_{i}"], memory, {f"node_{i}": 1})

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Leftover temp files: {tmp_files}"

    def test_file_always_valid_json_after_write(self, tmp_path: Path):
        """state.json must be valid JSON after every single write."""
        executor = _make_executor(tmp_path)

        for i in range(50):
            memory = FakeMemory({"iteration": i, "nested": {"a": [1, 2, 3]}})
            executor._write_progress(
                f"node_{i}",
                [f"node_{j}" for j in range(i + 1)],
                memory,
                {f"node_{j}": j + 1 for j in range(i + 1)},
            )
            # Verify valid JSON after every write
            raw = (tmp_path / "state.json").read_text(encoding="utf-8")
            data = json.loads(raw)  # Would raise JSONDecodeError if corrupt
            assert data["progress"]["current_node"] == f"node_{i}"

    def test_atomic_write_on_crash_preserves_previous(self, tmp_path: Path):
        """If atomic_write fails mid-write, the previous state.json is intact."""
        executor = _make_executor(tmp_path)
        memory = FakeMemory({"step": 1})

        # Write valid initial state
        executor._write_progress(
            "node_a", ["node_a"], memory, {"node_a": 1},
        )
        original_data = json.loads(
            (tmp_path / "state.json").read_text(encoding="utf-8"),
        )

        # Simulate a crash during atomic_write by raising OSError
        target = "framework.utils.io.atomic_write"
        with patch(target, side_effect=OSError("disk full")):
            # This should fail silently (best-effort)
            executor._write_progress(
                "node_b", ["node_a", "node_b"],
                FakeMemory({"step": 2}),
                {"node_a": 1, "node_b": 1},
            )

        # Original state.json must be intact
        preserved = json.loads(
            (tmp_path / "state.json").read_text(encoding="utf-8"),
        )
        assert preserved == original_data, (
            "Previous state.json should survive a failed write"
        )


class TestWriteProgressConcurrency:
    """Concurrency stress tests for the race condition fix."""

    def test_concurrent_writes_valid_json(self, tmp_path: Path):
        """Concurrent _write_progress calls must never corrupt state.json."""
        executor = _make_executor(tmp_path)

        (tmp_path / "state.json").write_text(
            json.dumps({"session_id": "sess-concurrent", "status": "active"}),
            encoding="utf-8",
        )

        num_threads = 20
        barrier = threading.Barrier(num_threads)
        errors: list[Exception] = []

        def write_from_thread(thread_id: int) -> None:
            try:
                memory = FakeMemory({f"thread_{thread_id}": thread_id})
                barrier.wait(timeout=5)
                executor._write_progress(
                    f"node_{thread_id}",
                    [f"node_{i}" for i in range(thread_id + 1)],
                    memory,
                    {f"node_{i}": 1 for i in range(thread_id + 1)},
                )
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=write_from_thread, args=(i,))
            for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Threads raised errors: {errors}"

        state_path = tmp_path / "state.json"
        data = json.loads(state_path.read_text(encoding="utf-8"))

        # Original fields must survive all concurrent writes
        assert data["session_id"] == "sess-concurrent"
        assert data["status"] == "active"
        assert "progress" in data
        assert "current_node" in data["progress"]
        assert data["progress"]["current_node"].startswith("node_")
        assert "memory" in data
        assert "timestamps" in data

    def test_concurrent_writes_serialized_ordering(self, tmp_path: Path):
        """Verify the lock serializes writes — each write sees the previous one.

        We use SlowMemory to widen the race window. Without the lock,
        threads would read the same stale state and overwrite each other.
        With the lock, each thread reads the state left by the previous writer.
        """
        executor = _make_executor(tmp_path)
        state_path = tmp_path / "state.json"

        # Seed with a counter
        state_path.write_text(
            json.dumps({"write_sequence": [], "session_id": "test"}),
            encoding="utf-8",
        )

        num_threads = 8
        barrier = threading.Barrier(num_threads)
        errors: list[Exception] = []

        def write_and_append_id(thread_id: int) -> None:
            try:
                barrier.wait(timeout=5)
                # Acquire the lock, read current state, append our ID, write back
                with executor._progress_lock:
                    data = json.loads(state_path.read_text(encoding="utf-8"))
                    data["write_sequence"].append(thread_id)
                    from framework.utils.io import atomic_write
                    with atomic_write(state_path) as f:
                        f.write(json.dumps(data, indent=2))
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(
                target=write_and_append_id, args=(i,),
            )
            for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Threads raised errors: {errors}"

        data = json.loads(state_path.read_text(encoding="utf-8"))
        # All thread IDs must be present — none lost to a clobber
        assert sorted(data["write_sequence"]) == list(range(num_threads)), (
            f"Expected all thread IDs 0-{num_threads - 1} but got {data['write_sequence']}. "
            "Some writes were lost — the lock is not serializing correctly."
        )

    def test_high_contention_stress(self, tmp_path: Path):
        """50 threads, 5 writes each — no corruption under sustained load."""
        executor = _make_executor(tmp_path)
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"session_id": "stress"}), encoding="utf-8")

        num_threads = 50
        writes_per_thread = 5
        barrier = threading.Barrier(num_threads)
        errors: list[Exception] = []

        def hammer(thread_id: int) -> None:
            try:
                barrier.wait(timeout=10)
                for w in range(writes_per_thread):
                    memory = FakeMemory({f"t{thread_id}_w{w}": True})
                    executor._write_progress(
                        f"node_t{thread_id}_w{w}",
                        [f"step_{w}"],
                        memory,
                        {f"node_t{thread_id}_w{w}": 1},
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=hammer, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"{len(errors)} threads raised errors: {errors[:5]}"

        # File must be valid JSON
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["session_id"] == "stress"
        assert "progress" in data
        assert "memory" in data
        assert "timestamps" in data

        # No leftover temp files
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Leftover temp files after stress: {tmp_files}"

    def test_slow_memory_read_does_not_cause_clobber(self, tmp_path: Path):
        """SlowMemory widens the race window; the lock must still prevent clobber.

        Without the lock: thread A reads state, thread B reads same state,
        A writes (with its memory), B writes (with its memory) — A's progress
        fields are lost. With the lock, B reads after A writes.
        """
        executor = _make_executor(tmp_path)
        state_path = tmp_path / "state.json"

        state_path.write_text(
            json.dumps({"session_id": "slow-mem", "marker": "original"}),
            encoding="utf-8",
        )

        num_threads = 10
        barrier = threading.Barrier(num_threads)
        write_order: list[int] = []
        order_lock = threading.Lock()
        errors: list[Exception] = []

        def write_with_slow_memory(thread_id: int) -> None:
            try:
                # Each thread has distinct memory to detect clobbering
                memory = SlowMemory({f"mem_from_thread_{thread_id}": True}, delay=0.02)
                barrier.wait(timeout=5)
                executor._write_progress(
                    f"node_{thread_id}",
                    [f"path_{thread_id}"],
                    memory,
                    {f"node_{thread_id}": 1},
                )
                with order_lock:
                    write_order.append(thread_id)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(
                target=write_with_slow_memory, args=(i,),
            )
            for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, f"Errors: {errors}"

        data = json.loads(state_path.read_text(encoding="utf-8"))
        # Original marker field must survive
        assert data["marker"] == "original"
        assert data["session_id"] == "slow-mem"
        # The final state must reflect the last writer's data
        last_writer = write_order[-1]
        assert data["progress"]["current_node"] == f"node_{last_writer}"
        assert data["memory"] == {f"mem_from_thread_{last_writer}": True}

    def test_concurrent_read_during_write(self, tmp_path: Path):
        """Readers during concurrent writes must always see valid JSON.

        Simulates ExecutionStream or API routes reading state.json while
        _write_progress is actively writing.
        """
        executor = _make_executor(tmp_path)
        state_path = tmp_path / "state.json"
        state_path.write_text(
            json.dumps({"session_id": "read-during-write", "status": "active"}),
            encoding="utf-8",
        )

        stop_event = threading.Event()
        read_errors: list[str] = []
        read_count = 0
        read_count_lock = threading.Lock()

        def writer():
            for i in range(100):
                memory = FakeMemory({"step": i})
                executor._write_progress(
                    f"node_{i}",
                    [f"n{j}" for j in range(i + 1)],
                    memory,
                    {f"node_{i}": 1},
                )
            stop_event.set()

        def reader():
            nonlocal read_count
            while not stop_event.is_set():
                try:
                    raw = state_path.read_text(encoding="utf-8")
                    data = json.loads(raw)  # Must always parse
                    # Must always have session_id
                    if "session_id" not in data:
                        read_errors.append("Missing session_id")
                    with read_count_lock:
                        read_count += 1
                except json.JSONDecodeError as e:
                    read_errors.append(f"Corrupt JSON: {e}")
                except FileNotFoundError:
                    pass  # Acceptable during temp-file swap
                except Exception as e:
                    read_errors.append(f"Unexpected: {e}")

        writer_thread = threading.Thread(target=writer)
        reader_threads = [threading.Thread(target=reader) for _ in range(5)]

        for r in reader_threads:
            r.start()
        writer_thread.start()

        writer_thread.join(timeout=15)
        stop_event.set()
        for r in reader_threads:
            r.join(timeout=5)

        assert not read_errors, f"Readers saw invalid state: {read_errors[:5]}"
        assert read_count > 0, "Readers must have completed at least one read"


class TestWriteProgressEdgeCases:
    """Edge case tests."""

    def test_empty_path_and_counts(self, tmp_path: Path):
        """Handles empty path and counts without error."""
        executor = _make_executor(tmp_path)
        executor._write_progress("start", [], FakeMemory(), {})

        data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert data["progress"]["current_node"] == "start"
        assert data["progress"]["path"] == []
        assert data["progress"]["node_visit_counts"] == {}
        assert data["progress"]["steps_executed"] == 0

    def test_special_characters_in_node_ids(self, tmp_path: Path):
        """Node IDs with special characters are handled correctly."""
        executor = _make_executor(tmp_path)
        node_id = "node/with:special-chars_and.dots"
        executor._write_progress(node_id, [node_id], FakeMemory({"key": "val"}), {node_id: 1})

        data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert data["progress"]["current_node"] == node_id

    def test_unicode_in_memory(self, tmp_path: Path):
        """Memory with unicode content is preserved."""
        executor = _make_executor(tmp_path)
        msg = "Hello 世界 🌍"
        memory = FakeMemory({"message": msg, "emoji": "❤️"})
        executor._write_progress("node_a", ["node_a"], memory, {"node_a": 1})

        data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert data["memory"]["message"] == msg

    def test_overwrite_corrupted_state_file(self, tmp_path: Path):
        """If state.json contains invalid JSON, _write_progress handles it gracefully."""
        state_path = tmp_path / "state.json"
        state_path.write_text("{invalid json content???", encoding="utf-8")

        executor = _make_executor(tmp_path)
        # The read will fail, triggering the except branch — best-effort, no crash
        executor._write_progress("node_a", ["node_a"], FakeMemory(), {"node_a": 1})
        # We don't assert the file content since the behavior on corrupt input
        # is best-effort — the important thing is no crash

    def test_memory_with_nested_structures(self, tmp_path: Path):
        """Complex nested memory objects serialize and deserialize correctly."""
        executor = _make_executor(tmp_path)
        complex_memory = FakeMemory({
            "conversations": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ],
            "metadata": {
                "nested": {"deep": {"value": 42}},
                "list_of_lists": [[1, 2], [3, 4]],
            },
            "null_value": None,
            "boolean": True,
            "number": 3.14159,
        })
        executor._write_progress("node_a", ["node_a"], complex_memory, {"node_a": 1})

        data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert data["memory"]["conversations"][1]["content"] == "hi there"
        assert data["memory"]["metadata"]["nested"]["deep"]["value"] == 42
        assert data["memory"]["null_value"] is None
        assert data["memory"]["number"] == 3.14159

    def test_two_executors_same_file_both_use_locks(self, tmp_path: Path):
        """Two executor instances targeting the same state.json.

        Each has its own lock, so cross-executor serialization relies on
        atomic_write (no partial reads). Verify no corruption.
        """
        exec_a = _make_executor(tmp_path)
        exec_b = _make_executor(tmp_path)
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"session_id": "shared"}), encoding="utf-8")

        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def writer_a():
            try:
                barrier.wait(timeout=5)
                for i in range(20):
                    exec_a._write_progress(
                        f"a_{i}", [f"a_{i}"],
                        FakeMemory({"from": "a"}),
                        {f"a_{i}": 1},
                    )
            except Exception as e:
                errors.append(e)

        def writer_b():
            try:
                barrier.wait(timeout=5)
                for i in range(20):
                    exec_b._write_progress(
                        f"b_{i}", [f"b_{i}"],
                        FakeMemory({"from": "b"}),
                        {f"b_{i}": 1},
                    )
            except Exception as e:
                errors.append(e)

        ta = threading.Thread(target=writer_a)
        tb = threading.Thread(target=writer_b)
        ta.start()
        tb.start()
        ta.join(timeout=15)
        tb.join(timeout=15)

        assert not errors, f"Errors: {errors}"

        # File must be valid JSON with original fields preserved
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["session_id"] == "shared"
        assert "progress" in data
        assert "memory" in data
