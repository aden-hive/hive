"""Queen memory v2 — file-per-memory architecture.

Each memory is an individual ``.md`` file in ``~/.hive/queen/memories/``
with optional YAML frontmatter (name, type, description).  Frontmatter
is a convention enforced by prompt instructions — parsing is lenient and
malformed files degrade gracefully (appear in scans with ``None`` metadata).

Cursor-based incremental processing tracks which conversation messages
have already been processed by the reflection agent.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MEMORY_TYPES: tuple[str, ...] = ("goal", "environment", "technique", "reference")

_HIVE_QUEEN_DIR = Path.home() / ".hive" / "queen"
MEMORY_DIR: Path = _HIVE_QUEEN_DIR / "memories"
CURSOR_FILE: Path = MEMORY_DIR / ".cursor.json"

MAX_FILES: int = 200
MAX_FILE_SIZE_BYTES: int = 4096  # 4 KB hard limit per memory file

# How many lines of a memory file to read for header scanning.
_HEADER_LINE_LIMIT: int = 30

# Frontmatter example provided to the reflection agent via prompt.
MEMORY_FRONTMATTER_EXAMPLE: list[str] = [
    "```markdown",
    "---",
    "name: {{memory name}}",
    (
        "description: {{one-line description — used to decide "
        "relevance in future conversations, so be specific}}"
    ),
    f"type: {{{{{', '.join(MEMORY_TYPES)}}}}}",
    "---",
    "",
    (
        "{{memory content — for feedback/project types, "
        "structure as: rule/fact, then **Why:** "
        "and **How to apply:** lines}}"
    ),
    "```",
]


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


def parse_memory_type(raw: str | None) -> str | None:
    """Validate *raw* against ``MEMORY_TYPES``.  Falls back to ``None``."""
    if raw is None:
        return None
    normalized = raw.strip().lower()
    return normalized if normalized in MEMORY_TYPES else None


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
            type=parse_memory_type(fm.get("type")),
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
    d = memory_dir or MEMORY_DIR
    if not d.is_dir():
        return []

    md_files = sorted(
        (f for f in d.glob("*.md") if f.is_file() and not f.name.startswith(".")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    return [MemoryFile.from_path(f) for f in md_files[:MAX_FILES]]


# ---------------------------------------------------------------------------
# Manifest formatting
# ---------------------------------------------------------------------------

def _age_label(mtime: float) -> str:
    """Human-readable age string from an mtime."""
    age_days = memory_age_days(mtime)
    if age_days <= 0:
        return "today"
    if age_days == 1:
        return "1 day ago"
    return f"{age_days} days ago"


def format_memory_manifest(files: list[MemoryFile]) -> str:
    """One-line-per-file text manifest for the recall selector / reflection agent.

    Format: ``[type] filename (age): description``
    """
    lines: list[str] = []
    for mf in files:
        t = mf.type or "unknown"
        desc = mf.description or "(no description)"
        age = _age_label(mf.mtime)
        lines.append(f"[{t}] {mf.filename} ({age}): {desc}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Freshness / staleness
# ---------------------------------------------------------------------------

_SECONDS_PER_DAY = 86_400


def memory_age_days(mtime: float) -> int:
    """Return the age of a memory file in whole days."""
    if mtime <= 0:
        return 0
    return int((time.time() - mtime) / _SECONDS_PER_DAY)


def memory_freshness_text(mtime: float) -> str:
    """Return a staleness warning for injection, or empty string if fresh."""
    d = memory_age_days(mtime)
    if d <= 1:
        return ""
    return (
        f"This memory is {d} days old. "
        "Memories are point-in-time observations, not live state — "
        "claims about code behavior or file:line citations may be outdated. "
        "Verify against current code before asserting as fact."
    )


# ---------------------------------------------------------------------------
# Cursor-based incremental processing
# ---------------------------------------------------------------------------


def read_cursor(cursor_file: Path | None = None) -> int:
    """Read ``lastMemoryMessageSeq`` from the cursor file.  Returns 0 if missing."""
    p = cursor_file or CURSOR_FILE
    if not p.exists():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return int(data.get("lastMemoryMessageSeq", 0))
    except (json.JSONDecodeError, TypeError, ValueError, OSError):
        return 0


def write_cursor(seq: int, cursor_file: Path | None = None) -> None:
    """Persist the cursor seq number.  Creates parent dirs if needed."""
    p = cursor_file or CURSOR_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"lastMemoryMessageSeq": seq}),
        encoding="utf-8",
    )


def read_messages_since_cursor(
    session_dir: Path,
    cursor_seq: int,
) -> tuple[list[dict[str, Any]], int]:
    """Read conversation parts added since *cursor_seq*.

    Returns ``(messages, max_seq)``.  Each message is the raw JSON dict
    from the part file.

    **Compaction fallback**: if no files have ``seq > cursor_seq`` (the
    cursor was evicted by compaction), all existing parts are returned so
    that the reflection agent can still process visible messages.
    """
    parts_dir = session_dir / "conversations" / "parts"
    if not parts_dir.is_dir():
        return [], cursor_seq

    part_files = sorted(parts_dir.glob("*.json"))
    if not part_files:
        return [], cursor_seq

    # Determine which files are new (seq > cursor_seq).
    new_files: list[tuple[int, Path]] = []
    all_files: list[tuple[int, Path]] = []
    for f in part_files:
        try:
            seq = int(f.stem)
        except ValueError:
            continue
        all_files.append((seq, f))
        if seq > cursor_seq:
            new_files.append((seq, f))

    # Compaction fallback: cursor evicted → return everything visible.
    # Only trigger when cursor_seq is beyond the max seq of existing files,
    # meaning files were compacted away.  If cursor_seq <= max_all_seq there
    # is simply nothing new (already up-to-date) — returning empty is correct.
    if not new_files and all_files:
        max_all_seq = max(seq for seq, _ in all_files)
        if cursor_seq > max_all_seq:
            new_files = all_files

    if not new_files:
        return [], cursor_seq

    messages: list[dict[str, Any]] = []
    max_seq = cursor_seq
    for seq, f in new_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            messages.append(data)
            if seq > max_seq:
                max_seq = seq
        except (json.JSONDecodeError, OSError):
            continue

    return messages, max_seq


# ---------------------------------------------------------------------------
# Initialisation and legacy migration
# ---------------------------------------------------------------------------


def init_memory_dir(memory_dir: Path | None = None) -> None:
    """Create the memory directory if missing.  Migrates legacy files on first run."""
    d = memory_dir or MEMORY_DIR
    first_run = not d.exists()
    d.mkdir(parents=True, exist_ok=True)
    if first_run:
        migrate_legacy_memories(d)


def migrate_legacy_memories(memory_dir: Path | None = None) -> None:
    """Convert old MEMORY.md + MEMORY-YYYY-MM-DD.md files to individual memory files.

    Originals are moved to ``{memory_dir}/.legacy/``.
    """
    d = memory_dir or MEMORY_DIR
    queen_dir = _HIVE_QUEEN_DIR
    legacy_archive = d / ".legacy"

    migrated_any = False

    # --- Semantic memory (MEMORY.md) ---
    semantic = queen_dir / "MEMORY.md"
    if semantic.exists():
        content = semantic.read_text(encoding="utf-8").strip()
        # Skip the blank seed template.
        if content and not content.startswith("# My Understanding of the User\n\n*No sessions"):
            _write_migration_file(
                d,
                filename="legacy-semantic-memory.md",
                name="legacy-semantic-memory",
                mem_type="reference",
                description="Migrated semantic memory from previous memory system",
                body=content,
            )
            migrated_any = True
        # Archive original.
        legacy_archive.mkdir(parents=True, exist_ok=True)
        semantic.rename(legacy_archive / "MEMORY.md")

    # --- Episodic memories (MEMORY-YYYY-MM-DD.md) ---
    old_memories_dir = queen_dir / "memories"
    if old_memories_dir.is_dir():
        for ep_file in sorted(old_memories_dir.glob("MEMORY-*.md")):
            content = ep_file.read_text(encoding="utf-8").strip()
            if not content:
                continue
            date_part = ep_file.stem.replace("MEMORY-", "")
            slug = f"legacy-diary-{date_part}.md"
            _write_migration_file(
                d,
                filename=slug,
                name=f"legacy-diary-{date_part}",
                mem_type="reference",
                description=f"Migrated diary entry from {date_part}",
                body=content,
            )
            migrated_any = True
            # Archive original.
            legacy_archive.mkdir(parents=True, exist_ok=True)
            ep_file.rename(legacy_archive / ep_file.name)

    if migrated_any:
        logger.info("queen_memory_v2: migrated legacy memory files to %s", d)


def _write_migration_file(
    memory_dir: Path,
    filename: str,
    name: str,
    mem_type: str,
    description: str,
    body: str,
) -> None:
    """Write a single migrated memory file with frontmatter."""
    # Truncate body to respect file size limit (leave room for frontmatter).
    header = (
        f"---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"type: {mem_type}\n"
        f"---\n\n"
    )
    max_body = MAX_FILE_SIZE_BYTES - len(header.encode("utf-8"))
    if len(body.encode("utf-8")) > max_body:
        # Rough truncation — cut at character level then trim to last newline.
        body = body[: max_body - 20]
        nl = body.rfind("\n")
        if nl > 0:
            body = body[:nl]
        body += "\n\n...(truncated during migration)"

    path = memory_dir / filename
    path.write_text(header + body + "\n", encoding="utf-8")
