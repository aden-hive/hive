"""
Stripe Tool Registration for FastMCP

This module provides the register_tools function to integrate Stripe with FastMCP,
following the same pattern as other Hive tools.
"""

from fastmcp import FastMCP

from .stripe_tool import StripeTool


def register_tools(mcp: FastMCP, credentials=None) -> None:
    """
    Register Stripe tools with FastMCP server.

    Follows the same pattern as other Hive tools (github_tool, slack_tool, etc.)

    Args:
        mcp: FastMCP server instance
        credentials: Optional CredentialStoreAdapter instance (not currently used,
                     Stripe reads from STRIPE_API_KEY environment variable)
    """
    try:
        # Initialize Stripe tools
        stripe_tool = StripeTool()

        # Register all Stripe methods as FastMCP tools
        # Customer Management
        mcp.tool(name="stripe_create_customer")(stripe_tool.create_customer)
        mcp.tool(name="stripe_get_customer_by_email")(stripe_tool.get_customer_by_email)
        mcp.tool(name="stripe_get_customer_by_id")(stripe_tool.get_customer_by_id)
        mcp.tool(name="stripe_update_customer")(stripe_tool.update_customer)
        mcp.tool(name="stripe_list_customers")(stripe_tool.list_customers)
        mcp.tool(name="stripe_delete_customer")(stripe_tool.delete_customer)

        # Subscription Management
        mcp.tool(name="stripe_create_subscription")(stripe_tool.create_subscription)
        mcp.tool(name="stripe_get_subscription_status")(stripe_tool.get_subscription_status)
        mcp.tool(name="stripe_update_subscription")(stripe_tool.update_subscription)
        mcp.tool(name="stripe_cancel_subscription")(stripe_tool.cancel_subscription)
        mcp.tool(name="stripe_pause_subscription")(stripe_tool.pause_subscription)
        mcp.tool(name="stripe_resume_subscription")(stripe_tool.resume_subscription)
        mcp.tool(name="stripe_list_subscriptions")(stripe_tool.list_subscriptions)

        # Invoice Management
        mcp.tool(name="stripe_create_invoice")(stripe_tool.create_invoice)
        mcp.tool(name="stripe_get_invoice")(stripe_tool.get_invoice)
        mcp.tool(name="stripe_list_invoices")(stripe_tool.list_invoices)
        mcp.tool(name="stripe_pay_invoice")(stripe_tool.pay_invoice)
        mcp.tool(name="stripe_void_invoice")(stripe_tool.void_invoice)
        mcp.tool(name="stripe_finalize_invoice")(stripe_tool.finalize_invoice)

        # Payment Methods
        mcp.tool(name="stripe_attach_payment_method")(stripe_tool.attach_payment_method)
        mcp.tool(name="stripe_detach_payment_method")(stripe_tool.detach_payment_method)
        mcp.tool(name="stripe_list_payment_methods")(stripe_tool.list_payment_methods)
        mcp.tool(name="stripe_set_default_payment_method")(stripe_tool.set_default_payment_method)

        # Payment Intents
        mcp.tool(name="stripe_create_payment_intent")(stripe_tool.create_payment_intent)
        mcp.tool(name="stripe_confirm_payment_intent")(stripe_tool.confirm_payment_intent)
        mcp.tool(name="stripe_cancel_payment_intent")(stripe_tool.cancel_payment_intent)
        mcp.tool(name="stripe_capture_payment_intent")(stripe_tool.capture_payment_intent)
        mcp.tool(name="stripe_list_payment_intents")(stripe_tool.list_payment_intents)

        # Checkout & Payment Links
        mcp.tool(name="stripe_create_checkout_session")(stripe_tool.create_checkout_session)
        mcp.tool(name="stripe_get_checkout_session")(stripe_tool.get_checkout_session)
        mcp.tool(name="stripe_expire_checkout_session")(stripe_tool.expire_checkout_session)
        mcp.tool(name="stripe_create_payment_link")(stripe_tool.create_payment_link)

        # Products & Prices
        mcp.tool(name="stripe_create_product")(stripe_tool.create_product)
        mcp.tool(name="stripe_get_product")(stripe_tool.get_product)
        mcp.tool(name="stripe_update_product")(stripe_tool.update_product)
        mcp.tool(name="stripe_list_products")(stripe_tool.list_products)
        mcp.tool(name="stripe_archive_product")(stripe_tool.archive_product)
        mcp.tool(name="stripe_create_price")(stripe_tool.create_price)
        mcp.tool(name="stripe_get_price")(stripe_tool.get_price)
        mcp.tool(name="stripe_list_prices")(stripe_tool.list_prices)

        # Refunds
        mcp.tool(name="stripe_create_refund")(stripe_tool.create_refund)
        mcp.tool(name="stripe_get_refund")(stripe_tool.get_refund)
        mcp.tool(name="stripe_list_refunds")(stripe_tool.list_refunds)
        mcp.tool(name="stripe_cancel_refund")(stripe_tool.cancel_refund)

        # Webhooks
        mcp.tool(name="stripe_verify_webhook_signature")(stripe_tool.verify_webhook_signature)

    except Exception as e:
        # Fail gracefully if Stripe is not configured
        print(f"Warning: Failed to register Stripe tools. Error: {e}")
        print("Make sure STRIPE_API_KEY environment variable is set.")


__all__ = ["register_tools"]
