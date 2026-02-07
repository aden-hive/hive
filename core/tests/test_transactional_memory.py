"""Tests for transactional SharedMemory behavior.

These tests verify that the transaction layer (begin_transaction, commit_transaction,
rollback_transaction) correctly stages writes and handles success/failure scenarios.
"""

import pytest

from framework.graph.node import SharedMemory


class TestTransactionBasics:
    """Basic transaction lifecycle tests."""

    def test_begin_transaction_returns_unique_id(self):
        """Each call to begin_transaction returns a unique ID."""
        memory = SharedMemory()
        txn1 = memory.begin_transaction()
        memory.commit_transaction(txn1)  # Complete first before starting second
        txn2 = memory.begin_transaction()
        assert txn1 != txn2
        assert txn1.startswith("txn_")
        assert txn2.startswith("txn_")

    def test_has_active_transaction(self):
        """has_active_transaction reflects transaction state."""
        memory = SharedMemory()
        assert not memory.has_active_transaction()
        txn_id = memory.begin_transaction()
        assert memory.has_active_transaction()
        memory.commit_transaction(txn_id)
        assert not memory.has_active_transaction()

    def test_get_current_transaction(self):
        """get_current_transaction returns the current transaction ID."""
        memory = SharedMemory()
        assert memory.get_current_transaction() is None
        txn_id = memory.begin_transaction()
        assert memory.get_current_transaction() == txn_id
        memory.rollback_transaction(txn_id)
        assert memory.get_current_transaction() is None


class TestWriteStaging:
    """Tests for staged writes during transactions."""

    def test_write_during_transaction_is_staged(self):
        """Writes during a transaction are staged, not committed."""
        memory = SharedMemory()
        memory.write("existing", "value1")

        txn_id = memory.begin_transaction()
        memory.write("new_key", "staged_value")

        # Staged write should not be in committed data
        assert memory._data.get("new_key") is None
        # But should be in staged data
        assert memory._staged_data[txn_id]["new_key"] == "staged_value"

        memory.rollback_transaction(txn_id)

    def test_commit_moves_staged_to_committed(self):
        """Committing a transaction moves staged data to committed data."""
        memory = SharedMemory()
        txn_id = memory.begin_transaction()
        memory.write("key1", "value1")
        memory.write("key2", "value2")
        memory.commit_transaction(txn_id)

        assert memory._data["key1"] == "value1"
        assert memory._data["key2"] == "value2"

    def test_rollback_discards_staged_data(self):
        """Rolling back a transaction discards all staged writes."""
        memory = SharedMemory()
        memory.write("original", "preserved")

        txn_id = memory.begin_transaction()
        memory.write("new", "discarded")
        memory.write("original", "overwritten")
        memory.rollback_transaction(txn_id)

        assert memory._data.get("new") is None
        assert memory._data["original"] == "preserved"


class TestReadYourOwnWrites:
    """Tests for read-your-own-writes semantics."""

    def test_read_sees_staged_data(self):
        """Reads within a transaction see staged data."""
        memory = SharedMemory()
        memory.write("committed", "original")

        txn_id = memory.begin_transaction()
        memory.write("committed", "staged")
        memory.write("new", "staged_new")

        assert memory.read("committed") == "staged"
        assert memory.read("new") == "staged_new"

        memory.rollback_transaction(txn_id)

    def test_read_falls_back_to_committed(self):
        """Reads fall back to committed data if key not staged."""
        memory = SharedMemory()
        memory.write("committed", "original")

        txn_id = memory.begin_transaction()
        assert memory.read("committed") == "original"
        memory.rollback_transaction(txn_id)

    def test_read_all_merges_staged_and_committed(self):
        """read_all() merges staged data with committed data."""
        memory = SharedMemory()
        memory.write("key1", "committed1")
        memory.write("key2", "committed2")

        txn_id = memory.begin_transaction()
        memory.write("key2", "staged2")
        memory.write("key3", "staged3")

        result = memory.read_all()
        assert result["key1"] == "committed1"
        assert result["key2"] == "staged2"
        assert result["key3"] == "staged3"

        memory.rollback_transaction(txn_id)


