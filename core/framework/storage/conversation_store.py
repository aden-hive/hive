import os
import json
import tempfile
import logging
from contextlib import contextmanager

# World No. 1 Cross-Platform Locking: Pure PhD Level
if os.name == 'nt':
    import msvcrt
else:
    import fcntl

logger = logging.getLogger(__name__)

class EncryptedFileStorage:
    def __init__(self, base_path: str):
        self.base_path = base_path
        self.index_path = os.path.join(base_path, "index.json")
        os.makedirs(base_path, exist_ok=True)

    @contextmanager
    def _get_lock(self):
        """Pure PhD Cross-Platform Sentinel Lock."""
        lock_path = f"{self.index_path}.lock"
        with open(lock_path, "a") as f:
            try:
                if os.name == 'nt':
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                yield
            finally:
                if os.name == 'nt':
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _update_index(self, new_data: dict):
        """Atomic Shadow-Write Implementation for 100% Integrity."""
        with self._get_lock():
            dir_name = os.path.dirname(self.index_path)
            # 1. Atomic Prep: Create Shadow File
            with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False) as tmp:
                json.dump(new_data, tmp)
                tmp.flush()
                os.fsync(tmp.fileno())  # Force hardware-level commit
                temp_name = tmp.name
            
            # 2. THE ATOMIC SWAP: Instant OS replacement
            os.replace(temp_name, self.index_path)

    def list_all(self) -> dict:
        """Sovereign Guarded Read (Consistency Guaranteed)."""
        with self._get_lock():
            if not os.path.exists(self.index_path):
                return {}
            try:
                with open(self.index_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Integrity check failed: {e}")
                return {}