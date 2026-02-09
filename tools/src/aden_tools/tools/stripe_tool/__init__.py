from fastmcp import FastMCP
from .stripe_tool import (
    # Existing
    get_customer_by_email,
    get_subscription_status,
    create_payment_link,
    # New: Customer Management
    create_customer,
    update_customer,
    list_customers,
    get_customer_by_id,
    # New: Subscriptions
    create_subscription,
    update_subscription,
    cancel_subscription,
    list_subscriptions,
    # New: Invoices & Payments
    list_invoices,
    retrieve_invoice,
    pay_invoice,
    list_payment_intents,
    # New: Checkout & Webhooks
    create_checkout_session,
    verify_webhook_signature
)

def register_tools(mcp: FastMCP, credentials=None):
    """
    Registers all Stripe tools with the MCP server.
    Accepts an optional 'credentials' argument for compatibility.
    """
    # 1. Existing Tools
    mcp.tool(name="get_customer_by_email")(get_customer_by_email)
    mcp.tool(name="get_subscription_status")(get_subscription_status)
    mcp.tool(name="create_payment_link")(create_payment_link)

    # 2. New Customer Tools
    mcp.tool(name="create_customer")(create_customer)
    mcp.tool(name="update_customer")(update_customer)
    mcp.tool(name="list_customers")(list_customers)
    mcp.tool(name="get_customer_by_id")(get_customer_by_id)

    # 3. New Subscription Tools
    mcp.tool(name="create_subscription")(create_subscription)
    mcp.tool(name="update_subscription")(update_subscription)
    mcp.tool(name="cancel_subscription")(cancel_subscription)
    mcp.tool(name="list_subscriptions")(list_subscriptions)

    # 4. New Invoice/Payment Tools
    mcp.tool(name="list_invoices")(list_invoices)
    mcp.tool(name="retrieve_invoice")(retrieve_invoice)
    mcp.tool(name="pay_invoice")(pay_invoice)
    mcp.tool(name="list_payment_intents")(list_payment_intents)

    # 5. New Checkout/Webhook Tools
    mcp.tool(name="create_checkout_session")(create_checkout_session)
    mcp.tool(name="verify_webhook_signature")(verify_webhook_signature)

__all__ = [
    "register_tools",
    "get_customer_by_email",
    "get_subscription_status",
    "create_payment_link",
    "create_customer",
    "update_customer",
    "list_customers",
    "get_customer_by_id",
    "create_subscription",
    "update_subscription",
    "cancel_subscription",
    "list_subscriptions",
    "list_invoices",
    "retrieve_invoice",
    "pay_invoice",
    "list_payment_intents",
    "create_checkout_session",
    "verify_webhook_signature"
]