class TestNestedTransactions:
    """Tests for nested transaction behavior."""

    def test_nested_commit_merges_into_parent(self):
        """Nested transaction commit merges into parent, not main data."""
        memory = SharedMemory()

        outer = memory.begin_transaction()
        memory.write("outer_key", "outer_value")

        inner = memory.begin_transaction()
        memory.write("inner_key", "inner_value")
        memory.commit_transaction(inner)

        # Inner committed to parent, not main
        assert "inner_key" not in memory._data
        assert memory._staged_data[outer]["inner_key"] == "inner_value"

        memory.commit_transaction(outer)
        assert memory._data["outer_key"] == "outer_value"
        assert memory._data["inner_key"] == "inner_value"

    def test_nested_rollback_only_discards_inner(self):
        """Rolling back inner transaction preserves outer's writes."""
        memory = SharedMemory()

        outer = memory.begin_transaction()
        memory.write("outer", "preserved")

        inner = memory.begin_transaction()
        memory.write("inner", "discarded")
        memory.rollback_transaction(inner)

        memory.commit_transaction(outer)
        assert memory._data["outer"] == "preserved"
        assert "inner" not in memory._data


class TestAsyncWrites:
    """Tests for async write behavior with transactions."""

    @pytest.mark.asyncio
    async def test_write_async_respects_transaction(self):
        """write_async stages data when transaction is active."""
        memory = SharedMemory()
        txn_id = memory.begin_transaction()

        await memory.write_async("async_key", "async_value")

        assert "async_key" not in memory._data
        assert memory._staged_data[txn_id]["async_key"] == "async_value"

        memory.commit_transaction(txn_id)
        assert memory._data["async_key"] == "async_value"


class TestPermissionScopes:
    """Tests for scoped views and transaction sharing."""

    def test_scoped_view_shares_transaction(self):
        """with_permissions() creates view that shares transaction state."""
        memory = SharedMemory()
        txn_id = memory.begin_transaction()

        scoped = memory.with_permissions(["key1"], ["key1"])

        # Scoped view should see the same transaction
        assert scoped.has_active_transaction()
        assert scoped.get_current_transaction() == txn_id

        memory.rollback_transaction(txn_id)

    def test_scoped_writes_staged_in_shared_transaction(self):
        """Writes through scoped view are staged in shared transaction."""
        memory = SharedMemory()
        txn_id = memory.begin_transaction()

        scoped = memory.with_permissions(["key1"], ["key1"])
        scoped.write("key1", "scoped_value")

        # Both views should see the staged write
        assert memory.read("key1") == "scoped_value"
        assert scoped.read("key1") == "scoped_value"

        memory.commit_transaction(txn_id)
        assert memory._data["key1"] == "scoped_value"


class TestErrorHandling:
    """Tests for transaction error handling."""

    def test_commit_invalid_txn_raises(self):
        """Committing an invalid transaction ID raises ValueError."""
        memory = SharedMemory()
        with pytest.raises(ValueError, match="not active"):
            memory.commit_transaction("invalid_txn")

    def test_rollback_invalid_txn_raises(self):
        """Rolling back an invalid transaction ID raises ValueError."""
        memory = SharedMemory()
        with pytest.raises(ValueError, match="not active"):
            memory.rollback_transaction("invalid_txn")

    def test_double_commit_raises(self):
        """Committing the same transaction twice raises ValueError."""
        memory = SharedMemory()
        txn_id = memory.begin_transaction()
        memory.commit_transaction(txn_id)

        with pytest.raises(ValueError, match="not active"):
            memory.commit_transaction(txn_id)


class TestAsyncTransactionMethods:
    """Tests for async transaction methods with lock protection."""

    @pytest.mark.asyncio
    async def test_begin_transaction_async(self):
        """begin_transaction_async creates unique transaction IDs."""
        memory = SharedMemory()
        txn1 = await memory.begin_transaction_async()
        await memory.commit_transaction_async(txn1)
        txn2 = await memory.begin_transaction_async()

        assert txn1 != txn2
        assert txn1.startswith("txn_")

    @pytest.mark.asyncio
    async def test_commit_transaction_async(self):
        """commit_transaction_async commits staged data."""
        memory = SharedMemory()
        txn_id = await memory.begin_transaction_async()
        memory.write("key", "value")
        await memory.commit_transaction_async(txn_id)

        assert memory._data["key"] == "value"

    @pytest.mark.asyncio
    async def test_rollback_transaction_async(self):
        """rollback_transaction_async discards staged data."""
        memory = SharedMemory()
        txn_id = await memory.begin_transaction_async()
        memory.write("key", "value")
        await memory.rollback_transaction_async(txn_id)

        assert "key" not in memory._data


