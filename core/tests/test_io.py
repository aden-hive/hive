import threading
import time
from pathlib import Path

from framework.utils.io import atomic_write


def test_atomic_write_concurrent_reader(tmp_path: Path):
    target = tmp_path / "checkpoint.json"
    target.write_text("original", encoding="utf-8")

    # To simulate a concurrent reader, we open the file and keep it open.
    # On Windows, this will cause a PermissionError during replace.
    # We want to test that atomic_write retries and eventually succeeds
    # if the reader closes the file within the retry window.

    reader = open(target, encoding="utf-8")

    # Use a background thread to close the reader after a short delay
    # The atomic_write should retry and succeed once this thread closes the handle.
    def close_reader():
        time.sleep(0.05)
        reader.close()

    t = threading.Thread(target=close_reader)
    t.start()

    with atomic_write(target) as f:
        f.write("new content")

    t.join()
    assert target.read_text(encoding="utf-8") == "new content"
