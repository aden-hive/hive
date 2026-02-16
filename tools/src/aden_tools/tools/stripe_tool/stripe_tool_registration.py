"""
Stripe Tool Registration for Hive Framework.

Registers all Stripe payment processing tools with the MCP server.
Tools are registered regardless of credential availability - they will
return helpful error messages when called without valid credentials.
"""

import os
from typing import Any

from fastmcp import FastMCP

from .stripe_tool import StripeTool, StripeToolConfig


def register_tools(
    mcp: FastMCP,
    credentials: dict[str, Any] | None = None,
) -> list[str]:
    """
    Register all Stripe payment processing tools with MCP server.

    This function registers all 45+ Stripe tools. Tools are registered even
    when credentials are missing - they will return error messages when called.

    Args:
        mcp: FastMCP server instance to register tools with
        credentials: Optional dictionary containing Stripe credentials.
                    Expected format: {"stripe": {"api_key": "sk_...",
                    "webhook_secret": "whsec_..."}}

    Returns:
        List of registered tool names (empty list if initialization fails)
    """
    # Extract Stripe API key from credentials or environmentssss
    api_key = None
    webhook_secret = None

    if credentials and "stripe" in credentials:
        stripe_creds = credentials["stripe"]
        api_key = stripe_creds.get("api_key")
        webhook_secret = stripe_creds.get("webhook_secret")

    # Fallback to environment variables
    if not api_key:
        api_key = os.environ.get("STRIPE_API_KEY") or os.environ.get("STRIPE_SECRET_KEY")

    if not webhook_secret:
        webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

    # Initialize StripeTool
    # If no API key is available, we still need to register the tools
    # so they appear in the tool list (they'll return errors when called)
    try:
        if api_key:
            config = StripeToolConfig(api_key=api_key)
            stripe_tool = StripeTool(config=config)
        else:
            # No API key available - print warning but continue registration
            print(
                "Warning: Stripe API key not found. Stripe tools will be registered "
                "but will return errors when called without credentials.\n"
                "Set STRIPE_API_KEY environment variable or provide credentials parameter."
            )
            # Create a dummy tool that will error on use
            # This allows tools to be registered for testing
            stripe_tool = None
    except Exception as e:
        print(f"Warning: Failed to initialize Stripe tool: {e}")
        # Return empty list - registration failed
        return []

    # List to track registered tool names
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
        """
        Create a new Stripe customer.

        Args:
            email: Customer email address (required)
            name: Customer full name
            description: Internal description for the customer
            metadata: Custom key-value metadata (max 50 keys)
            payment_method: ID of payment method to attach
            invoice_settings: Default invoice settings for customer

        Returns:
            Dictionary containing customer details including id, email, created timestamp
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured. Set STRIPE_API_KEY"
            " environment variable."}
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
        """
        Retrieve a customer by their email address.

        Args:
            email: Customer email to search for

        Returns:
            Customer object if found, or error if not found or multiple matches
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.get_customer_by_email(email)

    registered_tools.append("stripe_get_customer_by_email")

    @mcp.tool()
    def stripe_get_customer_by_id(customer_id: str) -> dict[str, Any]:
        """
        Retrieve a customer by their Stripe customer ID.

        Args:
            customer_id: Stripe customer ID (starts with cus_)

        Returns:
            Customer object dictionary
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
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
        """
        Update an existing customer's information.

        Args:
            customer_id: Stripe customer ID to update
            email: New email address
            name: New customer name
            description: New description
            metadata: New or updated metadata
            default_payment_method: New default payment method ID

        Returns:
            Updated customer object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
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
    def stripe_list_customers(
        email: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        List customers with optional email filter.

        Args:
            email: Filter by customer email
            limit: Maximum number of customers to return (1-100)

        Returns:
            Dictionary with 'data' array of customer objects and pagination info
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.list_customers(email=email, limit=limit)

    registered_tools.append("stripe_list_customers")

    @mcp.tool()
    def stripe_delete_customer(customer_id: str) -> dict[str, Any]:
        """
        Delete a customer permanently.

        Args:
            customer_id: Stripe customer ID to delete

        Returns:
            Confirmation dictionary with deleted status
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
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
        """
        Create a new subscription for a customer.

        Args:
            customer_id: Stripe customer ID
            price_id: Stripe price ID to subscribe to
            quantity: Number of units (default 1)
            trial_period_days: Number of trial days before billing
            metadata: Custom metadata
            payment_behavior: How to handle payment (default_incomplete, allow_incomplete,
              error_if_incomplete)

        Returns:
            Subscription object with status, current_period_end, etc.
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
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
        """
        Get current subscription status and details.

        Args:
            subscription_id: Stripe subscription ID

        Returns:
            Subscription object with status, billing dates, items, etc.
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
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
        """
        Update an existing subscription.

        Args:
            subscription_id: Subscription to update
            price_id: New price ID to switch to
            quantity: New quantity
            metadata: Updated metadata
            proration_behavior: How to handle prorations (create_prorations, none, always_invoice)

        Returns:
            Updated subscription object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
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
        subscription_id: str,
        cancel_at_period_end: bool = False,
    ) -> dict[str, Any]:
        """
        Cancel a subscription immediately or at period end.

        Args:
            subscription_id: Subscription to cancel
            cancel_at_period_end: If True, cancel at end of billing period;
            if False,cancel immediately

        Returns:
            Updated subscription object with canceled status
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.cancel_subscription(
            subscription_id=subscription_id,
            cancel_at_period_end=cancel_at_period_end,
        )

    registered_tools.append("stripe_cancel_subscription")

    @mcp.tool()
    def stripe_pause_subscription(
        subscription_id: str,
        resumes_at: int | None = None,
    ) -> dict[str, Any]:
        """
        Pause a subscription.

        Args:
            subscription_id: Subscription to pause
            resumes_at: Unix timestamp when subscription should resume (optional)

        Returns:
            Updated subscription with paused status
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.pause_subscription(
            subscription_id=subscription_id,
            resumes_at=resumes_at,
        )

    registered_tools.append("stripe_pause_subscription")

    @mcp.tool()
    def stripe_resume_subscription(subscription_id: str) -> dict[str, Any]:
        """
        Resume a paused subscription.

        Args:
            subscription_id: Subscription to resume

        Returns:
            Updated subscription object with active status
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.resume_subscription(subscription_id)

    registered_tools.append("stripe_resume_subscription")

    @mcp.tool()
    def stripe_list_subscriptions(
        customer_id: str | None = None,
        status: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        List subscriptions with optional filters.

        Args:
            customer_id: Filter by customer
            status: Filter by status (active, past_due, canceled, etc.)
            limit: Maximum results (1-100)

        Returns:
            Dictionary with 'data' array of subscriptions
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.list_subscriptions(
            customer_id=customer_id,
            status=status,
            limit=limit,
        )

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
        """
        Create a new invoice for a customer.

        Args:
            customer_id: Customer to invoice
            auto_advance: Automatically finalize and attempt payment
            collection_method: charge_automatically or send_invoice
            description: Invoice description
            metadata: Custom metadata

        Returns:
            Invoice object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
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
        """
        Retrieve invoice details.

        Args:
            invoice_id: Invoice ID to retrieve

        Returns:
            Invoice object with line items, amount, status, etc.
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.get_invoice(invoice_id)

    registered_tools.append("stripe_get_invoice")

    @mcp.tool()
    def stripe_list_invoices(
        customer_id: str | None = None,
        status: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        List invoices with filters.

        Args:
            customer_id: Filter by customer
            status: Filter by status (draft, open, paid, void, uncollectible)
            limit: Maximum results

        Returns:
            Dictionary with 'data' array of invoices
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.list_invoices(
            customer_id=customer_id,
            status=status,
            limit=limit,
        )

    registered_tools.append("stripe_list_invoices")

    @mcp.tool()
    def stripe_pay_invoice(invoice_id: str) -> dict[str, Any]:
        """
        Attempt to pay an invoice.

        Args:
            invoice_id: Invoice to pay

        Returns:
            Updated invoice object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.pay_invoice(invoice_id)

    registered_tools.append("stripe_pay_invoice")

    @mcp.tool()
    def stripe_void_invoice(invoice_id: str) -> dict[str, Any]:
        """
        Void an invoice (mark as uncollectible).

        Args:
            invoice_id: Invoice to void

        Returns:
            Voided invoice object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.void_invoice(invoice_id)

    registered_tools.append("stripe_void_invoice")

    @mcp.tool()
    def stripe_finalize_invoice(invoice_id: str) -> dict[str, Any]:
        """
        Finalize a draft invoice (make it ready for payment).

        Args:
            invoice_id: Invoice to finalize

        Returns:
            Finalized invoice object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.finalize_invoice(invoice_id)

    registered_tools.append("stripe_finalize_invoice")

    # ==================== PAYMENT METHODS ====================

    @mcp.tool()
    def stripe_attach_payment_method(
        payment_method_id: str,
        customer_id: str,
    ) -> dict[str, Any]:
        """
        Attach a payment method to a customer.

        Args:
            payment_method_id: Payment method to attach
            customer_id: Customer to attach to

        Returns:
            Updated payment method object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.attach_payment_method(payment_method_id, customer_id)

    registered_tools.append("stripe_attach_payment_method")

    @mcp.tool()
    def stripe_detach_payment_method(payment_method_id: str) -> dict[str, Any]:
        """
        Detach a payment method from its customer.

        Args:
            payment_method_id: Payment method to detach

        Returns:
            Updated payment method object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.detach_payment_method(payment_method_id)

    registered_tools.append("stripe_detach_payment_method")

    @mcp.tool()
    def stripe_list_payment_methods(
        customer_id: str,
        type: str = "card",
    ) -> dict[str, Any]:
        """
        List payment methods for a customer.

        Args:
            customer_id: Customer to list methods for
            type: Payment method type (card, us_bank_account, etc.)

        Returns:
            Dictionary with 'data' array of payment methods
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.list_payment_methods(customer_id, type)

    registered_tools.append("stripe_list_payment_methods")

    @mcp.tool()
    def stripe_set_default_payment_method(
        customer_id: str,
        payment_method_id: str,
    ) -> dict[str, Any]:
        """
        Set the default payment method for a customer.

        Args:
            customer_id: Customer to update
            payment_method_id: Payment method to set as default

        Returns:
            Updated customer object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
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
        """
        Create a payment intent.

        Args:
            amount: Amount in cents (e.g., 1000 = $10.00)
            currency: Three-letter currency code (e.g., usd, eur)
            customer_id: Customer to charge
            payment_method: Payment method to use
            description: Payment description
            metadata: Custom metadata

        Returns:
            Payment intent object with client_secret for frontend
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
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
        """
        Confirm a payment intent.

        Args:
            payment_intent_id: Payment intent to confirm

        Returns:
            Updated payment intent object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.confirm_payment_intent(payment_intent_id)

    registered_tools.append("stripe_confirm_payment_intent")

    @mcp.tool()
    def stripe_cancel_payment_intent(payment_intent_id: str) -> dict[str, Any]:
        """
        Cancel a payment intent.

        Args:
            payment_intent_id: Payment intent to cancel

        Returns:
            Canceled payment intent object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.cancel_payment_intent(payment_intent_id)

    registered_tools.append("stripe_cancel_payment_intent")

    @mcp.tool()
    def stripe_capture_payment_intent(
        payment_intent_id: str,
        amount_to_capture: int | None = None,
    ) -> dict[str, Any]:
        """
        Capture a payment intent (for manual capture mode).

        Args:
            payment_intent_id: Payment intent to capture
            amount_to_capture: Amount to capture in cents (None = full amount)

        Returns:
            Captured payment intent object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.capture_payment_intent(payment_intent_id, amount_to_capture)

    registered_tools.append("stripe_capture_payment_intent")

    @mcp.tool()
    def stripe_list_payment_intents(
        customer_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        List payment intents.

        Args:
            customer_id: Filter by customer
            limit: Maximum results

        Returns:
            Dictionary with 'data' array of payment intents
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
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
        """
        Create a Stripe Checkout session.

        Args:
            price_id: Price to charge
            success_url: URL to redirect on success
            cancel_url: URL to redirect on cancel
            customer_id: Existing customer ID
            quantity: Quantity of items
            mode: payment, subscription, or setup

        Returns:
            Checkout session with url to redirect customer
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
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
        """
        Retrieve a checkout session.

        Args:
            session_id: Checkout session ID

        Returns:
            Checkout session object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.get_checkout_session(session_id)

    registered_tools.append("stripe_get_checkout_session")

    @mcp.tool()
    def stripe_expire_checkout_session(session_id: str) -> dict[str, Any]:
        """
        Expire a checkout session (prevent further use).

        Args:
            session_id: Checkout session to expire

        Returns:
            Expired checkout session
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.expire_checkout_session(session_id)

    registered_tools.append("stripe_expire_checkout_session")

    @mcp.tool()
    def stripe_create_payment_link(
        price_id: str,
        quantity: int = 1,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Create a payment link (shareable checkout link).

        Args:
            price_id: Price to charge
            quantity: Default quantity
            metadata: Custom metadata

        Returns:
            Payment link object with url
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.create_payment_link(
            price_id=price_id,
            quantity=quantity,
            metadata=metadata,
        )

    registered_tools.append("stripe_create_payment_link")

    # ==================== PRODUCTS & PRICES ====================

    @mcp.tool()
    def stripe_create_product(
        name: str,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Create a product in the catalog.

        Args:
            name: Product name
            description: Product description
            metadata: Custom metadata

        Returns:
            Product object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.create_product(
            name=name,
            description=description,
            metadata=metadata,
        )

    registered_tools.append("stripe_create_product")

    @mcp.tool()
    def stripe_get_product(product_id: str) -> dict[str, Any]:
        """
        Retrieve a product.

        Args:
            product_id: Product ID

        Returns:
            Product object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.get_product(product_id)

    registered_tools.append("stripe_get_product")

    @mcp.tool()
    def stripe_update_product(
        product_id: str,
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Update a product.

        Args:
            product_id: Product to update
            name: New name
            description: New description
            metadata: Updated metadata

        Returns:
            Updated product object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.update_product(
            product_id=product_id,
            name=name,
            description=description,
            metadata=metadata,
        )

    registered_tools.append("stripe_update_product")

    @mcp.tool()
    def stripe_list_products(limit: int = 10) -> dict[str, Any]:
        """
        List products.

        Args:
            limit: Maximum results

        Returns:
            Dictionary with 'data' array of products
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.list_products(limit)

    registered_tools.append("stripe_list_products")

    @mcp.tool()
    def stripe_archive_product(product_id: str) -> dict[str, Any]:
        """
        Archive a product (make inactive).

        Args:
            product_id: Product to archive

        Returns:
            Archived product object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
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
        """
        Create a price for a product.

        Args:
            product_id: Product to price
            unit_amount: Price in cents
            currency: Currency code
            recurring_interval: For subscriptions: day, week, month, year
            recurring_interval_count: Billing frequency (e.g., 3 for quarterly)

        Returns:
            Price object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
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
        """
        Retrieve a price.

        Args:
            price_id: Price ID

        Returns:
            Price object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.get_price(price_id)

    registered_tools.append("stripe_get_price")

    @mcp.tool()
    def stripe_list_prices(
        product_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        List prices.

        Args:
            product_id: Filter by product
            limit: Maximum results

        Returns:
            Dictionary with 'data' array of prices
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.list_prices(product_id, limit)

    registered_tools.append("stripe_list_prices")

    # ==================== REFUNDS ====================

    @mcp.tool()
    def stripe_create_refund(
        payment_intent_id: str,
        amount: int | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a refund.

        Args:
            payment_intent_id: Payment to refund
            amount: Amount to refund in cents (None = full amount)
            reason: Refund reason (duplicate, fraudulent, requested_by_customer)

        Returns:
            Refund object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.create_refund(
            payment_intent_id=payment_intent_id,
            amount=amount,
            reason=reason,
        )

    registered_tools.append("stripe_create_refund")

    @mcp.tool()
    def stripe_get_refund(refund_id: str) -> dict[str, Any]:
        """
        Retrieve refund details.

        Args:
            refund_id: Refund ID

        Returns:
            Refund object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.get_refund(refund_id)

    registered_tools.append("stripe_get_refund")

    @mcp.tool()
    def stripe_list_refunds(
        payment_intent_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        List refunds.

        Args:
            payment_intent_id: Filter by payment intent
            limit: Maximum results

        Returns:
            Dictionary with 'data' array of refunds
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.list_refunds(payment_intent_id, limit)

    registered_tools.append("stripe_list_refunds")

    @mcp.tool()
    def stripe_cancel_refund(refund_id: str) -> dict[str, Any]:
        """
        Cancel a pending refund.

        Args:
            refund_id: Refund to cancel

        Returns:
            Canceled refund object
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        return stripe_tool.cancel_refund(refund_id)

    registered_tools.append("stripe_cancel_refund")

    # ==================== WEBHOOKS ====================

    @mcp.tool()
    def stripe_verify_webhook_signature(
        payload: str,
        signature: str,
    ) -> dict[str, Any]:
        """
        Verify a Stripe webhook signature.

        Args:
            payload: Raw webhook payload body
            signature: Stripe-Signature header value

        Returns:
            Verified event object or error
        """
        if stripe_tool is None:
            return {"error": "Stripe API key not configured"}
        if not webhook_secret:
            return {"error": "Stripe webhook secret not configured. Set STRIPE_WEBHOOK_SECRET "
            "environment variable."}
        return stripe_tool.verify_webhook_signature(payload, signature, webhook_secret)

    registered_tools.append("stripe_verify_webhook_signature")

    return registered_tools


__all__ = ["register_tools"]
