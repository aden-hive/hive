"""Role-based default tool allowlists for queens.

Every queen inherits the same MCP surface (all servers loaded for the
queen agent), but exposing 94+ tools to every persona clutters the LLM
tool catalog and wastes prompt tokens. This module defines a sensible
default allowlist per queen persona so, e.g., Head of Legal doesn't
see port scanners and Head of Brand & Design doesn't see CSV/SQL tools.

Defaults apply only when the queen has no ``tools.json`` sidecar — the
moment the user saves an allowlist through the Tool Library, the
sidecar becomes authoritative. A DELETE on the tools endpoint removes
the sidecar and brings the queen back to her role default.

Category entries support a ``@server:NAME`` shorthand that expands to
every tool name registered against that MCP server in the current
catalog. This keeps the category table short and drift-free when new
tools are added (e.g. browser_* auto-joins the ``browser`` category).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Categories — reusable bundles of MCP tool names.
# ---------------------------------------------------------------------------
#
# Each category is a flat list of either concrete tool names or the
# ``@server:NAME`` shorthand. The shorthand expands to every tool the
# given MCP server currently exposes (requires a live catalog; when one
# is not available the shorthand is silently dropped so we fall back to
# the named entries only).

_TOOL_CATEGORIES: dict[str, list[str]] = {
    # Unified file ops — read, write, edit, search across the files-tools
    # MCP server (read_file, write_file, edit_file, search_files). pdf_read
    # lives in hive_tools so it's listed explicitly; without it queens
    # cannot read PDF documents by default.
    "file_ops": [
        "@server:files-tools",
        "pdf_read",
    ],
    # Terminal basic — the 3-tool subset queens get out of the box.
    #   terminal_exec — foreground command execution (Bash equivalent)
    #   terminal_rg   — ripgrep content search (Grep equivalent)
    #   terminal_find — glob/find file listing (Glob equivalent)
    "terminal_basic": [
        "terminal_exec",
        "terminal_rg",
        "terminal_find",
    ],
    # Terminal advanced — the power-user tools beyond the basics. Not in
    # any role default; opt in explicitly per-queen via the Tool Library.
    #   terminal_job_*   — background job lifecycle (start/manage/logs)
    #   terminal_output_get — fetch captured output from foreground exec
    #   terminal_pty_*   — persistent PTY sessions (open/run/close)
    "terminal_advanced": [
        "terminal_job_start",
        "terminal_job_manage",
        "terminal_job_logs",
        "terminal_output_get",
        "terminal_pty_open",
        "terminal_pty_run",
        "terminal_pty_close",
    ],
    # Tabular data. CSV/Excel read/write + DuckDB SQL.
    "spreadsheet_advanced": [
        "csv_read",
        "csv_info",
        "csv_write",
        "csv_append",
        "csv_sql",
        "excel_read",
        "excel_info",
        "excel_write",
        "excel_append",
        "excel_search",
        "excel_sheet_list",
        "excel_sql",
    ],
    # Browser lifecycle + read-only inspection (navigation, snapshots, query).
    # Split out from interaction so personas that only need to *observe* pages
    # (e.g. research, status checks) don't pull in click/type/drag/etc.
    "browser_basic": [
        "browser_setup",
        "browser_status",
        "browser_stop",
        "browser_tabs",
        "browser_open",
        "browser_close",
        "browser_activate_tab",
        "browser_navigate",
        "browser_go_back",
        "browser_go_forward",
        "browser_reload",
        "browser_screenshot",
        "browser_snapshot",
        "browser_html",
        "browser_console",
        "browser_evaluate",
        "browser_get_text",
        "browser_get_attribute",
        "browser_get_rect",
        "browser_shadow_query",
    ],
    # Browser interaction — anything that mutates page state (clicks, typing,
    # drag, scrolling, dialogs, file uploads). Pair with browser_basic for
    # full automation; omit for read-only personas.
    "browser_interaction": [
        "browser_click",
        "browser_click_coordinate",
        "browser_type",
        "browser_type_focused",
        "browser_press",
        "browser_press_at",
        "browser_hover",
        "browser_hover_coordinate",
        "browser_select",
        "browser_scroll",
        "browser_drag",
        "browser_wait",
        "browser_resize",
        "browser_upload",
    ],
    # Research — paper search, Wikipedia, ad-hoc web scrape. Pair with
    # browser_basic for richer site-by-site research; this category is the
    # lightweight always-available fallback.
    "research": ["web_scrape", "pdf_read"],
    # Security — defensive scanning and reconnaissance. Engineering-only
    # surface; the rest of the queens shouldn't see port scanners.
    "security": [
        "port_scan",
        "dns_security_scan",
        "http_headers_scan",
        "ssl_tls_scan",
        "subdomain_enumerate",
        "tech_stack_detect",
        "risk_score",
    ],
    # Lightweight context helpers — good default for every queen.
    "context_awareness": [
        "get_current_time",
        "get_account_info",
    ],
    # BI / financial chart + diagram rendering. Calling chart_render
    # both embeds the chart live in chat and produces a downloadable PNG.
    "charts": [
        "@server:chart-tools",
    ],
}


# ---------------------------------------------------------------------------
# Per-queen mapping.
# ---------------------------------------------------------------------------
#
# Built from the queen personas in ``queen_profiles.DEFAULT_QUEENS``. The
# goal is "just enough" — a queen should see tools she'd plausibly call
# for her stated role, nothing more. Users curate further via the Tool
# Library if they want.
#
# A queen whose ID is NOT in this map falls through to "allow every MCP
# tool" (the original behavior), which keeps the system compatible with
# user-added custom queen IDs that we don't know about.

QUEEN_DEFAULT_CATEGORIES: dict[str, list[str]] = {
    # Head of Technology — builds and operates systems. Security tools
    # (port_scan, subdomain_enumerate, etc.) are intentionally NOT in the
    # default — users opt in via the Tool Library when an engagement
    # actually needs reconnaissance.
    "queen_technology": [
        "file_ops",
        "terminal_basic",
        "browser_basic",
        "browser_interaction",
        "research",
        "context_awareness",
        "charts",
    ],
    # Head of Growth — data, experiments, competitor research; no security.
    "queen_growth": [
        "file_ops",
        "terminal_basic",
        "browser_basic",
        "browser_interaction",
        "research",
        "context_awareness",
        "charts",
    ],
    # Head of Product Strategy — user research + roadmaps; no security.
    "queen_product_strategy": [
        "file_ops",
        "terminal_basic",
        "browser_basic",
        "browser_interaction",
        "research",
        "context_awareness",
        "charts",
    ],
    # Head of Finance — financial models (CSV/Excel heavy), market research.
    "queen_finance_fundraising": [
        "file_ops",
        "terminal_basic",
        "spreadsheet_advanced",
        "browser_basic",
        "browser_interaction",
        "research",
        "context_awareness",
        "charts",
    ],
    # Head of Legal — reads contracts/PDFs, researches; no data/security.
    "queen_legal": [
        "file_ops",
        "terminal_basic",
        "browser_basic",
        "browser_interaction",
        "research",
        "context_awareness",
    ],
    # Head of Brand & Design — visual refs, style guides; no data/security.
    "queen_brand_design": [
        "file_ops",
        "terminal_basic",
        "browser_basic",
        "browser_interaction",
        "research",
        "context_awareness",
    ],
    # Head of Talent — candidate pipelines, resumes; data + browser heavy.
    "queen_talent": [
        "file_ops",
        "terminal_basic",
        "browser_basic",
        "browser_interaction",
        "research",
        "context_awareness",
    ],
    # Head of Operations — processes, automation, observability.
    "queen_operations": [
        "file_ops",
        "terminal_basic",
        "spreadsheet_advanced",
        "browser_basic",
        "browser_interaction",
        "context_awareness",
        "charts",
    ],
}


def has_role_default(queen_id: str) -> bool:
    """Return True when ``queen_id`` is known to the category table."""
    return queen_id in QUEEN_DEFAULT_CATEGORIES


def list_category_names() -> list[str]:
    """Return every category name defined in the table, in declaration order."""
    return list(_TOOL_CATEGORIES.keys())


def queen_role_categories(queen_id: str) -> list[str]:
    """Return the category names assigned to ``queen_id`` by role default.

    Returns an empty list for queens not in the persona table (they fall
    through to allow-all and have no implicit category membership).
    """
    return list(QUEEN_DEFAULT_CATEGORIES.get(queen_id, []))


def resolve_category_tools(
    category: str,
    mcp_catalog: dict[str, list[dict[str, Any]]] | None = None,
) -> list[str]:
    """Expand a single category to its concrete tool names.

    Mirrors ``resolve_queen_default_tools`` but for a single category, so
    callers (e.g. the Tool Library API) can present per-category tool
    membership without re-implementing the ``@server:NAME`` shorthand
    expansion.
    """
    names: list[str] = []
    seen: set[str] = set()
    for entry in _TOOL_CATEGORIES.get(category, []):
        if entry.startswith("@server:"):
            server_name = entry[len("@server:") :]
            if mcp_catalog is None:
                continue
            for tool in mcp_catalog.get(server_name, []) or []:
                tname = tool.get("name") if isinstance(tool, dict) else None
                if tname and tname not in seen:
                    seen.add(tname)
                    names.append(tname)
        elif entry not in seen:
            seen.add(entry)
            names.append(entry)
    return names


def resolve_queen_default_tools(
    queen_id: str,
    mcp_catalog: dict[str, list[dict[str, Any]]] | None = None,
) -> list[str] | None:
    """Return the role-based default allowlist for ``queen_id``.

    Arguments:
        queen_id: Profile ID (e.g. ``"queen_technology"``).
        mcp_catalog: Optional mapping of ``{server_name: [{"name": ...}, ...]}``
            used to expand ``@server:NAME`` shorthands in categories.
            When absent, shorthand entries are dropped and the result
            contains only the explicitly-named tools.

    Returns:
        A deduplicated list of tool names, or ``None`` if the queen has
        no role entry (caller should treat as "allow every MCP tool").
    """
    categories = QUEEN_DEFAULT_CATEGORIES.get(queen_id)
    if not categories:
        return None

    names: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    for cat in categories:
        for entry in _TOOL_CATEGORIES.get(cat, []):
            if entry.startswith("@server:"):
                server_name = entry[len("@server:") :]
                if mcp_catalog is None:
                    logger.debug(
                        "resolve_queen_default_tools: catalog missing; cannot expand %s",
                        entry,
                    )
                    continue
                for tool in mcp_catalog.get(server_name, []) or []:
                    tname = tool.get("name") if isinstance(tool, dict) else None
                    if tname:
                        _add(tname)
            else:
                _add(entry)

    return names
