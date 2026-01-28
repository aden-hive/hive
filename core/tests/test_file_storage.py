"""Tests for FileStorage backend concurrency."""

import shutil
import pytest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from framework.storage.backend import FileStorage

class TestFileStorageConcurrency:
    """Tests for FileStorage concurrency handling."""

    def test_concurrent_index_updates(self, tmp_path):
        """
        Test that concurrent updates to the same index do not cause data loss or corruption.
        
        This simulates multiple threads adding items to a single index file simultaneously.
        Without locking and atomic writes, this would fail.
        """
        storage = FileStorage(tmp_path)
        goal_id = "concurrent_goal"
        
        # Configuration
        num_threads = 10
        writes_per_thread = 10
        total_expected = num_threads * writes_per_thread
        
        def hammer_index(batch_ids):
            """Simulate concurrent writes."""
            # Use a new storage instance per thread to simulate real-world usage
            # (though they share the same base path)
            thread_storage = FileStorage(tmp_path)
            for run_id in batch_ids:
                # We access the private method to target the specific race condition
                # deeply, but in reality any public method updating the index would trigger it.
                thread_storage._add_to_index("by_goal", goal_id, run_id)

        # Generate run IDs
        all_batches = []
        for i in range(num_threads):
            batch = [f"run_{i}_{j}" for j in range(writes_per_thread)]
            all_batches.append(batch)

        # Run concurrent updates
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            list(executor.map(hammer_index, all_batches))
            
        # Verify results
        saved_ids = storage.get_runs_by_goal(goal_id)
        count = len(saved_ids)
        
        # Check for corruption (would have raised JSONDecodeError during get_runs_by_goal)
        # Check for data loss
        assert count == total_expected, f"Lost {total_expected - count} updates due to race condition"
        
        # Verify all IDs are present
        for batch in all_batches:
            for run_id in batch:
                assert run_id in saved_ids

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
