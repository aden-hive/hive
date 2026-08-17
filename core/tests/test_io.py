import sys
from pathlib import Path

import pytest

from framework.utils.io import atomic_write


@pytest.mark.skipif(sys.platform != "win32", reason="PermissionError lock scenario is Windows-specific")
def test_atomic_write_concurrent_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "checkpoint.json"
    target.write_text("original", encoding="utf-8")

    call_count = [0]
    original_replace = type(target).replace

    def mocked_replace(self, *args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise PermissionError(13, "Access is denied")
        return original_replace(self, *args, **kwargs)

    monkeypatch.setattr(type(target), "replace", mocked_replace)

    with atomic_write(target) as f:
        f.write("new content")

    assert call_count[0] == 2
    assert target.read_text(encoding="utf-8") == "new content"
