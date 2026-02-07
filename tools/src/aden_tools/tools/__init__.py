"""
Aden Tools - Tool implementations for FastMCP.

Usage:
    from fastmcp import FastMCP
    from aden_tools.tools import register_all_tools
    from aden_tools.credentials import CredentialStoreAdapter

    mcp = FastMCP("my-server")
    credentials = CredentialStoreAdapter.default()
    register_all_tools(mcp, credentials=credentials)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

# Import register_tools from each tool module
from .apollo_tool import register_tools as register_apollo
from .csv_tool import register_tools as register_csv
from .email_tool import register_tools as register_email
from .example_tool import register_tools as register_example
from .file_system_toolkits.apply_diff import register_tools as register_apply_diff
from .file_system_toolkits.apply_patch import register_tools as register_apply_patch
from .file_system_toolkits.data_tools import register_tools as register_data_tools
from .file_system_toolkits.execute_command_tool import (
    register_tools as register_execute_command,
)
from .file_system_toolkits.grep_search import register_tools as register_grep_search
from .file_system_toolkits.list_dir import register_tools as register_list_dir
from .file_system_toolkits.replace_file_content import (
    register_tools as register_replace_file_content,
)

# Import file system toolkits
from .file_system_toolkits.view_file import register_tools as register_view_file
from .file_system_toolkits.write_to_file import register_tools as register_write_to_file
from .github_tool import register_tools as register_github
from .hubspot_tool import register_tools as register_hubspot
from .pdf_read_tool import register_tools as register_pdf_read
from .runtime_logs_tool import register_tools as register_runtime_logs
from .slack_tool import register_tools as register_slack
from .web_scrape_tool import register_tools as register_web_scrape
from .web_search_tool import register_tools as register_web_search


def register_all_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> list[str]:
    """
    Register all tools with a FastMCP server.

    Args:
        mcp: FastMCP server instance
        credentials: Optional CredentialStoreAdapter instance.
                     If not provided, tools fall back to direct os.getenv() calls.

    Returns:
        List of registered tool names
    """
    # Tools that don't need credentials
    register_example(mcp)
    register_web_scrape(mcp)
    register_pdf_read(mcp)
    register_runtime_logs(mcp)

    # Tools that need credentials (pass credentials if provided)
    # web_search supports multiple providers (Google, Brave) with auto-detection
    register_web_search(mcp, credentials=credentials)
    register_github(mcp, credentials=credentials)
    # email supports multiple providers (Resend) with auto-detection
    register_email(mcp, credentials=credentials)
    register_hubspot(mcp, credentials=credentials)
    register_apollo(mcp, credentials=credentials)
    register_slack(mcp, credentials=credentials)

    # Register file system toolkits
    register_view_file(mcp)
    register_write_to_file(mcp)
    register_list_dir(mcp)
    register_replace_file_content(mcp)
    register_apply_diff(mcp)
    register_apply_patch(mcp)
    register_grep_search(mcp)
    register_execute_command(mcp)
    register_data_tools(mcp)
    register_csv(mcp)

    return [
        "example_tool",
        "web_search",
        "web_scrape",
        "pdf_read",
        "view_file",
        "write_to_file",
        "list_dir",
        "replace_file_content",
        "apply_diff",
        "apply_patch",
        "grep_search",
        "execute_command_tool",
        "load_data",
        "save_data",
        "list_data_files",
        "serve_file_to_user",
        "csv_read",
        "csv_write",
        "csv_append",
        "csv_info",
        "csv_sql",
        "apollo_enrich_person",
        "apollo_enrich_company",
        "apollo_search_people",
        "apollo_search_companies",
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
        "send_email",
        "send_budget_alert_email",
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
        "query_runtime_logs",
        "query_runtime_log_details",
        "query_runtime_log_raw",
        "slack_send_message",
        "slack_list_channels",
        "slack_get_channel_history",
        "slack_add_reaction",
        "slack_get_user_info",
        "slack_update_message",
        "slack_delete_message",
        "slack_schedule_message",
        "slack_create_channel",
        "slack_archive_channel",
        "slack_invite_to_channel",
        "slack_set_channel_topic",
        "slack_remove_reaction",
        "slack_list_users",
        "slack_upload_file",
        # Advanced Slack tools
        "slack_search_messages",
        "slack_get_thread_replies",
        "slack_pin_message",
        "slack_unpin_message",
        "slack_list_pins",
        "slack_add_bookmark",
        "slack_list_scheduled_messages",
        "slack_delete_scheduled_message",
        "slack_send_dm",
        "slack_get_permalink",
        "slack_send_ephemeral",
        # Block Kit & Views
        "slack_post_blocks",
        "slack_open_modal",
        "slack_update_home_tab",
        # Phase 2: User Status & Presence
        "slack_set_status",
        "slack_set_presence",
        "slack_get_presence",
        # Phase 2: Reminders
        "slack_create_reminder",
        "slack_list_reminders",
        "slack_delete_reminder",
        # Phase 2: User Groups
        "slack_create_usergroup",
        "slack_update_usergroup_members",
        "slack_list_usergroups",
        # Phase 2: Emoji
        "slack_list_emoji",
        # Phase 2: Canvas
        "slack_create_canvas",
        "slack_edit_canvas",
        # Phase 2: Analytics (AI-Driven)
        "slack_get_messages_for_analysis",
        # Phase 2: Workflow
        "slack_trigger_workflow",
        # Phase 3: Critical Power Tools
        "slack_get_conversation_context",
        "slack_find_user_by_email",
        "slack_kick_user_from_channel",
        "slack_delete_file",
        "slack_get_team_stats",
    ]


__all__ = ["register_all_tools"]
