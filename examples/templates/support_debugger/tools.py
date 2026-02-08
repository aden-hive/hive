"""Reference tool implementations for Support Debugger Agent.

These are stub/mock tools that define the interface contract for the
investigation node. Each tool returns hardcoded reference data shaped
exactly like a real integration would.

To connect real backends, replace the function bodies while keeping
the signatures and return shapes identical.

Discovery: These tools are found by ToolRegistry.discover_from_module()
via the @tool decorator. Tool names must match NodeSpec.tools entries.
"""

from framework.runner.tool_registry import tool


@tool(description="Search the knowledge base and documentation for relevant articles")
def search_knowledge_base(query: str) -> dict:
    """Search product documentation and knowledge base articles.

    Args:
        query: Natural language search query derived from hypotheses.

    Returns:
        Dict with 'results' list of evidence items.
    """
    # Reference stub — replace with real vector search / docs API
    return {
        "results": [
            {
                "source_type": "docs",
                "source_id": "https://example.com/docs/configuration",
                "snippet": (
                    "The `framework_name` key must be explicitly set in the "
                    "configuration file for test execution and reporting to work."
                ),
                "metadata": {"section": "Configuration Reference"},
            }
        ],
        "query_used": query,
        "result_count": 1,
    }


@tool(
    description="Fetch resolved support tickets with similar issues from ticket history"
)
def fetch_ticket_history(keywords: str) -> dict:
    """Fetch previously resolved support tickets matching keywords.

    Args:
        keywords: Comma-separated keywords to search ticket history.

    Returns:
        Dict with 'tickets' list of matching historical tickets.
    """
    # Reference stub — replace with real Freshdesk / BigQuery integration
    return {
        "tickets": [
            {
                "source_type": "tickets",
                "source_id": "TICKET-1529418",
                "snippet": (
                    "Subject: Pytest execution ends immediately\n"
                    "Resolution: Root cause was missing framework_name in config file."
                ),
                "metadata": {
                    "status": "resolved",
                    "resolution_date": "2024-11-02",
                },
            }
        ],
        "query_used": keywords,
        "result_count": 1,
    }


@tool(description="Fetch runtime logs for a specific session or build")
def fetch_runtime_logs(session_id: str) -> dict:
    """Fetch runtime logs from the execution environment.

    Args:
        session_id: Session or build identifier to fetch logs for.

    Returns:
        Dict with 'logs' list of log evidence items.
    """
    # Reference stub — replace with real log aggregator integration
    return {
        "logs": [
            {
                "source_type": "logs",
                "source_id": session_id,
                "snippet": (
                    "ERROR webdriver_init: Failed to create remote session\n"
                    "ValueError: Missing required key 'framework_name' in config"
                ),
                "metadata": {"log_type": "selenium", "phase": "setup"},
            },
            {
                "source_type": "logs",
                "source_id": session_id,
                "snippet": (
                    "INFO pytest: Total tests collected: 19\n"
                    "INFO pytest: Aborting execution due to setup failure"
                ),
                "metadata": {"log_type": "pytest", "phase": "collection"},
            },
        ],
        "query_used": session_id,
        "result_count": 2,
    }