class TestCleanupOrphanedTransactions:
    """Tests for cleanup_orphaned_transactions method."""

    def test_cleanup_returns_count(self):
        """cleanup_orphaned_transactions returns number of orphaned transactions."""
        memory = SharedMemory()
        memory.begin_transaction()
        memory.begin_transaction()

        count = memory.cleanup_orphaned_transactions()

        assert count == 2
        assert not memory.has_active_transaction()

    def test_cleanup_clears_staged_data(self):
        """cleanup_orphaned_transactions clears all staged data."""
        memory = SharedMemory()
        memory.begin_transaction()
        memory.write("key", "value")

        memory.cleanup_orphaned_transactions()

        assert len(memory._staged_data) == 0
        assert len(memory._transaction_stack) == 0

    def test_cleanup_no_orphans_returns_zero(self):
        """cleanup_orphaned_transactions returns 0 when no orphans exist."""
        memory = SharedMemory()
        count = memory.cleanup_orphaned_transactions()
        assert count == 0


class TestMutableCounterSharing:
    """Tests for counter sharing across scoped views."""

    def test_scoped_views_share_counter(self):
        """Scoped views share the mutable counter."""
        memory = SharedMemory()
        scoped = memory.with_permissions(["key"], ["key"])

        txn1 = memory.begin_transaction()
        memory.commit_transaction(txn1)
        txn2 = scoped.begin_transaction()

        # IDs should be different because they share the counter
        assert txn1 != txn2
        assert txn1 == "txn_0"
        assert txn2 == "txn_1"


class TestTransactionMetrics:
    """Tests for transaction metrics tracking."""

    def test_metrics_track_commits(self):
        """get_transaction_metrics tracks commits."""
        memory = SharedMemory()
        txn_id = memory.begin_transaction()
        memory.commit_transaction(txn_id)

        metrics = memory.get_transaction_metrics()
        assert metrics["total_commits"] == 1
        assert metrics["total_rollbacks"] == 0
        assert metrics["active_count"] == 0

    def test_metrics_track_rollbacks(self):
        """get_transaction_metrics tracks rollbacks."""
        memory = SharedMemory()
        txn_id = memory.begin_transaction()
        memory.rollback_transaction(txn_id)

        metrics = memory.get_transaction_metrics()
        assert metrics["total_commits"] == 0
        assert metrics["total_rollbacks"] == 1

    def test_metrics_track_active_count(self):
        """get_transaction_metrics tracks active transactions."""
        memory = SharedMemory()
        memory.begin_transaction()
        memory.begin_transaction()

        metrics = memory.get_transaction_metrics()
        assert metrics["active_count"] == 2


class TestContextManager:
    """Tests for TransactionContext context manager."""

    def test_context_manager_auto_commits(self):
        """Context manager auto-commits on success."""
        memory = SharedMemory()

        with memory.transaction() as txn:
            memory.write("key", "value")
            assert txn.txn_id is not None

        assert memory._data["key"] == "value"
        assert memory.get_transaction_metrics()["total_commits"] == 1

    def test_context_manager_auto_rollbacks_on_exception(self):
        """Context manager auto-rollbacks on exception."""
        memory = SharedMemory()

        with pytest.raises(ValueError):
            with memory.transaction():
                memory.write("key", "value")
                raise ValueError("Test error")

        assert "key" not in memory._data
        assert memory.get_transaction_metrics()["total_rollbacks"] == 1

    def test_context_manager_mark_rollback(self):
        """Context manager respects mark_rollback()."""
        memory = SharedMemory()

        with memory.transaction() as txn:
            memory.write("key", "value")
            txn.mark_rollback()

        assert "key" not in memory._data
        assert memory.get_transaction_metrics()["total_rollbacks"] == 1
