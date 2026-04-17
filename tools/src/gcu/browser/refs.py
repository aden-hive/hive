"""Ref system for selector resolution.

This module provides backward compatibility for selector resolution.
With bridge-based tools, selectors are passed directly to CDP methods.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session import BrowserSession

"""Shared ARIA role classification sets.

Keep these in sync across snapshot paths — divergence causes different
drivers to produce different snapshot output for the same page.
"""

# Roles that represent user-interactive elements and always get a ref.
INTERACTIVE_ROLES: frozenset[str] = frozenset(
    {
        "button",
        "checkbox",
        "combobox",
        "link",
        "listbox",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "option",
        "radio",
        "searchbox",
        "slider",
        "spinbutton",
        "switch",
        "tab",
        "textbox",
        "treeitem",
    }
)

# Roles that carry meaningful content and get a ref when named.
CONTENT_ROLES: frozenset[str] = frozenset(
    {
        "article",
        "cell",
        "columnheader",
        "gridcell",
        "heading",
        "listitem",
        "main",
        "navigation",
        "region",
        "rowheader",
    }
)

# Structural/container roles — typically skipped in compact mode.
STRUCTURAL_ROLES: frozenset[str] = frozenset(
    {
        "application",
        "directory",
        "document",
        "generic",
        "grid",
        "group",
        "ignored",
        "list",
        "menu",
        "menubar",
        "none",
        "presentation",
        "row",
        "rowgroup",
        "table",
        "tablist",
        "toolbar",
        "tree",
        "treegrid",
    }
)

# Regex for parsing aria snapshot lines
_LINE_RE = re.compile(r"^(\s*-\s+)(\w+)(?:\s+\"([^\"]*)\")?(.*?)$")

# Regex for detecting ref patterns
_REF_PATTERN = re.compile(r"^e\d+$")


@dataclass(frozen=True)
class RefEntry:
    """A single ref entry mapping to a CSS selector."""

    role: str
    name: str | None
    nth: int


# Type alias for ref maps
RefMap = dict[str, RefEntry]


def annotate_snapshot(snapshot: str) -> tuple[str, RefMap]:
    """Inject [ref=eN] markers into an aria snapshot.

    Returns:
        (annotated_text, ref_map) where ref_map maps ref ids to RefEntry.
    """
    lines = snapshot.split("\n")
    candidates: list[tuple[int, str, str | None]] = []

    for i, line in enumerate(lines):
        m = _LINE_RE.match(line)
        if not m:
            continue
        role = m.group(2)
        name = m.group(3)

        if role in INTERACTIVE_ROLES or (role in CONTENT_ROLES and name):
            candidates.append((i, role, name))

    ref_map: RefMap = {}
    pair_seen: dict[tuple[str, str | None], int] = {}
    ref_counter = 0

    for line_idx, role, name in candidates:
        key = (role, name)
        nth = pair_seen.get(key, 0)
        pair_seen[key] = nth + 1

        ref_id = f"e{ref_counter}"
        ref_counter += 1

        ref_map[ref_id] = RefEntry(role=role, name=name, nth=nth)
        lines[line_idx] = lines[line_idx].rstrip() + f" [ref={ref_id}]"

    return "\n".join(lines), ref_map


def resolve_ref(selector: str, ref_map: RefMap | None) -> str:
    """Resolve a ref id (e.g. "e5") to a CSS selector.

    If selector doesn't look like a ref (e\\d+), it's returned as-is
    so that plain CSS selectors keep working.

    Raises:
        ValueError: If the ref is not found or no snapshot has been taken.
    """
    if not _REF_PATTERN.match(selector):
        return selector

    if ref_map is None:
        raise ValueError(f"Ref '{selector}' used but no snapshot has been taken yet. Call browser_snapshot first.")

    entry = ref_map.get(selector)
    if entry is None:
        valid = ", ".join(sorted(ref_map.keys(), key=lambda k: int(k[1:])))
        raise ValueError(
            f"Ref '{selector}' not found. Valid refs: {valid}. The page may have changed - take a new snapshot."
        )

    # Build CSS selector
    if entry.name is not None:
        sel = f'[role="{entry.role}"][aria-label="{entry.name}"]'
    else:
        sel = f'[role="{entry.role}"]'

    return f"{sel}:nth-of-type({entry.nth + 1})"


def resolve_selector(
    selector: str,
    session: BrowserSession,
    target_id: str | None,
) -> str:
    """Resolve a selector that might be a ref.

    With bridge-based tools, this simply passes through the selector.
    Kept for backward compatibility with existing tool signatures.
    """
    return selector
