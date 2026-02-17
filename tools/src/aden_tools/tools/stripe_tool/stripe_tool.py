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

    api_key: str | None = Field(default=None, description="Stripe API key (secret key)")
    api_version: str | None = Field(default="2024-11-20.acacia", description="Stripe API version")
    webhook_secret: str | None = Field(default=None, description="Stripe Webhook Signing Secret")
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
            # Attempt to load from environment, but do NOT raise if missing.
            # This allows the tool to register successfully in CI environments.
            api_key = os.environ.get("STRIPE_API_KEY") or os.environ.get("STRIPE_SECRET_KEY")
            webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

            # We create the config even if api_key is None
            config = StripeToolConfig(api_key=api_key, webhook_secret=webhook_secret)

        self.config = config

        # Only configure the stripe library if we actually have a key
        if self.config.api_key:
            stripe.api_key = self.config.api_key
            if self.config.api_version:
                stripe.api_version = self.config.api_version
            stripe.max_network_retries = self.config.max_retries

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
        """
        if not self.config.api_key:
            return {
                "error": "Stripe API key not configured. Set STRIPE_API_KEY environment variable."
            }

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
        """Retrieve a customer by email address."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        customers = stripe.Customer.list(email=email, limit=1)
        if customers.data:
            return customers.data[0].to_dict()
        return None

    def get_customer_by_id(self, customer_id: str) -> dict[str, Any]:
        """Retrieve a customer by ID."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Update an existing customer."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """List customers with optional filtering and pagination."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Delete a customer."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        result = stripe.Customer.delete(customer_id)
        return result.to_dict()

    # ==================== SUBSCRIPTION MANAGEMENT ====================

    def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        quantity: int = 1,
        payment_behavior: str = "default_incomplete",
        collection_method: str = "charge_automatically",
        days_until_due: int | None = None,
        default_payment_method: str | None = None,
        trial_period_days: int | None = None,
        metadata: dict[str, str] | None = None,
        proration_behavior: str = "create_prorations",
    ) -> dict[str, Any]:
        """Create a new subscription for a customer."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        # Handle simplified single item creation
        items = [{"price": price_id, "quantity": quantity}]

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

    def get_subscription_status(self, subscription_id: str) -> dict[str, Any]:
        """Get the status of a subscription."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        subscription = stripe.Subscription.retrieve(subscription_id)
        # Return full object, caller can check .status
        return subscription.to_dict()

    def get_subscription(self, subscription_id: str) -> dict[str, Any]:
        """Retrieve a subscription by ID."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        subscription = stripe.Subscription.retrieve(subscription_id)
        return subscription.to_dict()

    def update_subscription(
        self,
        subscription_id: str,
        items: list[dict[str, Any]] | None = None,
        price_id: str | None = None,
        quantity: int | None = None,
        default_payment_method: str | None = None,
        metadata: dict[str, str] | None = None,
        proration_behavior: str = "create_prorations",
        cancel_at_period_end: bool | None = None,
    ) -> dict[str, Any]:
        """Update an existing subscription."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        params = {"proration_behavior": proration_behavior}

        # Handle logic for price/quantity update shortcut
        if price_id and quantity:
            # We need to retrieve the subscription to find the item ID to update
            sub = stripe.Subscription.retrieve(subscription_id)
            if sub.items.data:
                # Assuming single item subscription for simple update
                item_id = sub.items.data[0].id
                params["items"] = [{"id": item_id, "price": price_id, "quantity": quantity}]
        elif items:
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
        cancel_at_period_end: bool = False,
    ) -> dict[str, Any]:
        """Cancel a subscription."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        if cancel_at_period_end:
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
        """Pause a subscription."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        params = {"pause_collection": {"behavior": "void"}}
        if resumes_at:
            params["pause_collection"]["resumes_at"] = resumes_at

        subscription = stripe.Subscription.modify(subscription_id, **params)
        return subscription.to_dict()

    def resume_subscription(self, subscription_id: str) -> dict[str, Any]:
        """Resume a paused subscription."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        subscription = stripe.Subscription.modify(subscription_id, pause_collection="")
        return subscription.to_dict()

    def list_subscriptions(
        self,
        customer_id: str | None = None,
        status: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        """List subscriptions with optional filtering."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Create a new invoice."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Retrieve an invoice by ID."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """List invoices with optional filtering."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Pay an invoice."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        params = {}
        if payment_method:
            params["payment_method"] = payment_method

        invoice = stripe.Invoice.pay(invoice_id, **params)
        return invoice.to_dict()

    def void_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Void an invoice."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        invoice = stripe.Invoice.void_invoice(invoice_id)
        return invoice.to_dict()

    def finalize_invoice(self, invoice_id: str, auto_advance: bool = False) -> dict[str, Any]:
        """Finalize a draft invoice."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        invoice = stripe.Invoice.finalize_invoice(invoice_id, auto_advance=auto_advance)
        return invoice.to_dict()

    # ==================== PAYMENT METHODS ====================

    def attach_payment_method(self, payment_method_id: str, customer_id: str) -> dict[str, Any]:
        """Attach a payment method to a customer."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        payment_method = stripe.PaymentMethod.attach(payment_method_id, customer=customer_id)
        return payment_method.to_dict()

    def detach_payment_method(self, payment_method_id: str) -> dict[str, Any]:
        """Detach a payment method from a customer."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        payment_method = stripe.PaymentMethod.detach(payment_method_id)
        return payment_method.to_dict()

    def list_payment_methods(
        self, customer_id: str, type: str = "card", limit: int = 10
    ) -> dict[str, Any]:
        """List payment methods for a customer."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        payment_methods = stripe.PaymentMethod.list(
            customer=customer_id, type=type, limit=min(limit, 100)
        )
        return payment_methods.to_dict()

    def set_default_payment_method(
        self, customer_id: str, payment_method_id: str
    ) -> dict[str, Any]:
        """Set default payment method for a customer."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Create a payment intent."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Confirm a payment intent."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        params = {}
        if payment_method:
            params["payment_method"] = payment_method

        payment_intent = stripe.PaymentIntent.confirm(payment_intent_id, **params)
        return payment_intent.to_dict()

    def cancel_payment_intent(
        self, payment_intent_id: str, cancellation_reason: str | None = None
    ) -> dict[str, Any]:
        """Cancel a payment intent."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        params = {}
        if cancellation_reason:
            params["cancellation_reason"] = cancellation_reason

        payment_intent = stripe.PaymentIntent.cancel(payment_intent_id, **params)
        return payment_intent.to_dict()

    def capture_payment_intent(
        self, payment_intent_id: str, amount_to_capture: int | None = None
    ) -> dict[str, Any]:
        """Capture a payment intent."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        params = {}
        if amount_to_capture:
            params["amount_to_capture"] = amount_to_capture

        payment_intent = stripe.PaymentIntent.capture(payment_intent_id, **params)
        return payment_intent.to_dict()

    def list_payment_intents(
        self, customer_id: str | None = None, limit: int = 10, starting_after: str | None = None
    ) -> dict[str, Any]:
        """List payment intents."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        price_id: str,
        success_url: str,
        cancel_url: str,
        customer_id: str | None = None,
        customer_email: str | None = None,
        quantity: int = 1,
        mode: str = "payment",
        metadata: dict[str, str] | None = None,
        expires_at: int | None = None,
    ) -> dict[str, Any]:
        """Create a Checkout Session."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        # Handle simplified line items
        line_items = [{"price": price_id, "quantity": quantity}]

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
        """Retrieve a checkout session."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        session = stripe.checkout.Session.retrieve(session_id)
        return session.to_dict()

    def list_checkout_sessions(
        self, limit: int = 10, starting_after: str | None = None
    ) -> dict[str, Any]:
        """List checkout sessions."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        sessions = stripe.checkout.Session.list(
            limit=min(limit, 100), starting_after=starting_after
        )
        return sessions.to_dict()

    def expire_checkout_session(self, session_id: str) -> dict[str, Any]:
        """Expire a checkout session."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        session = stripe.checkout.Session.expire(session_id)
        return session.to_dict()

    # ==================== PAYMENT LINKS ====================

    def create_payment_link(
        self,
        price_id: str,
        quantity: int = 1,
        metadata: dict[str, str] | None = None,
        after_completion: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a payment link."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        # Handle simplified line items
        line_items = [{"price": price_id, "quantity": quantity}]

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
        """Create a product."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Update a product."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Retrieve a product."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        product = stripe.Product.retrieve(product_id)
        return product.to_dict()

    def list_products(
        self, active: bool | None = None, limit: int = 10, starting_after: str | None = None
    ) -> dict[str, Any]:
        """List products."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        params = {"limit": min(limit, 100)}
        if active is not None:
            params["active"] = active
        if starting_after:
            params["starting_after"] = starting_after

        products = stripe.Product.list(**params)
        return products.to_dict()

    def archive_product(self, product_id: str) -> dict[str, Any]:
        """Archive a product (set active=False)."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        product = stripe.Product.modify(product_id, active=False)
        return product.to_dict()

    # ==================== PRICES ====================

    def create_price(
        self,
        product_id: str,
        unit_amount: int,
        currency: str,
        recurring_interval: str | None = None,
        recurring_interval_count: int = 1,
        metadata: dict[str, str] | None = None,
        active: bool = True,
    ) -> dict[str, Any]:
        """Create a price for a product."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        params = {
            "product": product_id,
            "unit_amount": unit_amount,
            "currency": currency.lower(),
            "active": active,
        }
        if recurring_interval:
            params["recurring"] = {
                "interval": recurring_interval,
                "interval_count": recurring_interval_count,
            }
        if metadata:
            params["metadata"] = metadata

        price = stripe.Price.create(**params)
        return price.to_dict()

    def update_price(
        self, price_id: str, metadata: dict[str, str] | None = None, active: bool | None = None
    ) -> dict[str, Any]:
        """Update a price."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        params = {}
        if metadata:
            params["metadata"] = metadata
        if active is not None:
            params["active"] = active

        price = stripe.Price.modify(price_id, **params)
        return price.to_dict()

    def get_price(self, price_id: str) -> dict[str, Any]:
        """Retrieve a price."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        price = stripe.Price.retrieve(price_id)
        return price.to_dict()

    def list_prices(
        self,
        product_id: str | None = None,
        active: bool | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        """List prices."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Create a coupon."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        params = {"duration": duration}
        if percent_off:
            params["percent_off"] = percent_off
        elif amount_off and currency:
            params["amount_off"] = amount_off
            params["currency"] = currency.lower()
        else:
            return {"error": "Must provide either percent_off or (amount_off and currency)"}

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
        """Retrieve a coupon."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        coupon = stripe.Coupon.retrieve(coupon_id)
        return coupon.to_dict()

    def delete_coupon(self, coupon_id: str) -> dict[str, Any]:
        """Delete a coupon."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Create a refund."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        params = {}
        if payment_intent_id:
            params["payment_intent"] = payment_intent_id
        elif charge_id:
            params["charge"] = charge_id
        else:
            return {"error": "Must provide either payment_intent_id or charge_id"}

        if amount:
            params["amount"] = amount
        if reason:
            params["reason"] = reason
        if metadata:
            params["metadata"] = metadata

        refund = stripe.Refund.create(**params)
        return refund.to_dict()

    def get_refund(self, refund_id: str) -> dict[str, Any]:
        """Retrieve a refund."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        refund = stripe.Refund.retrieve(refund_id)
        return refund.to_dict()

    def list_refunds(
        self,
        payment_intent_id: str | None = None,
        charge_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        """List refunds."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Cancel a refund."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        refund = stripe.Refund.cancel(refund_id)
        return refund.to_dict()

    # ==================== DISPUTES ====================

    def get_dispute(self, dispute_id: str) -> dict[str, Any]:
        """Retrieve a dispute."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        dispute = stripe.Dispute.retrieve(dispute_id)
        return dispute.to_dict()

    def list_disputes(
        self,
        payment_intent_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        """List disputes."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Update a dispute."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Close a dispute."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        dispute = stripe.Dispute.close(dispute_id)
        return dispute.to_dict()

    # ==================== BALANCE TRANSACTIONS ====================

    def get_balance_transaction(self, transaction_id: str) -> dict[str, Any]:
        """Retrieve a balance transaction."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        transaction = stripe.BalanceTransaction.retrieve(transaction_id)
        return transaction.to_dict()

    def list_balance_transactions(
        self,
        type: str | None = None,
        payout: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        """List balance transactions."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Create a payout."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

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
        """Retrieve a payout."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        payout = stripe.Payout.retrieve(payout_id)
        return payout.to_dict()

    def list_payouts(
        self, status: str | None = None, limit: int = 10, starting_after: str | None = None
    ) -> dict[str, Any]:
        """List payouts."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        params = {"limit": min(limit, 100)}
        if status:
            params["status"] = status
        if starting_after:
            params["starting_after"] = starting_after

        payouts = stripe.Payout.list(**params)
        return payouts.to_dict()

    def cancel_payout(self, payout_id: str) -> dict[str, Any]:
        """Cancel a payout."""
        if not self.config.api_key:
            return {"error": "Stripe API key not configured."}

        payout = stripe.Payout.cancel(payout_id)
        return payout.to_dict()

    # ==================== WEBHOOKS ====================

    def verify_webhook_signature(
        self, payload: str, sig_header: str, webhook_secret: str
    ) -> dict[str, Any]:
        """Verify a webhook signature."""
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
            return event.to_dict() if hasattr(event, "to_dict") else dict(event)
        except Exception as e:
            return {"error": f"Webhook verification failed: {str(e)}"}

    def construct_webhook_event(
        self, payload: str, sig_header: str, webhook_secret: str, tolerance: int = 300
    ) -> dict[str, Any]:
        """Construct a webhook event."""
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret, tolerance=tolerance
            )
            return event.to_dict() if hasattr(event, "to_dict") else dict(event)
        except Exception as e:
            return {"error": f"Webhook construction failed: {str(e)}"}
