"""
Tests for framework.blocks (building blocks registry).
"""

import pytest

from framework.blocks import BlockSpec, get_block, list_blocks


class TestBlocksRegistry:
    """Tests for block registry."""

    def test_list_blocks_returns_all(self):
        blocks = list_blocks()
        assert len(blocks) >= 3
        ids = {b.id for b in blocks}
        assert "retry_default" in ids
        assert "approval_required" in ids
        assert "validation_default" in ids

    def test_list_blocks_filter_by_category(self):
        retry_blocks = list_blocks(category="retry")
        assert len(retry_blocks) >= 1
        assert all(b.category == "retry" for b in retry_blocks)

        approval_blocks = list_blocks(category="approval")
        assert len(approval_blocks) >= 1
        assert all(b.category == "approval" for b in approval_blocks)

        validation_blocks = list_blocks(category="validation")
        assert len(validation_blocks) >= 1
        assert all(b.category == "validation" for b in validation_blocks)

    def test_get_block_returns_block(self):
        b = get_block("retry_default")
        assert b is not None
        assert b.id == "retry_default"
        assert b.category == "retry"
        assert "max_retries" in b.delta

    def test_get_block_unknown_returns_none(self):
        assert get_block("nonexistent_block") is None

    def test_retry_default_delta(self):
        b = get_block("retry_default")
        assert b.delta["max_retries"] == 3
        assert b.delta["retry_on"] == []

    def test_approval_required_delta(self):
        b = get_block("approval_required")
        assert b.delta["pause_for_hitl"] is True
        assert "approval_message" in b.delta

    def test_apply_to_node_dict_merges_delta(self):
        b = get_block("retry_default")
        node_data = {"id": "test-node", "max_retries": 1}
        out = b.apply_to_node_dict(node_data)
        assert out["max_retries"] == 3
        assert out["id"] == "test-node"

    def test_apply_to_node_dict_with_overrides(self):
        b = get_block("retry_default")
        node_data = {"id": "test-node"}
        out = b.apply_to_node_dict(node_data, overrides={"max_retries": 5})
        assert out["max_retries"] == 5
