"""Queen global memory helpers.

Memory hierarchy::

    ~/.hive/memories/
        global/              # shared across all queens and colonies
        colonies/{name}/     # colony-scoped memories
        agents/queens/{name}/ # queen-specific memories
        agents/{name}/       # per-worker-agent memories

Each memory is an individual ``.md`` file with optional YAML frontmatter
(name, type, description).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from framework.config import MEMORIES_DIR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GLOBAL_MEMORY_CATEGORIES: tuple[str, ...] = ("profile", "preference", "environment", "feedback")

MAX_FILES: int = 200
MAX_FILE_SIZE_BYTES: int = 4096  # 4 KB hard limit per memory file

# How many lines of a memory file to read for header scanning.
_HEADER_LINE_LIMIT: int = 30


def global_memory_dir() -> Path:
    """Return the global memory directory (shared across all queens/colonies)."""
    return MEMORIES_DIR / "global"


def colony_memory_dir(colony_name: str) -> Path:
    """Return the memory directory for a named colony."""
    return MEMORIES_DIR / "colonies" / colony_name


def queen_memory_dir(queen_name: str = "default") -> Path:
    """Return the memory directory for a named queen."""
    return MEMORIES_DIR / "agents" / "queens" / queen_name


def agent_memory_dir(agent_name: str) -> Path:
    """Return the memory directory for a worker agent."""
    return MEMORIES_DIR / "agents" / agent_name


# ---------------------------------------------------------------------------
# Frontmatter parsing (lenient)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def parse_frontmatter(text: str) -> dict[str, str]:
    """Extract YAML-ish frontmatter from *text*.

    Returns a dict of key-value pairs.  Never raises — returns ``{}`` on
    any parse failure.  Values are stripped strings; no nested structures.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    result: dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        colon = line.find(":")
        if colon < 1:
            continue
        key = line[:colon].strip().lower()
        val = line[colon + 1 :].strip()
        if val:
            result[key] = val
    return result


def parse_global_memory_category(raw: str | None) -> str | None:
    """Validate *raw* against ``GLOBAL_MEMORY_CATEGORIES``."""
    if raw is None:
        return None
    normalized = raw.strip().lower()
    return normalized if normalized in GLOBAL_MEMORY_CATEGORIES else None


# ---------------------------------------------------------------------------
# MemoryFile dataclass
# ---------------------------------------------------------------------------


@dataclass
class MemoryFile:
    """Parsed representation of a single memory file on disk."""

    filename: str
    path: Path
    # Frontmatter fields — all nullable (lenient parsing).
    name: str | None = None
    type: str | None = None
    description: str | None = None
    # First N lines of the file (for manifest / header scanning).
    header_lines: list[str] = field(default_factory=list)
    # Filesystem modification time (seconds since epoch).
    mtime: float = 0.0

    @classmethod
    def from_path(cls, path: Path) -> MemoryFile:
        """Read a memory file and leniently parse its frontmatter."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return cls(filename=path.name, path=path)

        fm = parse_frontmatter(text)
        lines = text.splitlines()[:_HEADER_LINE_LIMIT]

        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0

        return cls(
            filename=path.name,
            path=path,
            name=fm.get("name"),
            type=parse_global_memory_category(fm.get("type")),
            description=fm.get("description"),
            header_lines=lines,
            mtime=mtime,
        )


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def scan_memory_files(memory_dir: Path | None = None) -> list[MemoryFile]:
    """Scan *memory_dir* for ``.md`` files, returning up to ``MAX_FILES``.

    Files are sorted by modification time (newest first).  Dotfiles and
    subdirectories are ignored.
    """
    d = memory_dir or global_memory_dir()
    if not d.is_dir():
        return []

    md_files = sorted(
        (f for f in d.glob("*.md") if f.is_file() and not f.name.startswith(".")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    return [MemoryFile.from_path(f) for f in md_files[:MAX_FILES]]


def slugify_memory_name(raw: str) -> str:
    """Create a filesystem-safe slug for a memory filename."""
    slug = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    return slug or "memory"


def allocate_memory_filename(
    memory_dir: Path,
    name: str,
    *,
    suffix: str = ".md",
) -> str:
    """Allocate a unique filename in *memory_dir* based on *name*."""
    base = slugify_memory_name(name)
    candidate = f"{base}{suffix}"
    counter = 2
    while (memory_dir / candidate).exists():
        candidate = f"{base}-{counter}{suffix}"
        counter += 1
    return candidate


def build_memory_document(
    *,
    name: str,
    description: str,
    mem_type: str,
    body: str,
) -> str:
    """Build one memory file with frontmatter and body."""
    return (
        f"---\n"
        f"name: {name.strip()}\n"
        f"description: {description.strip()}\n"
        f"type: {mem_type.strip()}\n"
        f"---\n\n"
        f"{body.strip()}\n"
    )


# ---------------------------------------------------------------------------
# Manifest formatting
# ---------------------------------------------------------------------------


def format_memory_manifest(files: list[MemoryFile]) -> str:
    """One-line-per-file text manifest.

    Format: ``[type] filename: description``
    """
    lines: list[str] = []
    for mf in files:
        t = mf.type or "unknown"
        desc = mf.description or "(no description)"
        lines.append(f"[{t}] {mf.filename}: {desc}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init_memory_dir(memory_dir: Path | None = None) -> None:
    """Create the memory directory if missing."""
    d = memory_dir or global_memory_dir()
    d.mkdir(parents=True, exist_ok=True)
