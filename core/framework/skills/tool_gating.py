"""Tool-gated pre-activation of default skills.

Maps tool-name prefixes to default skills whose full body should be
injected into the system prompt whenever a matching tool is available
to the agent. This sidesteps progressive disclosure for skills that are
foundational to a tool family — the agent shouldn't have to discover
them reactively after its first broken selector call.

Only the foundation skill (e.g. ``hive.browser-automation``) is wired
in here. Site-specific skills (``hive.x-automation``,
``hive.linkedin-automation``) stay in the catalog and rely on their
descriptions to get picked up on demand.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_SKILLS_DIR = Path(__file__).parent / "_default_skills"

# (tool-name prefix, default skill directory name, display name)
_TOOL_GATED_SKILLS: list[tuple[str, str, str]] = [
    ("browser_", "browser-automation", "hive.browser-automation"),
]

_BODY_CACHE: dict[str, str] = {}


def _load_body(dir_name: str) -> str:
    """Load the markdown body of a framework default skill, cached."""
    if dir_name in _BODY_CACHE:
        return _BODY_CACHE[dir_name]

    path = _DEFAULT_SKILLS_DIR / dir_name / "SKILL.md"
    body = ""
    try:
        raw = path.read_text(encoding="utf-8")
        # Strip YAML frontmatter (between the first two '---' fences)
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                body = parts[2].strip()
            else:
                body = raw.strip()
        else:
            body = raw.strip()
    except OSError as exc:
        logger.warning("Failed to read tool-gated skill '%s': %s", dir_name, exc)

    _BODY_CACHE[dir_name] = body
    return body


def augment_catalog_for_tools(
    base_catalog_prompt: str,
    tool_names: Iterable[str],
) -> str:
    """Return the catalog prompt with tool-gated skill bodies appended.

    For each entry in ``_TOOL_GATED_SKILLS`` whose prefix matches any
    name in ``tool_names``, appends the skill's full body as a
    ``--- Pre-Activated Skill: <name> ---`` block. When no tool-gated
    skill matches, returns ``base_catalog_prompt`` unchanged.
    """
    names = {str(name) for name in tool_names if name}
    if not names:
        return base_catalog_prompt

    blocks: list[str] = []
    for prefix, dir_name, display in _TOOL_GATED_SKILLS:
        if not any(n.startswith(prefix) for n in names):
            continue
        body = _load_body(dir_name)
        if not body:
            continue
        blocks.append(f"--- Pre-Activated Skill: {display} ---\n{body}")

    if not blocks:
        return base_catalog_prompt

    suffix = "\n\n".join(blocks)
    if not base_catalog_prompt:
        return suffix
    return f"{base_catalog_prompt}\n\n{suffix}"
