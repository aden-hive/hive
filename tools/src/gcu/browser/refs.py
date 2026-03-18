"""Ref system for aria snapshots.

Assigns short `[ref=eN]` markers to interactive elements in Playwright's
aria_snapshot() output so the LLM can reference elements by ref instead of
constructing fragile CSS selectors.

Usage:
    annotated, ref_map = annotate_snapshot(raw_snapshot)
    # ... later, when the LLM says selector="e5" ...
    playwright_selector = resolve_ref("e5", ref_map)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session import BrowserSession

# ---------------------------------------------------------------------------
# Role sets (matching Playwright's aria roles that matter for interaction)
# ---------------------------------------------------------------------------

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
        "scrollbar",
        "searchbox",
        "slider",
        "spinbutton",
        "switch",
        "tab",
        "textbox",
        "treeitem",
    }
)

NAMED_CONTENT_ROLES: frozenset[str] = frozenset(
    {
        "cell",
        "heading",
        "img",
    }
)

# Regex: captures indent, role, optional quoted name, and trailing text.
# Example line:  "  - button \"Submit\" [disabled]"
#   group(1)=indent "  ", group(2)=role "button",
#   group(3)=name "Submit" (or None), group(4)=rest " [disabled]"
_LINE_RE = re.compile(r"^(\s*-\s+)(\w+)(?:\s+\"([^\"]*)\")?(.*?)$")

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RefEntry:
    """A single ref entry mapping to a Playwright role selector."""

    role: str
    name: str | None
    nth: int


# ref_id (e.g. "e0") -> RefEntry
RefMap = dict[str, RefEntry]

# ---------------------------------------------------------------------------
# annotate_snapshot
# ---------------------------------------------------------------------------


def annotate_snapshot(snapshot: str) -> tuple[str, RefMap]:
    """Inject ``[ref=eN]`` markers into an aria snapshot.

    Returns:
        (annotated_text, ref_map) where ref_map maps ref ids to RefEntry.
    """
    lines = snapshot.split("\n")

    # First pass: identify which lines get refs and count (role, name) pairs
    # for nth disambiguation.
    candidates: list[tuple[int, str, str | None]] = []  # (line_idx, role, name)
    pair_counts: dict[tuple[str, str | None], int] = {}

    for i, line in enumerate(lines):
        m = _LINE_RE.match(line)
        if not m:
            continue
        role = m.group(2)
        name = m.group(3)  # None if no quoted name

        if role in INTERACTIVE_ROLES or (role in NAMED_CONTENT_ROLES and name):
            candidates.append((i, role, name))
            key = (role, name)
            pair_counts[key] = pair_counts.get(key, 0) + 1

    # Second pass: assign refs with nth indices.
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

        # Inject [ref=eN] at end of line (before any trailing whitespace)
        lines[line_idx] = lines[line_idx].rstrip() + f" [ref={ref_id}]"

    return "\n".join(lines), ref_map


# ---------------------------------------------------------------------------
# resolve_ref
# ---------------------------------------------------------------------------

_REF_PATTERN = re.compile(r"^e\d+$")


def resolve_ref(selector: str, ref_map: RefMap | None) -> str:
    """Resolve a ref id (e.g. ``"e5"``) to a Playwright role selector.

    If *selector* doesn't look like a ref (``e\\d+``), it's returned as-is
    so that plain CSS selectors keep working.

    Raises:
        ValueError: If the ref is not found or no snapshot has been taken.
    """
    if not _REF_PATTERN.match(selector):
        return selector  # Pass through CSS / XPath / role selectors

    if ref_map is None:
        raise ValueError(
            f"Ref '{selector}' used but no snapshot has been taken yet. "
            "Call browser_snapshot first."
        )

    entry = ref_map.get(selector)
    if entry is None:
        valid = ", ".join(sorted(ref_map.keys(), key=lambda k: int(k[1:])))
        raise ValueError(
            f"Ref '{selector}' not found. Valid refs: {valid}. "
            "The page may have changed — take a new snapshot."
        )

    # Build Playwright role selector
    if entry.name is not None:
        escaped_name = entry.name.replace("\\", "\\\\").replace('"', '\\"')
        sel = f'role={entry.role}[name="{escaped_name}"]'
    else:
        sel = f"role={entry.role}"

    # Always include nth to disambiguate
    sel += f" >> nth={entry.nth}"
    return sel


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------


def resolve_selector(
    selector: str,
    session: BrowserSession,
    target_id: str | None,
) -> str:
    """Resolve a selector that might be a ref, using the session's ref maps.

    Args:
        selector: A CSS selector or ref id (e.g. ``"e5"``).
        session: The current BrowserSession.
        target_id: The target page id (falls back to session.active_page_id).
    """
    tid = target_id or session.active_page_id
    ref_map = session.ref_maps.get(tid) if tid else None
    return resolve_ref(selector, ref_map)
