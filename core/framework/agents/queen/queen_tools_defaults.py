"""Role-based default tool allowlists for queens.

Every queen inherits the same MCP surface (all servers loaded for the
queen agent), but exposing 94+ tools to every persona clutters the LLM
tool catalog and wastes prompt tokens. This module defines a sensible
default allowlist per queen persona so, e.g., Head of Legal doesn't
see port scanners and Head of Finance doesn't see ``apply_patch``.

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
    # Read-only file operations — safe baseline for every knowledge queen.
    "file_read": [
        "read_file",
        "list_directory",
        "list_dir",
        "list_files",
        "search_files",
        "grep_search",
        "pdf_read",
    ],
    # File mutation — only personas that author or edit artifacts.
    "file_write": [
        "write_file",
        "edit_file",
        "apply_diff",
        "apply_patch",
        "replace_file_content",
        "hashline_edit",
        "undo_changes",
    ],
    # Shell + process control — engineering personas only.
    "shell": [
        "run_command",
        "execute_command_tool",
        "bash_kill",
        "bash_output",
    ],
    # Tabular data. CSV/Excel read/write + DuckDB SQL.
    "data": [
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
    # Browser automation — every tool from the gcu-tools MCP server.
    "browser": ["@server:gcu-tools"],
    # External research / information-gathering.
    "research": [
        "search_papers",
        "download_paper",
        "search_wikipedia",
        "web_scrape",
    ],
    # Security scanners — pentest-ish, only for engineering/security roles.
    "security": [
        "dns_security_scan",
        "http_headers_scan",
        "port_scan",
        "ssl_tls_scan",
        "subdomain_enumerate",
        "tech_stack_detect",
        "risk_score",
    ],
    # Lightweight context helpers — good default for every queen.
    "time_context": [
        "get_current_time",
        "get_account_info",
    ],
    # Runtime log inspection — debug/observability for builder personas.
    "runtime_inspection": [
        "query_runtime_logs",
        "query_runtime_log_details",
        "query_runtime_log_raw",
    ],
    # Agent-management tools — building/validating/checking agents.
    "agent_mgmt": [
        "list_agents",
        "list_agent_tools",
        "list_agent_sessions",
        "get_agent_checkpoint",
        "list_agent_checkpoints",
        "run_agent_tests",
        "save_agent_draft",
        "confirm_and_build",
        "validate_agent_package",
        "validate_agent_tools",
        "enqueue_task",
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
    # Head of Technology — builds and operates systems; full toolkit.
    "queen_technology": [
        "file_read",
        "file_write",
        "shell",
        "data",
        "browser",
        "research",
        "security",
        "time_context",
        "runtime_inspection",
        "agent_mgmt",
    ],
    # Head of Growth — data, experiments, competitor research; no shell/security.
    "queen_growth": [
        "file_read",
        "file_write",
        "data",
        "browser",
        "research",
        "time_context",
    ],
    # Head of Product Strategy — user research + roadmaps; no shell/security.
    "queen_product_strategy": [
        "file_read",
        "file_write",
        "data",
        "browser",
        "research",
        "time_context",
    ],
    # Head of Finance — financial models (CSV/Excel heavy), market research.
    "queen_finance_fundraising": [
        "file_read",
        "file_write",
        "data",
        "browser",
        "research",
        "time_context",
    ],
    # Head of Legal — reads contracts/PDFs, researches; no shell/data/security.
    "queen_legal": [
        "file_read",
        "file_write",
        "browser",
        "research",
        "time_context",
    ],
    # Head of Brand & Design — visual refs, style guides; no shell/data/security.
    "queen_brand_design": [
        "file_read",
        "file_write",
        "browser",
        "research",
        "time_context",
    ],
    # Head of Talent — candidate pipelines, resumes; data + browser heavy.
    "queen_talent": [
        "file_read",
        "file_write",
        "data",
        "browser",
        "research",
        "time_context",
    ],
    # Head of Operations — processes, automation, observability.
    "queen_operations": [
        "file_read",
        "file_write",
        "data",
        "browser",
        "research",
        "time_context",
        "runtime_inspection",
        "agent_mgmt",
    ],
}


def has_role_default(queen_id: str) -> bool:
    """Return True when ``queen_id`` is known to the category table."""
    return queen_id in QUEEN_DEFAULT_CATEGORIES


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
