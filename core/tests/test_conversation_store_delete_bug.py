from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from framework.storage.conversation_store import FileConversationStore


@pytest.mark.asyncio
async def test_delete_parts_before_skips_non_numeric(tmp_path: Path) -> None:
    """Test that delete_parts_before doesn't crash on non-numeric filenames."""
    store = FileConversationStore(tmp_path / "conv")
    await store.write_part(0, {"seq": 0})
    await store.write_part(1, {"seq": 1})
    
    # Manually create a non-numeric json file in the parts dir
    parts_dir = tmp_path / "conv" / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    bad_file = parts_dir / "bad_file.json"
    bad_file.write_text("{}")
    
    # Should not crash
    await store.delete_parts_before(2)
    
    # Verify the remaining files
    parts = await store.read_parts()
    assert len(parts) == 1  # 0 and 1 are deleted, but bad_file is read as {}
    assert parts[0] == {}
    
    assert bad_file.exists()
