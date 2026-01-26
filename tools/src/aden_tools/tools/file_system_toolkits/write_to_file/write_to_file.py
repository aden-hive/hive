import os
import sys
import tempfile
import time
import threading
from mcp.server.fastmcp import FastMCP
from ..security import get_secure_path


# Module-level lock for atomic file operations on Windows
# Windows doesn't support truly atomic os.replace, so we serialize operations
_write_lock = threading.Lock()


# Cross-platform file locking for atomic append operations
if sys.platform == 'win32':
    # On Windows, use threading lock for simplicity as msvcrt only locks byte ranges
    def _lock_file(f):
        """Acquire exclusive lock using threading lock (Windows)."""
        _write_lock.acquire()
    def _unlock_file(f):
        """Release lock (Windows)."""
        try:
            _write_lock.release()
        except RuntimeError:
            pass  # Lock may already be released
else:
    import fcntl
    def _lock_file(f):
        """Acquire exclusive lock on file (POSIX)."""
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    def _unlock_file(f):
        """Release lock on file (POSIX)."""
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def register_tools(mcp: FastMCP) -> None:
    """Register file write tools with the MCP server."""

    @mcp.tool()
    def write_to_file(path: str, content: str, workspace_id: str, agent_id: str, session_id: str, append: bool = False) -> dict:
        """
        Purpose
            Create a new file or append content to an existing file.
            
        Atomicity
            Write operations use atomic patterns to prevent race conditions:
            - Write mode: temp file + atomic rename
            - Append mode: file locking

        When to use
            Append new events to append-only logs
            Create new artifacts or summaries
            Initialize new canonical memory files

        Rules & Constraints
            Must not overwrite canonical memory unless explicitly allowed
            Should include structured data (JSON, Markdown with headers)
            Every write must be intentional and minimal

        Anti-pattern
            Do NOT dump raw conversation transcripts without structure or reason.

        Args:
            path: The path to the file (relative to session root)
            content: The content to write to the file
            workspace_id: The ID of the workspace
            agent_id: The ID of the agent
            session_id: The ID of the current session
            append: Whether to append to the file instead of overwriting (default: False)

        Returns:
            Dict with success status and path, or error dict
        """
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)
            dir_path = os.path.dirname(secure_path)
            os.makedirs(dir_path, exist_ok=True)
            
            if append:
                # Append mode: use file locking to prevent interleaved writes
                with open(secure_path, "a", encoding="utf-8") as f:
                    _lock_file(f)
                    try:
                        f.write(content)
                        f.flush()
                        os.fsync(f.fileno())
                    finally:
                        _unlock_file(f)
            else:
                # Write mode: atomic temp file + rename to prevent partial writes
                # Use lock on Windows to serialize replace operations (not truly atomic)
                fd, temp_path = tempfile.mkstemp(dir=dir_path, prefix='.tmp_write_')
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as f:
                        f.write(content)
                        f.flush()
                        os.fsync(f.fileno())
                    
                    # Serialize the replace operation to avoid Windows race conditions
                    with _write_lock:
                        # Retry logic for Windows where replace can fail under contention
                        max_retries = 3
                        for attempt in range(max_retries):
                            try:
                                os.replace(temp_path, secure_path)
                                break
                            except PermissionError:
                                if attempt < max_retries - 1:
                                    time.sleep(0.01 * (attempt + 1))  # Brief backoff
                                else:
                                    raise
                except Exception:
                    # Clean up temp file on failure
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
                    raise
            
            return {
                "success": True,
                "path": path,
                "mode": "appended" if append else "written",
                "bytes_written": len(content.encode("utf-8"))
            }
        except Exception as e:
            return {"error": f"Failed to write to file: {str(e)}"}
