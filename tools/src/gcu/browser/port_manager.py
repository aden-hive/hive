"""
CDP port allocation for persistent browser profiles.

Manages port allocation in the range 18800-18899 for Chrome DevTools Protocol
debugging ports. Ports are persisted to disk for reuse across browser restarts.
"""

from __future__ import annotations

import logging
import os
import socket
from pathlib import Path

logger = logging.getLogger(__name__)

# Port range for CDP debugging
CDP_PORT_MIN = 18800
CDP_PORT_MAX = 18899

# Module-level registry of allocated ports (within this process)
_allocated_ports: set[int] = set()


def _is_port_available(port: int) -> bool:
    """Check if a port is available using socket bind probe."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def _get_port_file(profile: str, storage_path: Path | None) -> Path | None:
    """Get the path to the port file for a profile."""
    if storage_path is None:
        storage_path_str = os.environ.get("HIVE_STORAGE_PATH")
        if storage_path_str:
            storage_path = Path(storage_path_str)

    if storage_path:
        browser_dir = storage_path / "browser"
        browser_dir.mkdir(parents=True, exist_ok=True)
        return browser_dir / f"{profile}.port"

    return None


def allocate_port(profile: str, storage_path: Path | None = None) -> int:
    """
    Allocate a CDP port for a browser profile.

    First checks if a port is stored on disk for this profile (for reuse).
    If not, finds an available port in the range and stores it.

    Args:
        profile: Browser profile name
        storage_path: Base storage path (uses HIVE_STORAGE_PATH env if not provided)

    Returns:
        Allocated port number

    Raises:
        RuntimeError: If no ports are available in the range
    """
    port_file = _get_port_file(profile, storage_path)

    # Check for stored port
    if port_file and port_file.exists():
        try:
            stored_port = int(port_file.read_text().strip())
            if CDP_PORT_MIN <= stored_port <= CDP_PORT_MAX:
                if _is_port_available(stored_port):
                    _allocated_ports.add(stored_port)
                    logger.info(f"Reusing stored CDP port {stored_port} for profile '{profile}'")
                    return stored_port
        except (ValueError, OSError):
            pass  # Stored port invalid or unavailable

    # Find available port
    for port in range(CDP_PORT_MIN, CDP_PORT_MAX + 1):
        if port not in _allocated_ports and _is_port_available(port):
            _allocated_ports.add(port)
            logger.info(f"Allocated new CDP port {port} for profile '{profile}'")
            # Persist port assignment
            if port_file:
                try:
                    port_file.write_text(str(port))
                except OSError as e:
                    logger.warning(f"Failed to save port to file: {e}")
            return port

    raise RuntimeError(f"No available CDP ports in range {CDP_PORT_MIN}-{CDP_PORT_MAX}")


def release_port(port: int) -> None:
    """Release a previously allocated port."""
    _allocated_ports.discard(port)
