"""
Stripe Tool for Hive Framework

Production-ready Stripe integration providing comprehensive payment and billing capabilities.
Supports customer management, subscriptions, invoices, payments, products, prices, webhooks,
 and more.

Author: Hive Contributors
Version: 1.0.0
"""

import os
from typing import Any

import stripe
from pydantic import BaseModel, Field


class StripeToolConfig(BaseModel):
    """Configuration for Stripe tool"""

    api_key: str = Field(description="Stripe API key (secret key)")
    api_version: str | None = Field(default="2024-11-20.acacia", description="Stripe API version")
    max_retries: int = Field(default=2, description="Maximum number of retries for API calls")
    timeout: int = Field(default=80, description="Request timeout in seconds")


class StripeTool:
    """
    Comprehensive Stripe integration tool for Hive agents.

    Provides full lifecycle management for:
    - Customers (create, update, retrieve, list, delete)
    - Subscriptions (create, update, cancel, pause, resume, list)
    - Invoices (create, retrieve, list, pay, void, finalize)
    - Payment Methods (attach, detach, list, set default)
    - Payment Intents (create, confirm, cancel, capture, list)
    - Checkout Sessions (create, retrieve, list, expire)
    - Products (create, update, retrieve, list, archive)
    - Prices (create, update, retrieve, list, archive)
    - Coupons (create, update, retrieve, list, delete)
    - Refunds (create, retrieve, list, cancel)
    - Disputes (retrieve, list, update, close)
    - Balance Transactions (retrieve, list)
    - Payouts (create, retrieve, list, cancel)
    - Webhooks (verify signature, construct event)
    """

    def __init__(self, config: StripeToolConfig | None = None):
        """
        Initialize Stripe tool with configuration.

        Args:
            config: StripeToolConfig instance, or None to load from environment
        """
        if config is None:
            api_key = os.environ.get("STRIPE_API_KEY") or os.environ.get("STRIPE_SECRET_KEY")
            if not api_key:
                raise ValueError(
                    "Stripe API key not found. Set STRIPE_API_KEY or STRIPE_SECRET_KEY "
                    "environment variable or provide config parameter."
                )
            config = StripeToolConfig(api_key=api_key)

        self.config = config
        stripe.api_key = config.api_key
        stripe.api_version = config.api_version
        stripe.max_network_retries = config.max_retries
        # Note: timeout configuration varies by Stripe SDK version
        # Some versions support stripe.default_http_client, others dons't
        # Timeout is handled by the SDK internally in newer versions

    # ==================== CUSTOMER MANAGEMENT ====================

    def create_customer(
        self,
        email: str,
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
        phone: str | None = None,
        address: dict[str, str] | None = None,
        payment_method: str | None = None,
        invoice_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new customer.

        Args:
            email: Customer email address
            name: Customer full name
            description: Internal description
            metadata: Custom key-value metadata
            phone: Customer phone number
            address: Billing address dictionary
            payment_method: Default payment method ID
            invoice_settings: Invoice preferences

        Returns:
            Customer object dictionary
        """
        params = {"email": email}
        if name:
            params["name"] = name
        if description:
            params["description"] = description
        if metadata:
            params["metadata"] = metadata
        if phone:
            params["phone"] = phone
        if address:
            params["address"] = address
        if payment_method:
            params["payment_method"] = payment_method
        if invoice_settings:
            params["invoice_settings"] = invoice_settings

        customer = stripe.Customer.create(**params)
        return customer.to_dict()

    def get_customer_by_email(self, email: str) -> dict[str, Any] | None:
        """
        Retrieve a customer by email address.

        Args:
            email: Customer email to search for

        Returns:
            Customer object dictionary or None if not found
        """
        customers = stripe.Customer.list(email=email, limit=1)
        if customers.data:
            return customers.data[0].to_dict()
        return None

    def get_customer_by_id(self, customer_id: str) -> dict[str, Any]:
        """
        Retrieve a customer by ID.

        Args:
            customer_id: Stripe customer ID

        Returns:
            Customer object dictionary
        """
        customer = stripe.Customer.retrieve(customer_id)
        return customer.to_dict()

    def update_customer(
        self,
        customer_id: str,
        email: str | None = None,
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
        phone: str | None = None,
        address: dict[str, str] | None = None,
        default_payment_method: str | None = None,
    ) -> dict[str, Any]:
        """
        Update an existing customer.

        Args:
            customer_id: Stripe customer ID
            email: New email address
            name: New name
            description: New description
            metadata: Updated metadata
            phone: New phone number
            address: New address
            default_payment_method: New default payment method

        Returns:
            Updated customer object dictionary
        """
        params = {}
        if email:
            params["email"] = email
        if name:
            params["name"] = name
        if description:
            params["description"] = description
        if metadata:
            params["metadata"] = metadata
        if phone:
            params["phone"] = phone
        if address:
            params["address"] = address
        if default_payment_method:
            params["invoice_settings"] = {"default_payment_method": default_payment_method}

        customer = stripe.Customer.modify(customer_id, **params)
        return customer.to_dict()

    def list_customers(
        self,
        limit: int = 10,
        email: str | None = None,
        starting_after: str | None = None,
        ending_before: str | None = None,
    ) -> dict[str, Any]:
        """
        List customers with optional filtering and pagination.

        Args:
            limit: Maximum number of customers to return (1-100)
            email: Filter by email address
            starting_after: Cursor for forward pagination
            ending_before: Cursor for backward pagination

        Returns:
            List response with customer objects
        """
        params = {"limit": min(limit, 100)}
        if email:
            params["email"] = email
        if starting_after:
            params["starting_after"] = starting_after
        if ending_before:
            params["ending_before"] = ending_before

        customers = stripe.Customer.list(**params)
        return customers.to_dict()

    def delete_customer(self, customer_id: str) -> dict[str, Any]:
        """
        Delete a customer.

        Args:
            customer_id: Stripe customer ID

        Returns:
            Deletion confirmation
        """
        result = stripe.Customer.delete(customer_id)
        return result.to_dict()

    # ==================== SUBSCRIPTION MANAGEMENT ====================

    def create_subscription(
        self,
        customer_id: str,
        items: list[dict[str, Any]],
        payment_behavior: str = "default_incomplete",
        collection_method: str = "charge_automatically",
        days_until_due: int | None = None,
        default_payment_method: str | None = None,
        trial_period_days: int | None = None,
        metadata: dict[str, str] | None = None,
        proration_behavior: str = "create_prorations",
    ) -> dict[str, Any]:
        """
        Create a new subscription for a customer.

        Args:
            customer_id: Stripe customer ID
            items: List of subscription items (price ID and quantity)
            payment_behavior: Payment behavior on subscription creation
            collection_method: How to collect payment ('charge_automatically' or 'send_invoice')
            days_until_due: Days until invoice is due (for send_invoice method)
            default_payment_method: Default payment method for subscription
            trial_period_days: Number of trial days
            metadata: Custom metadata
            proration_behavior: Proration behavior

        Returns:
            Subscription object dictionary
        """
        params = {
            "customer": customer_id,
            "items": items,
            "payment_behavior": payment_behavior,
            "collection_method": collection_method,
            "proration_behavior": proration_behavior,
        }
        if days_until_due:
            params["days_until_due"] = days_until_due
        if default_payment_method:
            params["default_payment_method"] = default_payment_method
        if trial_period_days:
            params["trial_period_days"] = trial_period_days
        if metadata:
            params["metadata"] = metadata

        subscription = stripe.Subscription.create(**params)
        return subscription.to_dict()

    def get_subscription_status(self, subscription_id: str) -> str:
        """
        Get the status of a subscription.

        Args:
            subscription_id: Stripe subscription ID

        Returns:
            Subscription status string (active, past_due, canceled, etc.)
        """
        subscription = stripe.Subscription.retrieve(subscription_id)
        return subscription.status

    def get_subscription(self, subscription_id: str) -> dict[str, Any]:
        """
        Retrieve a subscription by ID.

        Args:
            subscription_id: Stripe subscription ID

        Returns:
            Subscription object dictionary
        """
        subscription = stripe.Subscription.retrieve(subscription_id)
        return subscription.to_dict()

    def update_subscription(
        self,
        subscription_id: str,
        items: list[dict[str, Any]] | None = None,
        default_payment_method: str | None = None,
        metadata: dict[str, str] | None = None,
        proration_behavior: str = "create_prorations",
        cancel_at_period_end: bool | None = None,
    ) -> dict[str, Any]:
        """
        Update an existing subscription.

        Args:
            subscription_id: Stripe subscription ID
            items: Updated subscription items
            default_payment_method: New default payment method
            metadata: Updated metadata
            proration_behavior: How to handle prorations
            cancel_at_period_end: Whether to cancel at period end

        Returns:
            Updated subscription object dictionary
        """
        params = {"proration_behavior": proration_behavior}
        if items:
            params["items"] = items
        if default_payment_method:
            params["default_payment_method"] = default_payment_method
        if metadata:
            params["metadata"] = metadata
        if cancel_at_period_end is not None:
            params["cancel_at_period_end"] = cancel_at_period_end

        subscription = stripe.Subscription.modify(subscription_id, **params)
        return subscription.to_dict()

    def cancel_subscription(
        self,
        subscription_id: str,
        prorate: bool = False,
        invoice_now: bool = False,
        at_period_end: bool = False,
    ) -> dict[str, Any]:
        """
        Cancel a subscription.

        Args:
            subscription_id: Stripe subscription ID
            prorate: Whether to prorate
            invoice_now: Whether to invoice immediately
            at_period_end: Cancel at period end instead of immediately

        Returns:
            Canceled subscription object dictionary
        """
        if at_period_end:
            subscription = stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
        else:
            params = {}
            if prorate:
                params["prorate"] = True
            if invoice_now:
                params["invoice_now"] = True
            subscription = stripe.Subscription.cancel(subscription_id, **params)

        return subscription.to_dict()

    def pause_subscription(
        self, subscription_id: str, resumes_at: int | None = None
    ) -> dict[str, Any]:
        """
        Pause a subscription.

        Args:
            subscription_id: Stripe subscription ID
            resumes_at: Unix timestamp when subscription should resume

        Returns:
            Updated subscription object dictionary
        """
        params = {"pause_collection": {"behavior": "void"}}
        if resumes_at:
            params["pause_collection"]["resumes_at"] = resumes_at

        subscription = stripe.Subscription.modify(subscription_id, **params)
        return subscription.to_dict()

    def resume_subscription(self, subscription_id: str) -> dict[str, Any]:
        """
        Resume a paused subscription.

        Args:
            subscription_id: Stripe subscription ID

        Returns:
            Updated subscription object dictionary
        """
        subscription = stripe.Subscription.modify(subscription_id, pause_collection="")
        return subscription.to_dict()

    def list_subscriptions(
        self,
        customer_id: str | None = None,
        status: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        """
        List subscriptions with optional filtering.

        Args:
            customer_id: Filter by customer ID
            status: Filter by status (active, past_due, canceled, etc.)
            limit: Maximum number of subscriptions to return
            starting_after: Cursor for pagination

        Returns:
            List response with subscription objects
        """
        params = {"limit": min(limit, 100)}
        if customer_id:
            params["customer"] = customer_id
        if status:
            params["status"] = status
        if starting_after:
            params["starting_after"] = starting_after

        subscriptions = stripe.Subscription.list(**params)
        return subscriptions.to_dict()

    # ==================== INVOICE MANAGEMENT ====================

    def create_invoice(
        self,
        customer_id: str,
        auto_advance: bool = True,
        collection_method: str = "charge_automatically",
        description: str | None = None,
        metadata: dict[str, str] | None = None,
        days_until_due: int | None = None,
    ) -> dict[str, Any]:
        """
        Create a new invoice.

        Args:
            customer_id: Stripe customer ID
            auto_advance: Whether to auto-finalize
            collection_method: Payment collection method
            description: Invoice description
            metadata: Custom metadata
            days_until_due: Days until due (for send_invoice method)

        Returns:
            Invoice object dictionary
        """
        params = {
            "customer": customer_id,
            "auto_advance": auto_advance,
            "collection_method": collection_method,
        }
        if description:
            params["description"] = description
        if metadata:
            params["metadata"] = metadata
        if days_until_due:
            params["days_until_due"] = days_until_due

        invoice = stripe.Invoice.create(**params)
        return invoice.to_dict()

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        """
        Retrieve an invoice by ID.

        Args:
            invoice_id: Stripe invoice ID

        Returns:
            Invoice object dictionary
        """
        invoice = stripe.Invoice.retrieve(invoice_id)
        return invoice.to_dict()

    def list_invoices(
        self,
        customer_id: str | None = None,
        status: str | None = None,
        subscription_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        """
        List invoices with optional filtering.

        Args:
            customer_id: Filter by customer ID
            status: Filter by status (draft, open, paid, void, uncollectible)
            subscription_id: Filter by subscription ID
            limit: Maximum number to return
            starting_after: Cursor for pagination

        Returns:
            List response with invoice objects
        """
        params = {"limit": min(limit, 100)}
        if customer_id:
            params["customer"] = customer_id
        if status:
            params["status"] = status
        if subscription_id:
            params["subscription"] = subscription_id
        if starting_after:
            params["starting_after"] = starting_after

        invoices = stripe.Invoice.list(**params)
        return invoices.to_dict()

    def pay_invoice(self, invoice_id: str, payment_method: str | None = None) -> dict[str, Any]:
        """
        Pay an invoice.

        Args:
            invoice_id: Stripe invoice ID
            payment_method: Payment method to use

        Returns:
            Paid invoice object dictionary
        """
        params = {}
        if payment_method:
            params["payment_method"] = payment_method

        invoice = stripe.Invoice.pay(invoice_id, **params)
        return invoice.to_dict()

    def void_invoice(self, invoice_id: str) -> dict[str, Any]:
        """
        Void an invoice.

        Args:
            invoice_id: Stripe invoice ID

        Returns:
            Voided invoice object dictionary
        """
        invoice = stripe.Invoice.void_invoice(invoice_id)
        return invoice.to_dict()

    def finalize_invoice(self, invoice_id: str, auto_advance: bool = False) -> dict[str, Any]:
        """
        Finalize a draft invoice.

        Args:
            invoice_id: Stripe invoice ID
            auto_advance: Whether to auto-advance

        Returns:
            Finalized invoice object dictionary
        """
        invoice = stripe.Invoice.finalize_invoice(invoice_id, auto_advance=auto_advance)
        return invoice.to_dict()

    # ==================== PAYMENT METHODS ====================

    def attach_payment_method(self, payment_method_id: str, customer_id: str) -> dict[str, Any]:
        """
        Attach a payment method to a customer.

        Args:
            payment_method_id: Payment method ID
            customer_id: Customer ID

        Returns:
            Payment method object dictionary
        """
        payment_method = stripe.PaymentMethod.attach(payment_method_id, customer=customer_id)
        return payment_method.to_dict()

    def detach_payment_method(self, payment_method_id: str) -> dict[str, Any]:
        """
        Detach a payment method from a customer.

        Args:
            payment_method_id: Payment method ID

        Returns:
            Payment method object dictionary
        """
        payment_method = stripe.PaymentMethod.detach(payment_method_id)
        return payment_method.to_dict()

    def list_payment_methods(
        self, customer_id: str, type: str = "card", limit: int = 10
    ) -> dict[str, Any]:
        """
        List payment methods for a customer.

        Args:
            customer_id: Customer ID
            type: Payment method type (card, bank_account, etc.)
            limit: Maximum number to return

        Returns:
            List response with payment method objects
        """
        payment_methods = stripe.PaymentMethod.list(
            customer=customer_id, type=type, limit=min(limit, 100)
        )
        return payment_methods.to_dict()

    def set_default_payment_method(
        self, customer_id: str, payment_method_id: str
    ) -> dict[str, Any]:
        """
        Set default payment method for a customer.

        Args:
            customer_id: Customer ID
            payment_method_id: Payment method ID

        Returns:
            Updated customer object dictionary
        """
        customer = stripe.Customer.modify(
            customer_id, invoice_settings={"default_payment_method": payment_method_id}
        )
        return customer.to_dict()

    # ==================== PAYMENT INTENTS ====================

    def create_payment_intent(
        self,
        amount: int,
        currency: str,
        customer_id: str | None = None,
        payment_method: str | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
        confirm: bool = False,
        return_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a payment intent.

        Args:
            amount: Amount in smallest currency unit (cents)
            currency: Three-letter ISO currency code
            customer_id: Customer ID
            payment_method: Payment method ID
            description: Description
            metadata: Custom metadata
            confirm: Whether to confirm immediately
            return_url: Return URL after payment

        Returns:
            Payment intent object dictionary
        """
        params = {"amount": amount, "currency": currency.lower()}
        if customer_id:
            params["customer"] = customer_id
        if payment_method:
            params["payment_method"] = payment_method
        if description:
            params["description"] = description
        if metadata:
            params["metadata"] = metadata
        if confirm:
            params["confirm"] = True
        if return_url:
            params["return_url"] = return_url

        payment_intent = stripe.PaymentIntent.create(**params)
        return payment_intent.to_dict()

    def confirm_payment_intent(
        self, payment_intent_id: str, payment_method: str | None = None
    ) -> dict[str, Any]:
        """
        Confirm a payment intent.

        Args:
            payment_intent_id: Payment intent ID
            payment_method: Payment method to use

        Returns:
            Payment intent object dictionary
        """
        params = {}
        if payment_method:
            params["payment_method"] = payment_method

        payment_intent = stripe.PaymentIntent.confirm(payment_intent_id, **params)
        return payment_intent.to_dict()

    def cancel_payment_intent(
        self, payment_intent_id: str, cancellation_reason: str | None = None
    ) -> dict[str, Any]:
        """
        Cancel a payment intent.

        Args:
            payment_intent_id: Payment intent ID
            cancellation_reason: Reason for cancellation

        Returns:
            Payment intent object dictionary
        """
        params = {}
        if cancellation_reason:
            params["cancellation_reason"] = cancellation_reason

        payment_intent = stripe.PaymentIntent.cancel(payment_intent_id, **params)
        return payment_intent.to_dict()

    def capture_payment_intent(
        self, payment_intent_id: str, amount_to_capture: int | None = None
    ) -> dict[str, Any]:
        """
        Capture a payment intent.

        Args:
            payment_intent_id: Payment intent ID
            amount_to_capture: Amount to capture (defaults to full amount)

        Returns:
            Payment intent object dictionary
        """
        params = {}
        if amount_to_capture:
            params["amount_to_capture"] = amount_to_capture

        payment_intent = stripe.PaymentIntent.capture(payment_intent_id, **params)
        return payment_intent.to_dict()

    def list_payment_intents(
        self, customer_id: str | None = None, limit: int = 10, starting_after: str | None = None
    ) -> dict[str, Any]:
        """
        List payment intents.

        Args:
            customer_id: Filter by customer ID
            limit: Maximum number to return
            starting_after: Cursor for pagination

        Returns:
            List response with payment intent objects
        """
        params = {"limit": min(limit, 100)}
        if customer_id:
            params["customer"] = customer_id
        if starting_after:
            params["starting_after"] = starting_after

        payment_intents = stripe.PaymentIntent.list(**params)
        return payment_intents.to_dict()

    # ==================== CHECKOUT SESSIONS ====================

    def create_checkout_session(
        self,
        line_items: list[dict[str, Any]],
        mode: str = "payment",
        success_url: str = None,
        cancel_url: str = None,
        customer_id: str | None = None,
        customer_email: str | None = None,
        metadata: dict[str, str] | None = None,
        expires_at: int | None = None,
    ) -> dict[str, Any]:
        """
        Create a Checkout Session.

        Args:
            line_items: List of line items to purchase
            mode: Mode (payment, setup, or subscription)
            success_url: URL to redirect on success
            cancel_url: URL to redirect on cancel
            customer_id: Existing customer ID
            customer_email: Customer email (for new customers)
            metadata: Custom metadata
            expires_at: Session expiration timestamp

        Returns:
            Checkout session object dictionary
        """
        params = {"line_items": line_items, "mode": mode}
        if success_url:
            params["success_url"] = success_url
        if cancel_url:
            params["cancel_url"] = cancel_url
        if customer_id:
            params["customer"] = customer_id
        elif customer_email:
            params["customer_email"] = customer_email
        if metadata:
            params["metadata"] = metadata
        if expires_at:
            params["expires_at"] = expires_at

        session = stripe.checkout.Session.create(**params)
        return session.to_dict()

    def get_checkout_session(self, session_id: str) -> dict[str, Any]:
        """
        Retrieve a checkout session.

        Args:
            session_id: Checkout session ID

        Returns:
            Checkout session object dictionary
        """
        session = stripe.checkout.Session.retrieve(session_id)
        return session.to_dict()

    def list_checkout_sessions(
        self, limit: int = 10, starting_after: str | None = None
    ) -> dict[str, Any]:
        """
        List checkout sessions.

        Args:
            limit: Maximum number to return
            starting_after: Cursor for pagination

        Returns:
            List response with checkout session objects
        """
        sessions = stripe.checkout.Session.list(
            limit=min(limit, 100), starting_after=starting_after
        )
        return sessions.to_dict()

    def expire_checkout_session(self, session_id: str) -> dict[str, Any]:
        """
        Expire a checkout session.

        Args:
            session_id: Checkout session ID

        Returns:
            Expired session object dictionary
        """
        session = stripe.checkout.Session.expire(session_id)
        return session.to_dict()

    # ==================== PAYMENT LINKS ====================

    def create_payment_link(
        self,
        line_items: list[dict[str, Any]],
        metadata: dict[str, str] | None = None,
        after_completion: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a payment link.

        Args:
            line_items: List of line items
            metadata: Custom metadata
            after_completion: Post-payment behavior configuration

        Returns:
            Payment link object dictionary with URL
        """
        params = {"line_items": line_items}
        if metadata:
            params["metadata"] = metadata
        if after_completion:
            params["after_completion"] = after_completion

        payment_link = stripe.PaymentLink.create(**params)
        return payment_link.to_dict()

    # ==================== PRODUCTS ====================

    def create_product(
        self,
        name: str,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
        images: list[str] | None = None,
        active: bool = True,
    ) -> dict[str, Any]:
        """
        Create a product.

        Args:
            name: Product name
            description: Product description
            metadata: Custom metadata
            images: List of image URLs
            active: Whether product is active

        Returns:
            Product object dictionary
        """
        params = {"name": name, "active": active}
        if description:
            params["description"] = description
        if metadata:
            params["metadata"] = metadata
        if images:
            params["images"] = images

        product = stripe.Product.create(**params)
        return product.to_dict()

    def update_product(
        self,
        product_id: str,
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
        active: bool | None = None,
    ) -> dict[str, Any]:
        """
        Update a product.

        Args:
            product_id: Product ID
            name: New name
            description: New description
            metadata: Updated metadata
            active: New active status

        Returns:
            Updated product object dictionary
        """
        params = {}
        if name:
            params["name"] = name
        if description:
            params["description"] = description
        if metadata:
            params["metadata"] = metadata
        if active is not None:
            params["active"] = active

        product = stripe.Product.modify(product_id, **params)
        return product.to_dict()

    def get_product(self, product_id: str) -> dict[str, Any]:
        """
        Retrieve a product.

        Args:
            product_id: Product ID

        Returns:
            Product object dictionary
        """
        product = stripe.Product.retrieve(product_id)
        return product.to_dict()

    def list_products(
        self, active: bool | None = None, limit: int = 10, starting_after: str | None = None
    ) -> dict[str, Any]:
        """
        List products.

        Args:
            active: Filter by active status
            limit: Maximum number to return
            starting_after: Cursor for pagination

        Returns:
            List response with product objects
        """
        params = {"limit": min(limit, 100)}
        if active is not None:
            params["active"] = active
        if starting_after:
            params["starting_after"] = starting_after

        products = stripe.Product.list(**params)
        return products.to_dict()

    def archive_product(self, product_id: str) -> dict[str, Any]:
        """
        Archive a product (set active=False).

        Args:
            product_id: Product ID

        Returns:
            Updated product object dictionary
        """
        product = stripe.Product.modify(product_id, active=False)
        return product.to_dict()

    # ==================== PRICES ====================

    def create_price(
        self,
        product_id: str,
        unit_amount: int,
        currency: str,
        recurring: dict[str, Any] | None = None,
        metadata: dict[str, str] | None = None,
        active: bool = True,
    ) -> dict[str, Any]:
        """
        Create a price for a product.

        Args:
            product_id: Product ID
            unit_amount: Price in smallest currency unit
            currency: Three-letter ISO currency code
            recurring: Recurring billing configuration (for subscriptions)
            metadata: Custom metadata
            active: Whether price is active

        Returns:
            Price object dictionary
        """
        params = {
            "product": product_id,
            "unit_amount": unit_amount,
            "currency": currency.lower(),
            "active": active,
        }
        if recurring:
            params["recurring"] = recurring
        if metadata:
            params["metadata"] = metadata

        price = stripe.Price.create(**params)
        return price.to_dict()

    def update_price(
        self, price_id: str, metadata: dict[str, str] | None = None, active: bool | None = None
    ) -> dict[str, Any]:
        """
        Update a price.

        Args:
            price_id: Price ID
            metadata: Updated metadata
            active: New active status

        Returns:
            Updated price object dictionary
        """
        params = {}
        if metadata:
            params["metadata"] = metadata
        if active is not None:
            params["active"] = active

        price = stripe.Price.modify(price_id, **params)
        return price.to_dict()

    def get_price(self, price_id: str) -> dict[str, Any]:
        """
        Retrieve a price.

        Args:
            price_id: Price ID

        Returns:
            Price object dictionary
        """
        price = stripe.Price.retrieve(price_id)
        return price.to_dict()

    def list_prices(
        self,
        product_id: str | None = None,
        active: bool | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        """
        List prices.

        Args:
            product_id: Filter by product ID
            active: Filter by active status
            limit: Maximum number to return
            starting_after: Cursor for pagination

        Returns:
            List response with price objects
        """
        params = {"limit": min(limit, 100)}
        if product_id:
            params["product"] = product_id
        if active is not None:
            params["active"] = active
        if starting_after:
            params["starting_after"] = starting_after

        prices = stripe.Price.list(**params)
        return prices.to_dict()

    # ==================== COUPONS ====================

    def create_coupon(
        self,
        percent_off: float | None = None,
        amount_off: int | None = None,
        currency: str | None = None,
        duration: str = "once",
        duration_in_months: int | None = None,
        metadata: dict[str, str] | None = None,
        max_redemptions: int | None = None,
        redeem_by: int | None = None,
    ) -> dict[str, Any]:
        """
        Create a coupon.

        Args:
            percent_off: Percent off (0-100)
            amount_off: Amount off in smallest currency unit
            currency: Currency for amount_off
            duration: Duration (once, repeating, forever)
            duration_in_months: Months for repeating duration
            metadata: Custom metadata
            max_redemptions: Maximum redemptions allowed
            redeem_by: Expiration timestamp

        Returns:
            Coupon object dictionary
        """
        params = {"duration": duration}
        if percent_off:
            params["percent_off"] = percent_off
        elif amount_off and currency:
            params["amount_off"] = amount_off
            params["currency"] = currency.lower()
        else:
            raise ValueError("Must provide either percent_off or (amount_off and currency)")

        if duration_in_months:
            params["duration_in_months"] = duration_in_months
        if metadata:
            params["metadata"] = metadata
        if max_redemptions:
            params["max_redemptions"] = max_redemptions
        if redeem_by:
            params["redeem_by"] = redeem_by

        coupon = stripe.Coupon.create(**params)
        return coupon.to_dict()

    def get_coupon(self, coupon_id: str) -> dict[str, Any]:
        """
        Retrieve a coupon.

        Args:
            coupon_id: Coupon ID

        Returns:
            Coupon object dictionary
        """
        coupon = stripe.Coupon.retrieve(coupon_id)
        return coupon.to_dict()

    def delete_coupon(self, coupon_id: str) -> dict[str, Any]:
        """
        Delete a coupon.

        Args:
            coupon_id: Coupon ID

        Returns:
            Deletion confirmation
        """
        result = stripe.Coupon.delete(coupon_id)
        return result.to_dict()

    # ==================== REFUNDS ====================

    def create_refund(
        self,
        payment_intent_id: str | None = None,
        charge_id: str | None = None,
        amount: int | None = None,
        reason: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Create a refund.

        Args:
            payment_intent_id: Payment intent ID to refund
            charge_id: Charge ID to refund (alternative to payment_intent_id)
            amount: Amount to refund (defaults to full amount)
            reason: Refund reason (duplicate, fraudulent, requested_by_customer)
            metadata: Custom metadata

        Returns:
            Refund object dictionary
        """
        params = {}
        if payment_intent_id:
            params["payment_intent"] = payment_intent_id
        elif charge_id:
            params["charge"] = charge_id
        else:
            raise ValueError("Must provide either payment_intent_id or charge_id")

        if amount:
            params["amount"] = amount
        if reason:
            params["reason"] = reason
        if metadata:
            params["metadata"] = metadata

        refund = stripe.Refund.create(**params)
        return refund.to_dict()

    def get_refund(self, refund_id: str) -> dict[str, Any]:
        """
        Retrieve a refund.

        Args:
            refund_id: Refund ID

        Returns:
            Refund object dictionary
        """
        refund = stripe.Refund.retrieve(refund_id)
        return refund.to_dict()

    def list_refunds(
        self,
        payment_intent_id: str | None = None,
        charge_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        """
        List refunds.

        Args:
            payment_intent_id: Filter by payment intent ID
            charge_id: Filter by charge ID
            limit: Maximum number to return
            starting_after: Cursor for pagination

        Returns:
            List response with refund objects
        """
        params = {"limit": min(limit, 100)}
        if payment_intent_id:
            params["payment_intent"] = payment_intent_id
        if charge_id:
            params["charge"] = charge_id
        if starting_after:
            params["starting_after"] = starting_after

        refunds = stripe.Refund.list(**params)
        return refunds.to_dict()

    def cancel_refund(self, refund_id: str) -> dict[str, Any]:
        """
        Cancel a refund.

        Args:
            refund_id: Refund ID

        Returns:
            Updated refund object dictionary
        """
        refund = stripe.Refund.cancel(refund_id)
        return refund.to_dict()

    # ==================== DISPUTES ====================

    def get_dispute(self, dispute_id: str) -> dict[str, Any]:
        """
        Retrieve a dispute.

        Args:
            dispute_id: Dispute ID

        Returns:
            Dispute object dictionary
        """
        dispute = stripe.Dispute.retrieve(dispute_id)
        return dispute.to_dict()

    def list_disputes(
        self,
        payment_intent_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        """
        List disputes.

        Args:
            payment_intent_id: Filter by payment intent ID
            limit: Maximum number to return
            starting_after: Cursor for pagination

        Returns:
            List response with dispute objects
        """
        params = {"limit": min(limit, 100)}
        if payment_intent_id:
            params["payment_intent"] = payment_intent_id
        if starting_after:
            params["starting_after"] = starting_after

        disputes = stripe.Dispute.list(**params)
        return disputes.to_dict()

    def update_dispute(
        self,
        dispute_id: str,
        evidence: dict[str, Any] | None = None,
        metadata: dict[str, str] | None = None,
        submit: bool = False,
    ) -> dict[str, Any]:
        """
        Update a dispute with evidence.

        Args:
            dispute_id: Dispute ID
            evidence: Evidence dictionary
            metadata: Custom metadata
            submit: Whether to submit dispute

        Returns:
            Updated dispute object dictionary
        """
        params = {}
        if evidence:
            params["evidence"] = evidence
        if metadata:
            params["metadata"] = metadata
        if submit:
            params["submit"] = True

        dispute = stripe.Dispute.modify(dispute_id, **params)
        return dispute.to_dict()

    def close_dispute(self, dispute_id: str) -> dict[str, Any]:
        """
        Close a dispute (accept loss).

        Args:
            dispute_id: Dispute ID

        Returns:
            Closed dispute object dictionary
        """
        dispute = stripe.Dispute.close(dispute_id)
        return dispute.to_dict()

    # ==================== BALANCE TRANSACTIONS ====================

    def get_balance_transaction(self, transaction_id: str) -> dict[str, Any]:
        """
        Retrieve a balance transaction.

        Args:
            transaction_id: Balance transaction ID

        Returns:
            Balance transaction object dictionary
        """
        transaction = stripe.BalanceTransaction.retrieve(transaction_id)
        return transaction.to_dict()

    def list_balance_transactions(
        self,
        type: str | None = None,
        payout: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        """
        List balance transactions.

        Args:
            type: Filter by type (charge, refund, adjustment, etc.)
            payout: Filter by payout ID
            limit: Maximum number to return
            starting_after: Cursor for pagination

        Returns:
            List response with balance transaction objects
        """
        params = {"limit": min(limit, 100)}
        if type:
            params["type"] = type
        if payout:
            params["payout"] = payout
        if starting_after:
            params["starting_after"] = starting_after

        transactions = stripe.BalanceTransaction.list(**params)
        return transactions.to_dict()

    # ==================== PAYOUTS ====================

    def create_payout(
        self,
        amount: int,
        currency: str,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
        destination: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a payout.

        Args:
            amount: Amount in smallest currency unit
            currency: Three-letter ISO currency code
            description: Description
            metadata: Custom metadata
            destination: Destination bank account or debit card ID

        Returns:
            Payout object dictionary
        """
        params = {"amount": amount, "currency": currency.lower()}
        if description:
            params["description"] = description
        if metadata:
            params["metadata"] = metadata
        if destination:
            params["destination"] = destination

        payout = stripe.Payout.create(**params)
        return payout.to_dict()

    def get_payout(self, payout_id: str) -> dict[str, Any]:
        """
        Retrieve a payout.

        Args:
            payout_id: Payout ID

        Returns:
            Payout object dictionary
        """
        payout = stripe.Payout.retrieve(payout_id)
        return payout.to_dict()

    def list_payouts(
        self, status: str | None = None, limit: int = 10, starting_after: str | None = None
    ) -> dict[str, Any]:
        """
        List payouts.

        Args:
            status: Filter by status (paid, pending, in_transit, etc.)
            limit: Maximum number to return
            starting_after: Cursor for pagination

        Returns:
            List response with payout objects
        """
        params = {"limit": min(limit, 100)}
        if status:
            params["status"] = status
        if starting_after:
            params["starting_after"] = starting_after

        payouts = stripe.Payout.list(**params)
        return payouts.to_dict()

    def cancel_payout(self, payout_id: str) -> dict[str, Any]:
        """
        Cancel a payout.

        Args:
            payout_id: Payout ID

        Returns:
            Cancelled payout object dictionary
        """
        payout = stripe.Payout.cancel(payout_id)
        return payout.to_dict()

    # ==================== WEBHOOKS ====================

    def verify_webhook_signature(
        self, payload: str, sig_header: str, webhook_secret: str
    ) -> dict[str, Any]:
        """
        Verify a webhook signature and construct the event.

        Args:
            payload: Raw request body as string
            sig_header: Stripe-Signature header value
            webhook_secret: Webhook endpoint secret

        Returns:
            Verified event object dictionary

        Raises:
            stripe.error.SignatureVerificationError: If signature is invalid
        """
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        return event.to_dict() if hasattr(event, "to_dict") else dict(event)

    def construct_webhook_event(
        self, payload: str, sig_header: str, webhook_secret: str, tolerance: int = 300
    ) -> dict[str, Any]:
        """
        Construct and verify a webhook event with custom tolerance.

        Args:
            payload: Raw request body as string
            sig_header: Stripe-Signature header value
            webhook_secret: Webhook endpoint secret
            tolerance: Maximum age of event in seconds (default: 300)

        Returns:
            Verified event object dictionary

        Raises:
            stripe.error.SignatureVerificationError: If signature is invalid
        """
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret, tolerance=tolerance
        )
        return event.to_dict() if hasattr(event, "to_dict") else dict(event)
