"""Shared memory helpers for queen/worker recall and reflection.

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
import shutil
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MEMORY_TYPES: tuple[str, ...] = ("goal", "environment", "technique", "reference", "diary")
GLOBAL_MEMORY_CATEGORIES: tuple[str, ...] = ("profile", "preference", "environment", "feedback")

_HIVE_QUEEN_DIR = Path.home() / ".hive" / "queen"
# Legacy shared v2 root.  Colony memory now lives under queen sessions.
MEMORY_DIR: Path = _HIVE_QUEEN_DIR / "memories"
CURSOR_FILE: Path = MEMORY_DIR / ".cursor.json"

MAX_FILES: int = 200
MAX_FILE_SIZE_BYTES: int = 4096  # 4 KB hard limit per memory file

# How many lines of a memory file to read for header scanning.
_HEADER_LINE_LIMIT: int = 30
_MIGRATION_MARKER = ".migrated-from-shared-memory"
_GLOBAL_MEMORY_CODE_PATTERN = re.compile(
    r"(/Users/|~/.hive|\.py\b|\.ts\b|\.tsx\b|\.js\b|"
    r"\b(graph|node|runtime|session|execution|worker|queen|subagent|checkpoint|flowchart)\b)",
    re.IGNORECASE,
)

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


def colony_memory_dir(colony_id: str) -> Path:
    """Return the colony memory directory for a queen session."""
    return _HIVE_QUEEN_DIR / "session" / colony_id / "memory" / "colony"


def global_memory_dir() -> Path:
    """Return the queen-global memory directory."""
    return _HIVE_QUEEN_DIR / "global_memory"


def queen_colony_cursor_file(session_dir: Path) -> Path:
    """Return the queen colony cursor file for a session."""
    return session_dir / "memory" / "cursors" / "queen-colony.cursor.json"


def queen_global_cursor_file(session_dir: Path) -> Path:
    """Return the queen global cursor file for a session."""
    return session_dir / "memory" / "cursors" / "queen-global.cursor.json"


def worker_colony_cursor_file(worker_session_dir: Path) -> Path:
    """Return the worker colony cursor file for one top-level execution."""
    return worker_session_dir / "memory" / "worker-colony.cursor.json"


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
    """Validate *raw* against supported memory categories."""
    if raw is None:
        return None
    normalized = raw.strip().lower()
    allowed = set(MEMORY_TYPES) | set(GLOBAL_MEMORY_CATEGORIES)
    return normalized if normalized in allowed else None


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


def diary_filename(d: date | None = None) -> str:
    """Return the diary memory filename for date *d* (default: today)."""
    d = d or date.today()
    return f"MEMORY-{d.strftime('%Y-%m-%d')}.md"


def build_diary_document(*, date_str: str, body: str) -> str:
    """Build a diary memory file with frontmatter."""
    return build_memory_document(
        name=f"diary-{date_str}",
        description=f"Daily session narrative for {date_str}",
        mem_type="diary",
        body=body,
    )


def validate_global_memory_payload(
    *,
    category: str,
    description: str,
    content: str,
) -> str:
    """Validate a queen-global memory save request."""
    parsed = parse_global_memory_category(category)
    if parsed is None:
        raise ValueError(
            "Invalid global memory category. Use one of: "
            + ", ".join(GLOBAL_MEMORY_CATEGORIES)
        )
    if not description.strip():
        raise ValueError("Global memory description cannot be empty.")
    if not content.strip():
        raise ValueError("Global memory content cannot be empty.")

    probe = f"{description}\n{content}"
    if _GLOBAL_MEMORY_CODE_PATTERN.search(probe):
        raise ValueError(
            "Global memory is only for durable user profile, preferences, "
            "environment, or feedback — not task/code/runtime details."
        )
    return parsed


def save_global_memory(
    *,
    category: str,
    description: str,
    content: str,
    name: str | None = None,
    memory_dir: Path | None = None,
) -> tuple[str, Path]:
    """Persist one queen-global memory entry."""
    parsed = validate_global_memory_payload(
        category=category,
        description=description,
        content=content,
    )
    target_dir = memory_dir or global_memory_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    memory_name = (name or description).strip()
    filename = allocate_memory_filename(target_dir, memory_name)
    doc = build_memory_document(
        name=memory_name,
        description=description,
        mem_type=parsed,
        body=content,
    )
    if len(doc.encode("utf-8")) > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"Global memory entry exceeds the {MAX_FILE_SIZE_BYTES} byte limit."
        )
    path = target_dir / filename
    path.write_text(doc, encoding="utf-8")
    return filename, path


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


def init_memory_dir(
    memory_dir: Path | None = None,
    *,
    migrate_legacy: bool = False,
) -> None:
    """Create the memory directory if missing.

    When ``migrate_legacy`` is true, migrate both v1 memory files and the
    previous shared v2 queen memory store into this directory.
    """
    d = memory_dir or MEMORY_DIR
    first_run = not d.exists()
    d.mkdir(parents=True, exist_ok=True)
    if migrate_legacy:
        migrate_legacy_memories(d)
        migrate_shared_v2_memories(d)
    elif first_run and d == MEMORY_DIR:
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
                mem_type="diary",
                description=f"Migrated diary entry from {date_part}",
                body=content,
            )
            migrated_any = True
            # Archive original.
            legacy_archive.mkdir(parents=True, exist_ok=True)
            ep_file.rename(legacy_archive / ep_file.name)

    if migrated_any:
        logger.info("queen_memory_v2: migrated legacy memory files to %s", d)


def migrate_shared_v2_memories(
    memory_dir: Path | None = None,
    *,
    source_dir: Path | None = None,
) -> None:
    """Move shared queen v2 memory files into a colony directory once."""
    d = memory_dir or MEMORY_DIR
    d.mkdir(parents=True, exist_ok=True)
    src = source_dir or MEMORY_DIR
    if d.resolve() == src.resolve():
        return

    marker = d / _MIGRATION_MARKER
    if marker.exists():
        return

    if not src.is_dir():
        return

    md_files = sorted(
        f for f in src.glob("*.md")
        if f.is_file() and not f.name.startswith(".")
    )
    if not md_files:
        marker.write_text("no shared memories found\n", encoding="utf-8")
        return

    archive = src / ".legacy_colony_migration"
    archive.mkdir(parents=True, exist_ok=True)
    migrated_any = False

    for src_file in md_files:
        target = d / src_file.name
        if not target.exists():
            try:
                shutil.copy2(src_file, target)
                migrated_any = True
            except OSError:
                logger.debug("shared memory migration copy failed for %s", src_file, exc_info=True)
                continue

        archived = archive / src_file.name
        counter = 2
        while archived.exists():
            archived = archive / f"{src_file.stem}-{counter}{src_file.suffix}"
            counter += 1
        try:
            src_file.rename(archived)
        except OSError:
            logger.debug("shared memory migration archive failed for %s", src_file, exc_info=True)

    if migrated_any:
        logger.info("queen_memory_v2: migrated shared queen memories to %s", d)
    marker.write_text(
        f"migrated_at={int(time.time())}\nsource={src}\n",
        encoding="utf-8",
    )


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
