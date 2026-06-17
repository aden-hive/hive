from unittest.mock import MagicMock, patch
from pathlib import Path
import logging
from framework.orchestrator.node_worker import NodeWorker
from framework.orchestrator.node import NodeSpec

def test_node_worker_spillover_exception_logging(caplog):
    # Setup NodeSpec and mock GraphContext
    node_spec = NodeSpec(id="test_node", name="Test Node", description="Test description", node_type="task", output_keys=["large_key"])
    gc = MagicMock()
    
    # Configure GraphContext mocks
    gc.storage_path = Path("/some/path")
    gc.buffer.read_all.return_value = {
        "large_key": "x" * 500  # Longer than 300 characters
    }
    
    # Instantiate worker
    worker = NodeWorker(node_spec=node_spec, graph_context=gc)
    
    # Mock Path methods to raise an error during write_text
    with patch.object(Path, "mkdir"), \
         patch.object(Path, "write_text", side_effect=PermissionError("Permission denied")), \
         caplog.at_level(logging.WARNING):
         
        buffer_items, data_files = worker._prepare_transition_payload()
        
        # Verify fallback logic works (truncating to 300 chars + "...")
        assert "large_key" in buffer_items
        assert buffer_items["large_key"] == "x" * 300 + "..."
        
        # Verify warning is logged with correct details
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "WARNING"
        assert "failed to spill buffer key 'large_key'" in record.message
        assert record.exc_info is not None
