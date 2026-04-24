"""Shared skill authoring primitives.

Validates and materializes a skill folder. Used by three callers:

1. Queen's ``create_colony`` tool (``queen_lifecycle_tools.py``) — inline
   content passed by the queen during colony creation.
2. HTTP POST / PUT routes under ``/api/**/skills`` — UI-driven creation.
3. Future ``create_learned_skill`` tool — runtime learning.

Keeping the validators and writer here ensures the three paths share one
authority; changes to the name regex or frontmatter layout happen in one
place.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Framework skill names include dots (``hive.note-taking``), so the
# validator needs to allow them even though the queen's ``create_colony``
# tool historically forbade dots. User-created skills without dots still
# pass; the dot cap just prevents us from rejecting existing framework
# names when the UI toggles them via ``validate_skill_name``.
_SKILL_NAME_RE = re.compile(r"^[a-z0-9.-]+$")
_MAX_NAME_LEN = 64
_MAX_DESC_LEN = 1024


@dataclass
class SkillFile:
    """Supporting file bundled with a skill (relative path + content)."""

    rel_path: Path
    content: str


@dataclass
class SkillDraft:
    """Validated skill content ready to be written to disk."""

    name: str
    description: str
    body: str
    files: list[SkillFile] = field(default_factory=list)

    @property
    def skill_md_text(self) -> str:
        """Assemble the final SKILL.md text (frontmatter + body)."""
        body_norm = self.body.rstrip() + "\n"
        return f"---\nname: {self.name}\ndescription: {self.description}\n---\n\n{body_norm}"


def validate_skill_name(raw: str) -> tuple[str | None, str | None]:
    """Return ``(normalized_name, error)``. Either side may be None."""
    name = (raw or "").strip() if isinstance(raw, str) else ""
    if not name:
        return None, "skill_name is required"
    if not _SKILL_NAME_RE.match(name):
        return None, f"skill_name '{name}' must match [a-z0-9-] pattern"
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return None, f"skill_name '{name}' has leading/trailing/consecutive hyphens"
    if len(name) > _MAX_NAME_LEN:
        return None, f"skill_name '{name}' exceeds {_MAX_NAME_LEN} chars"
    return name, None


def validate_description(raw: str) -> tuple[str | None, str | None]:
    desc = (raw or "").strip() if isinstance(raw, str) else ""
    if not desc:
        return None, "skill_description is required"
    if len(desc) > _MAX_DESC_LEN:
        return None, f"skill_description must be 1–{_MAX_DESC_LEN} chars"
    # Frontmatter descriptions are line-oriented — the parser reads one value.
    if "\n" in desc or "\r" in desc:
        return None, "skill_description must be a single line (no newlines)"
    return desc, None


def validate_files(raw: list[dict] | None) -> tuple[list[SkillFile] | None, str | None]:
    if not raw:
        return [], None
    if not isinstance(raw, list):
        return None, "skill_files must be an array"
    out: list[SkillFile] = []
    for entry in raw:
        if not isinstance(entry, dict):
            return None, "each skill_files entry must be an object with 'path' and 'content'"
        rel_raw = entry.get("path")
        content = entry.get("content")
        if not isinstance(rel_raw, str) or not rel_raw.strip():
            return None, "skill_files entry missing non-empty 'path'"
        if not isinstance(content, str):
            return None, f"skill_files entry '{rel_raw}' missing string 'content'"
        rel_stripped = rel_raw.strip()
        # Allow './foo' but reject '/foo' — relativizing absolute paths silently
        # has bitten other tools; make the intent loud instead.
        if rel_stripped.startswith("./"):
            rel_stripped = rel_stripped[2:]
        rel_path = Path(rel_stripped)
        if rel_stripped.startswith("/") or rel_path.is_absolute() or ".." in rel_path.parts:
            return None, f"skill_files path '{rel_raw}' must be relative and inside the skill folder"
        if rel_path.as_posix() == "SKILL.md":
            return None, "skill_files must not contain SKILL.md — pass skill_body instead"
        out.append(SkillFile(rel_path=rel_path, content=content))
    return out, None


def build_draft(
    *,
    skill_name: str,
    skill_description: str,
    skill_body: str,
    skill_files: list[dict] | None = None,
) -> tuple[SkillDraft | None, str | None]:
    """Validate all inputs and return an immutable draft ready for writing."""
    name, err = validate_skill_name(skill_name)
    if err or name is None:
        return None, err
    desc, err = validate_description(skill_description)
    if err or desc is None:
        return None, err
    body = skill_body if isinstance(skill_body, str) else ""
    if not body.strip():
        return None, (
            "skill_body is required — the operational procedure the colony worker needs to run this job unattended"
        )
    files, err = validate_files(skill_files)
    if err or files is None:
        return None, err
    return SkillDraft(name=name, description=desc, body=body, files=list(files)), None


def write_skill(
    draft: SkillDraft,
    *,
    target_root: Path,
    replace_existing: bool = True,
) -> tuple[Path | None, str | None, bool]:
    """Write the draft under ``target_root/{draft.name}/``.

    ``target_root`` is the parent scope dir (e.g.
    ``~/.hive/agents/queens/{id}/skills`` or
    ``{colony_dir}/.hive/skills``). The function creates it if needed.

    Returns ``(installed_path, error, replaced)``. On success ``error`` is
    ``None``; on failure ``installed_path`` is ``None`` and the target is
    left as it was before the call (best-effort).

    When ``replace_existing=False`` and the target dir already exists,
    the write is refused with a non-fatal error (caller decides whether
    to surface it as a 409 or a warning).
    """
    try:
        target_root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return None, f"failed to create skills root: {e}", False

    target = target_root / draft.name
    replaced = False
    try:
        if target.exists():
            if not replace_existing:
                return None, f"skill '{draft.name}' already exists", False
            # Remove the old dir outright so stale files from a prior
            # version don't linger alongside the new ones.
            replaced = True
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=False)
        (target / "SKILL.md").write_text(draft.skill_md_text, encoding="utf-8")
        for sf in draft.files:
            full_path = target / sf.rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(sf.content, encoding="utf-8")
    except OSError as e:
        return None, f"failed to write skill folder {target}: {e}", replaced
    return target, None, replaced


def remove_skill(target_root: Path, skill_name: str) -> tuple[bool, str | None]:
    """Rm-tree the skill directory under ``target_root/{skill_name}/``.

    Returns ``(removed, error)``. ``removed=False, error=None`` means
    the directory didn't exist (idempotent). Name is validated on the
    way in so an attacker with UI access can't traverse out of the
    scope root.
    """
    name, err = validate_skill_name(skill_name)
    if err or name is None:
        return False, err
    target = target_root / name
    if not target.exists():
        return False, None
    try:
        shutil.rmtree(target)
    except OSError as e:
        return False, f"failed to remove skill folder {target}: {e}"
    return True, None
