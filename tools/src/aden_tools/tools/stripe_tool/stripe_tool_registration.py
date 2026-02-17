"""
Stripe Tool Registration for Hive Framework.

Registers all Stripe payment processing tools with the MCP server.
"""

import os
from typing import Any

from fastmcp import FastMCP

from .stripe_tool import StripeTool, StripeToolConfig

# Standard help text for missing credentials
STRIPE_HELP_TEXT = """To get your Stripe API key:
1. Go to https://dashboard.stripe.com/apikeys
2. Sign in to your Stripe account
3. For development: Copy the test mode Secret key (starts with sk_test_)
4. For production: Copy the live mode Secret key (starts with sk_live_)
5. Set STRIPE_API_KEY environment variable"""


def register_tools(
    mcp: FastMCP,
    credentials: Any | None = None,
) -> list[str]:
    """Register all Stripe tools with MCP server."""

    # 1. Try to load API key from environment
    api_key = os.environ.get("STRIPE_API_KEY") or os.environ.get("STRIPE_SECRET_KEY")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

    # 2. Initialize Tool (Safe Mode)
    stripe_tool = None
    try:
        if api_key:
            config = StripeToolConfig(api_key=api_key, webhook_secret=webhook_secret)
            stripe_tool = StripeTool(config=config)
        else:
            # Initialize without config to support lazy loading of errors
            stripe_tool = StripeTool(config=None)
    except Exception as e:
        print(f"Warning: Failed to initialize Stripe tool: {e}")
        # Even if init fails, we usually want to register tools that return errors
        # But if it crashes hard, return empty list
        return []

    # Helper to return standardized error with help text
    def get_missing_cred_error() -> dict[str, str]:
        return {"error": "Stripe API key not configured.", "help": STRIPE_HELP_TEXT}

    registered_tools: list[str] = []

    # ==================== CUSTOMER MANAGEMENT ====================

    @mcp.tool()
    def stripe_create_customer(
        email: str,
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
        payment_method: str | None = None,
        invoice_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new Stripe customer."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.create_customer(
            email=email,
            name=name,
            description=description,
            metadata=metadata,
            payment_method=payment_method,
            invoice_settings=invoice_settings,
        )

    registered_tools.append("stripe_create_customer")

    @mcp.tool()
    def stripe_get_customer_by_email(email: str) -> dict[str, Any]:
        """Retrieve a customer by their email address."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.get_customer_by_email(email)

    registered_tools.append("stripe_get_customer_by_email")

    @mcp.tool()
    def stripe_get_customer_by_id(customer_id: str) -> dict[str, Any]:
        """Retrieve a customer by their Stripe customer ID."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.get_customer_by_id(customer_id)

    registered_tools.append("stripe_get_customer_by_id")

    @mcp.tool()
    def stripe_update_customer(
        customer_id: str,
        email: str | None = None,
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
        default_payment_method: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing customer's information."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.update_customer(
            customer_id=customer_id,
            email=email,
            name=name,
            description=description,
            metadata=metadata,
            default_payment_method=default_payment_method,
        )

    registered_tools.append("stripe_update_customer")

    @mcp.tool()
    def stripe_list_customers(email: str | None = None, limit: int = 10) -> dict[str, Any]:
        """List customers with optional email filter."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.list_customers(email=email, limit=limit)

    registered_tools.append("stripe_list_customers")

    @mcp.tool()
    def stripe_delete_customer(customer_id: str) -> dict[str, Any]:
        """Delete a customer permanently."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.delete_customer(customer_id)

    registered_tools.append("stripe_delete_customer")

    # ==================== SUBSCRIPTION MANAGEMENT ====================

    @mcp.tool()
    def stripe_create_subscription(
        customer_id: str,
        price_id: str,
        quantity: int = 1,
        trial_period_days: int | None = None,
        metadata: dict[str, str] | None = None,
        payment_behavior: str = "default_incomplete",
    ) -> dict[str, Any]:
        """Create a new subscription for a customer."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.create_subscription(
            customer_id=customer_id,
            price_id=price_id,
            quantity=quantity,
            trial_period_days=trial_period_days,
            metadata=metadata,
            payment_behavior=payment_behavior,
        )

    registered_tools.append("stripe_create_subscription")

    @mcp.tool()
    def stripe_get_subscription_status(subscription_id: str) -> dict[str, Any]:
        """Get current subscription status and details."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.get_subscription_status(subscription_id)

    registered_tools.append("stripe_get_subscription_status")

    @mcp.tool()
    def stripe_update_subscription(
        subscription_id: str,
        price_id: str | None = None,
        quantity: int | None = None,
        metadata: dict[str, str] | None = None,
        proration_behavior: str = "create_prorations",
    ) -> dict[str, Any]:
        """Update an existing subscription."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.update_subscription(
            subscription_id=subscription_id,
            price_id=price_id,
            quantity=quantity,
            metadata=metadata,
            proration_behavior=proration_behavior,
        )

    registered_tools.append("stripe_update_subscription")

    @mcp.tool()
    def stripe_cancel_subscription(
        subscription_id: str, cancel_at_period_end: bool = False
    ) -> dict[str, Any]:
        """Cancel a subscription immediately or at period end."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.cancel_subscription(
            subscription_id=subscription_id, cancel_at_period_end=cancel_at_period_end
        )

    registered_tools.append("stripe_cancel_subscription")

    @mcp.tool()
    def stripe_pause_subscription(
        subscription_id: str, resumes_at: int | None = None
    ) -> dict[str, Any]:
        """Pause a subscription."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.pause_subscription(
            subscription_id=subscription_id, resumes_at=resumes_at
        )

    registered_tools.append("stripe_pause_subscription")

    @mcp.tool()
    def stripe_resume_subscription(subscription_id: str) -> dict[str, Any]:
        """Resume a paused subscription."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.resume_subscription(subscription_id)

    registered_tools.append("stripe_resume_subscription")

    @mcp.tool()
    def stripe_list_subscriptions(
        customer_id: str | None = None, status: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        """List subscriptions with optional filters."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.list_subscriptions(customer_id=customer_id, status=status, limit=limit)

    registered_tools.append("stripe_list_subscriptions")

    # ==================== INVOICE MANAGEMENT ====================

    @mcp.tool()
    def stripe_create_invoice(
        customer_id: str,
        auto_advance: bool = True,
        collection_method: str = "charge_automatically",
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a new invoice for a customer."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.create_invoice(
            customer_id=customer_id,
            auto_advance=auto_advance,
            collection_method=collection_method,
            description=description,
            metadata=metadata,
        )

    registered_tools.append("stripe_create_invoice")

    @mcp.tool()
    def stripe_get_invoice(invoice_id: str) -> dict[str, Any]:
        """Retrieve invoice details."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.get_invoice(invoice_id)

    registered_tools.append("stripe_get_invoice")

    @mcp.tool()
    def stripe_list_invoices(
        customer_id: str | None = None, status: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        """List invoices with filters."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.list_invoices(customer_id=customer_id, status=status, limit=limit)

    registered_tools.append("stripe_list_invoices")

    @mcp.tool()
    def stripe_pay_invoice(invoice_id: str) -> dict[str, Any]:
        """Attempt to pay an invoice."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.pay_invoice(invoice_id)

    registered_tools.append("stripe_pay_invoice")

    @mcp.tool()
    def stripe_void_invoice(invoice_id: str) -> dict[str, Any]:
        """Void an invoice (mark as uncollectible)."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.void_invoice(invoice_id)

    registered_tools.append("stripe_void_invoice")

    @mcp.tool()
    def stripe_finalize_invoice(invoice_id: str) -> dict[str, Any]:
        """Finalize a draft invoice (make it ready for payment)."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.finalize_invoice(invoice_id)

    registered_tools.append("stripe_finalize_invoice")

    # ==================== PAYMENT METHODS ====================

    @mcp.tool()
    def stripe_attach_payment_method(payment_method_id: str, customer_id: str) -> dict[str, Any]:
        """Attach a payment method to a customer."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.attach_payment_method(payment_method_id, customer_id)

    registered_tools.append("stripe_attach_payment_method")

    @mcp.tool()
    def stripe_detach_payment_method(payment_method_id: str) -> dict[str, Any]:
        """Detach a payment method from its customer."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.detach_payment_method(payment_method_id)

    registered_tools.append("stripe_detach_payment_method")

    @mcp.tool()
    def stripe_list_payment_methods(customer_id: str, type: str = "card") -> dict[str, Any]:
        """List payment methods for a customer."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.list_payment_methods(customer_id, type)

    registered_tools.append("stripe_list_payment_methods")

    @mcp.tool()
    def stripe_set_default_payment_method(
        customer_id: str, payment_method_id: str
    ) -> dict[str, Any]:
        """Set the default payment method for a customer."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.set_default_payment_method(customer_id, payment_method_id)

    registered_tools.append("stripe_set_default_payment_method")

    # ==================== PAYMENT INTENTS ====================

    @mcp.tool()
    def stripe_create_payment_intent(
        amount: int,
        currency: str = "usd",
        customer_id: str | None = None,
        payment_method: str | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a payment intent."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.create_payment_intent(
            amount=amount,
            currency=currency,
            customer_id=customer_id,
            payment_method=payment_method,
            description=description,
            metadata=metadata,
        )

    registered_tools.append("stripe_create_payment_intent")

    @mcp.tool()
    def stripe_confirm_payment_intent(payment_intent_id: str) -> dict[str, Any]:
        """Confirm a payment intent."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.confirm_payment_intent(payment_intent_id)

    registered_tools.append("stripe_confirm_payment_intent")

    @mcp.tool()
    def stripe_cancel_payment_intent(payment_intent_id: str) -> dict[str, Any]:
        """Cancel a payment intent."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.cancel_payment_intent(payment_intent_id)

    registered_tools.append("stripe_cancel_payment_intent")

    @mcp.tool()
    def stripe_capture_payment_intent(
        payment_intent_id: str, amount_to_capture: int | None = None
    ) -> dict[str, Any]:
        """Capture a payment intent (for manual capture mode)."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.capture_payment_intent(payment_intent_id, amount_to_capture)

    registered_tools.append("stripe_capture_payment_intent")

    @mcp.tool()
    def stripe_list_payment_intents(
        customer_id: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        """List payment intents."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.list_payment_intents(customer_id, limit)

    registered_tools.append("stripe_list_payment_intents")

    # ==================== CHECKOUT SESSIONS ====================

    @mcp.tool()
    def stripe_create_checkout_session(
        price_id: str,
        success_url: str,
        cancel_url: str,
        customer_id: str | None = None,
        quantity: int = 1,
        mode: str = "payment",
    ) -> dict[str, Any]:
        """Create a Stripe Checkout session."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.create_checkout_session(
            price_id=price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_id=customer_id,
            quantity=quantity,
            mode=mode,
        )

    registered_tools.append("stripe_create_checkout_session")

    @mcp.tool()
    def stripe_get_checkout_session(session_id: str) -> dict[str, Any]:
        """Retrieve a checkout session."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.get_checkout_session(session_id)

    registered_tools.append("stripe_get_checkout_session")

    @mcp.tool()
    def stripe_expire_checkout_session(session_id: str) -> dict[str, Any]:
        """Expire a checkout session (prevent further use)."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.expire_checkout_session(session_id)

    registered_tools.append("stripe_expire_checkout_session")

    @mcp.tool()
    def stripe_create_payment_link(
        price_id: str, quantity: int = 1, metadata: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Create a payment link (shareable checkout link)."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.create_payment_link(
            price_id=price_id, quantity=quantity, metadata=metadata
        )

    registered_tools.append("stripe_create_payment_link")

    # ==================== PRODUCTS & PRICES ====================

    @mcp.tool()
    def stripe_create_product(
        name: str,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a product in the catalog."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.create_product(name=name, description=description, metadata=metadata)

    registered_tools.append("stripe_create_product")

    @mcp.tool()
    def stripe_get_product(product_id: str) -> dict[str, Any]:
        """Retrieve a product."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.get_product(product_id)

    registered_tools.append("stripe_get_product")

    @mcp.tool()
    def stripe_update_product(
        product_id: str,
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Update a product."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.update_product(
            product_id=product_id,
            name=name,
            description=description,
            metadata=metadata,
        )

    registered_tools.append("stripe_update_product")

    @mcp.tool()
    def stripe_list_products(limit: int = 10) -> dict[str, Any]:
        """List products."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.list_products(limit)

    registered_tools.append("stripe_list_products")

    @mcp.tool()
    def stripe_archive_product(product_id: str) -> dict[str, Any]:
        """Archive a product (make inactive)."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.archive_product(product_id)

    registered_tools.append("stripe_archive_product")

    @mcp.tool()
    def stripe_create_price(
        product_id: str,
        unit_amount: int,
        currency: str = "usd",
        recurring_interval: str | None = None,
        recurring_interval_count: int = 1,
    ) -> dict[str, Any]:
        """Create a price for a product."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.create_price(
            product_id=product_id,
            unit_amount=unit_amount,
            currency=currency,
            recurring_interval=recurring_interval,
            recurring_interval_count=recurring_interval_count,
        )

    registered_tools.append("stripe_create_price")

    @mcp.tool()
    def stripe_get_price(price_id: str) -> dict[str, Any]:
        """Retrieve a price."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.get_price(price_id)

    registered_tools.append("stripe_get_price")

    @mcp.tool()
    def stripe_list_prices(product_id: str | None = None, limit: int = 10) -> dict[str, Any]:
        """List prices."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.list_prices(product_id, limit)

    registered_tools.append("stripe_list_prices")

    # ==================== REFUNDS ====================

    @mcp.tool()
    def stripe_create_refund(
        payment_intent_id: str,
        amount: int | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Create a refund."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.create_refund(
            payment_intent_id=payment_intent_id, amount=amount, reason=reason
        )

    registered_tools.append("stripe_create_refund")

    @mcp.tool()
    def stripe_get_refund(refund_id: str) -> dict[str, Any]:
        """Retrieve refund details."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.get_refund(refund_id)

    registered_tools.append("stripe_get_refund")

    @mcp.tool()
    def stripe_list_refunds(
        payment_intent_id: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        """List refunds."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.list_refunds(payment_intent_id, limit)

    registered_tools.append("stripe_list_refunds")

    @mcp.tool()
    def stripe_cancel_refund(refund_id: str) -> dict[str, Any]:
        """Cancel a pending refund."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.cancel_refund(refund_id)

    registered_tools.append("stripe_cancel_refund")

    # ==================== WEBHOOKS ====================

    @mcp.tool()
    def stripe_verify_webhook_signature(
        payload: str,
        signature: str,
    ) -> dict[str, Any]:
        """Verify a Stripe webhook signature."""
        if stripe_tool is None:
            return get_missing_cred_error()
        return stripe_tool.verify_webhook_signature(payload, signature)

    registered_tools.append("stripe_verify_webhook_signature")

    return registered_tools


__all__ = ["register_tools"]
