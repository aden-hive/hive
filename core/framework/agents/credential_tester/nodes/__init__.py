"""Node definitions for Credential Tester agent."""

from framework.graph import NodeSpec


def build_tester_node(
    provider: str,
    alias: str,
    tools: list[str],
    identity: dict[str, str],
) -> NodeSpec:
    """Build the tester node dynamically for the selected account.

    Args:
        provider: Aden provider name (e.g. "google", "slack").
        alias: User-set alias (e.g. "Timothy").
        tools: Tool names available for this provider.
        identity: Identity dict (email, workspace, etc.) for context.
    """
    detail_parts = [f"{k}: {v}" for k, v in identity.items() if v]
    detail = f" ({', '.join(detail_parts)})" if detail_parts else ""

    return NodeSpec(
        id="tester",
        name="Credential Tester",
        description=(
            f"Interactive testing node for {provider}/{alias}. "
            f"Has access to all {provider} tools to verify the credential works."
        ),
        node_type="event_loop",
        client_facing=True,
        max_node_visits=0,
        input_keys=[],
        output_keys=[],
        tools=tools,
        system_prompt=f"""\
You are a credential tester for the account: {provider}/{alias}{detail}

Your job is to help the user verify that this credential works by making \
real API calls using the available tools.

# Account routing

IMPORTANT: Always pass `account="{alias}"` when calling any tool. \
This routes the API call to the correct credential. Never use the email \
or any other identifier — always use the alias exactly as shown.

# Instructions

1. Start by greeting the user and confirming which account you're testing.
2. Suggest a simple, safe, read-only API call to verify the credential works \
(e.g. list messages, list channels, list contacts).
3. Execute the call when the user agrees.
4. Report the result clearly: success (with sample data) or failure (with error).
5. Let the user request additional API calls to further test the credential.

# Available tools

You have access to {len(tools)} tools for {provider}:
{chr(10).join(f"- {t}" for t in tools)}

# Rules

- Start with read-only operations (list, get) before write operations (create, update, delete).
- Always confirm with the user before performing write operations.
- If a call fails, report the exact error — this helps diagnose credential issues.
- Be concise. No emojis.
""",
    )
