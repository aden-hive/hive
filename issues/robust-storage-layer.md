# Issue: Implement Robust, Atomic, and Concurrent Storage Layer

## Summary
The current `FileStorage` backend (`core/framework/storage/backend.py`) is suitable only for single-process, happy-path prototyping. It lacks file locking (concurrency safety) and atomic writes (crash safety). In a multi-agent or multi-process environment, this will lead to data corruption and index inconsistencies.

## Problem
1.  **Race Conditions**: `_add_to_index` performs a "read-modify-write" cycle on shared JSON index files. If two agents save their state simultaneously, one update will overwrite the other.
    ```python
    values = self._get_index(...)  # Read
    values.append(value)           # Modify
    with open(..., "w") ...        # Write (OVERWRITES interleaved updates)
    ```
2.  **No Atomicity**: Files are opened with `w`. If the process crashes mid-write (or disk is full), the file is left empty or corrupted.
3.  **Scalability**: Indexes like `by_status/completed.json` grow indefinitely and are fully rewritten on every run completion.

## Affected Code
*   `core/framework/storage/backend.py`

## Proposed Solution
Refactor `FileStorage` to be production-ready, or introduce a SQLite backend.

### Option A: Robust File Storage
1.  **Atomic Writes**: Write to a temporary file (e.g., `foo.json.tmp`), then use `os.replace()` to atomically rename it to `foo.json`.
2.  **File Locking**: Use a library like `portalocker` or standard `fcntl`/`msvcrt` locking to acquire an exclusive lock before the read-modify-write cycle on indexes.

### Option B: SQLite Backend (Recommended)
Replace the rigid directory-of-JSON-files structure with a single SQLite database.
*   **Atomicity & Concurrency**: SQLite handles locking and WAL (Write-Ahead Logging) automatically.
*   **Querying**: SQL queries replace the manual JSON indexes.
*   **Performance**: Exponentially faster for listing/filtering runs.

## Technical Details (SQLite Approach)
Create `core/framework/storage/sqlite.py`:
```python
class SQLiteStorage(StorageProtocol):
    def init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                goal_id TEXT,
                status TEXT,
                data JSON
            )
        """)
```

## Impact
*   **Data Integrity**: Prevents data loss during concurrent executions or crashes.
*   **Production Readiness**: Essential for deploying the framework in a real environment.
