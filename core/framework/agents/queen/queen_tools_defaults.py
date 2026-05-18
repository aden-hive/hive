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
        # System memory — regex search across the queen's own message history
        # (across sessions). In-scope content: user text, assistant prose,
        # and tool result bodies. Never includes tool names, tool inputs,
        # reasoning, finish reasons, token counts, or timestamps.
        "search_messages",
    ],
    # BI / financial chart + diagram rendering. Calling chart_render
    # both embeds the chart live in chat and produces a downloadable PNG.
    "charts": [
        "@server:chart-tools",
    ],
    # ----- OAuth-bound categories ------------------------------------
    # These tools require an OAuth provider connection (Google, GitHub,
    # HubSpot, Notion, Slack). They are listed in the Library catalog
    # regardless of whether the provider is currently authorized — the
    # UI shows a greyed-out checkbox + Connect button when not — and
    # are filtered out of the worker prompt at spawn time if the
    # provider has no live account. New OAuth tools added under each
    # provider here will auto-light up once the user authorizes.
    "email_oauth": [
        "send_email",
        "gmail_list_messages",
        "gmail_get_message",
        "gmail_create_draft",
        "gmail_reply_email",
        "gmail_modify_message",
        "gmail_trash_message",
        "gmail_create_label",
        "gmail_list_labels",
        "gmail_batch_get_messages",
        "gmail_batch_modify_messages",
    ],
    "calendar_oauth": [
        "calendar_list_calendars",
        "calendar_get_calendar",
        "calendar_list_events",
        "calendar_get_event",
        "calendar_create_event",
        "calendar_update_event",
        "calendar_delete_event",
        "calendar_check_availability",
    ],
    "google_workspace": [
        "google_docs_create_document",
        "google_docs_get_document",
        "google_docs_insert_text",
        "google_docs_format_text",
        "google_docs_replace_all_text",
        "google_docs_batch_update",
        "google_docs_insert_image",
        "google_docs_create_list",
        "google_docs_add_comment",
        "google_docs_list_comments",
        "google_docs_export_content",
        "google_sheets_create_spreadsheet",
        "google_sheets_get_spreadsheet",
        "google_sheets_get_values",
        "google_sheets_update_values",
        "google_sheets_append_values",
        "google_sheets_clear_values",
        "google_sheets_batch_update_values",
        "google_sheets_batch_clear_values",
        "google_sheets_add_sheet",
        "google_sheets_delete_sheet",
    ],
    "github_oauth": [
        "github_list_repos",
        "github_get_repo",
        "github_search_repos",
        "github_list_issues",
        "github_get_issue",
        "github_create_issue",
        "github_update_issue",
        "github_list_pull_requests",
        "github_get_pull_request",
        "github_create_pull_request",
        "github_search_code",
        "github_list_branches",
        "github_get_branch",
        "github_list_stargazers",
        "github_get_user_profile",
        "github_get_user_emails",
        "github_list_commits",
        "github_create_release",
        "github_list_workflow_runs",
    ],
    "hubspot_oauth": [
        "hubspot_search_contacts",
        "hubspot_get_contact",
        "hubspot_create_contact",
        "hubspot_update_contact",
        "hubspot_search_companies",
        "hubspot_get_company",
        "hubspot_create_company",
        "hubspot_update_company",
        "hubspot_search_deals",
        "hubspot_get_deal",
        "hubspot_create_deal",
        "hubspot_update_deal",
        "hubspot_delete_object",
        "hubspot_list_associations",
        "hubspot_create_association",
    ],
    "notion_oauth": [
        "notion_search",
        "notion_get_page",
        "notion_create_page",
        "notion_update_page",
        "notion_query_database",
        "notion_get_database",
        "notion_create_database",
        "notion_update_database",
        "notion_get_block_children",
        "notion_get_block",
        "notion_update_block",
        "notion_delete_block",
        "notion_append_blocks",
    ],
    # Slack is currently "Coming soon" in the desktop integrations UI,
    # but queens still get the category — the per-spawn credential
    # filter drops the tools until the provider is connected, so when
    # Slack ships the queens auto-light up without any sidecar churn.
    "slack_oauth": [
        "slack_send_message",
        "slack_list_channels",
        "slack_get_channel_history",
        "slack_get_channel_info",
        "slack_list_users",
        "slack_get_user_info",
        "slack_find_user_by_email",
        "slack_send_dm",
        "slack_search_messages",
        "slack_get_thread_replies",
        "slack_get_messages_for_analysis",
        "slack_get_conversation_context",
        "slack_update_message",
        "slack_delete_message",
        "slack_schedule_message",
        "slack_add_reaction",
        "slack_remove_reaction",
        "slack_pin_message",
        "slack_unpin_message",
        "slack_upload_file",
        "slack_get_permalink",
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
    # actually needs reconnaissance. OAuth-bound categories (email,
    # github, slack, …) are likewise opt-in: defining them implicitly
    # would either spam the prompt with disconnected tools the worker
    # can't actually call, or — once authorized — expose data sources
    # the user never asked the queen to touch. Users add OAuth
    # categories per-queen via the Tool Library.
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
    # Head of Marketing — positioning, content, competitor research, campaign
    # performance. Charts included for funnel/audience reporting; no security.
    "queen_marketing": [
        "file_ops",
        "terminal_basic",
        "browser_basic",
        "browser_interaction",
        "research",
        "context_awareness",
        "charts",
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


def _credentialed_tool_names() -> set[str]:
    """Return the set of MCP tool names that are bound to an OAuth provider.

    Reads the credential adapter so the answer reflects every provider
    declared in ``CREDENTIAL_SPECS`` (Gmail, GitHub, Notion, …) without
    needing the live MCP catalog. Falls back to an empty set if
    ``aden_tools`` is unavailable so the rest of the resolver keeps
    working in stripped-down test environments.
    """
    try:
        from aden_tools.credentials.store_adapter import CredentialStoreAdapter

        return {name for name, provider in CredentialStoreAdapter.default().get_tool_provider_map().items() if provider}
    except Exception:
        logger.debug("Provider map unavailable for default-tools filter", exc_info=True)
        return set()


def resolve_queen_default_tools(
    queen_id: str,
    mcp_catalog: dict[str, list[dict[str, Any]]] | None = None,
) -> list[str] | None:
    """Return the role-based default allowlist for ``queen_id``.

    Arguments:
        queen_id: Profile ID (e.g. ``"queen_technology"``).
        mcp_catalog: Optional mapping of ``{server_name: [{"name": ...}, ...]}``
            used to expand ``@server:NAME`` shorthands in categories AND
            to enumerate credential-less tools for the unknown-queen
            fallback. When absent, shorthand entries are dropped and the
            unknown-queen fallback returns ``None`` (legacy "allow all").

    Returns:
        A deduplicated list of tool names. OAuth-credentialed tools are
        always excluded from the default — for known queens because
        none of the role categories contain them, for unknown queens
        because the unknown-queen fallback (when given a catalog)
        explicitly drops every name with a provider. Users opt OAuth
        tools in per-queen via the Tool Library; that save writes a
        sidecar which then takes precedence over this function.

        Returns ``None`` only when the queen is unknown AND no catalog
        was supplied — preserving the legacy "allow every MCP tool"
        path for environments that can't enumerate the catalog.
    """
    credentialed = _credentialed_tool_names()
    categories = QUEEN_DEFAULT_CATEGORIES.get(queen_id)
    if not categories:
        # Unknown queen — fall back to "every credential-less MCP tool"
        # when we have a catalog to enumerate from. Without a catalog
        # there's nothing to filter against, so preserve the legacy
        # ``None`` (allow-all) so we don't accidentally lock the queen
        # out of every tool in stripped-down boot paths.
        if mcp_catalog is None:
            return None
        names: list[str] = []
        seen: set[str] = set()
        for entries in mcp_catalog.values():
            for tool in entries or []:
                tname = tool.get("name") if isinstance(tool, dict) else None
                if not tname or tname in seen:
                    continue
                if tname in credentialed:
                    continue
                seen.add(tname)
                names.append(tname)
        return names

    names = []
    seen = set()

    def _add(name: str) -> None:
        if not name or name in seen:
            return
        # Belt-and-braces: even if a category accidentally references a
        # credentialed tool (e.g. via ``@server:hive_tools`` picking up
        # gmail_*), drop it from the default. OAuth tools are opt-in
        # everywhere — users add them per-queen via the Tool Library.
        if name in credentialed:
            return
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
