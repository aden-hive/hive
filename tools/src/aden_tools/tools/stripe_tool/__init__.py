from fastmcp import FastMCP
from .stripe_tool import get_customer_by_email, get_subscription_status, create_payment_link

def register_tools(mcp: FastMCP):
    """Registers Stripe tools with the MCP server."""
    mcp.tool()(get_customer_by_email)
    mcp.tool()(get_subscription_status)
    mcp.tool()(create_payment_link)

__all__ = [
    "register_tools",
    "get_customer_by_email",
    "get_subscription_status", 
    "create_payment_link"
]