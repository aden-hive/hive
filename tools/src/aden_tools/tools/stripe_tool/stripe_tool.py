"""
Stripe Tool - Online payments, subscriptions, and billing management via Stripe API.

Supports:
- API key authentication (STRIPE_API_KEY)

Use Cases:
- Manage customers and subscriptions
- Create and confirm payment intents
- List and capture charges
- Create and manage invoices and invoice items
- Manage products and prices
- Create payment links
- Process refunds
- Manage coupons
- Inspect account balance and transactions
- List webhook endpoints
- Manage payment methods

API Reference: https://stripe.com/docs/api
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import stripe
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


class _StripeClient:
    """Internal client wrapping Stripe API calls via the official stripe library."""

    def __init__(self, api_key: str):
        self._client = stripe.StripeClient(api_key)

    def _stripe(self) -> stripe.StripeClient:
        return self._client

    # --- Customers ---

    def create_customer(
        self,
        email: str | None = None,
        name: str | None = None,
        phone: str | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if email:
            params["email"] = email
        if name:
            params["name"] = name
        if phone:
            params["phone"] = phone
        if description:
            params["description"] = description
        if metadata:
            params["metadata"] = metadata
        customer = self._stripe().customers.create(params)
        return self._format_customer(customer)

    def get_customer(self, customer_id: str) -> dict[str, Any]:
        customer = self._stripe().customers.retrieve(customer_id)
        return self._format_customer(customer)

    def get_customer_by_email(self, email: str) -> dict[str, Any]:
        result = self._stripe().customers.list({"email": email, "limit": 1})
        items = result.data
        if not items:
            return {"error": f"No customer found with email: {email}"}
        return self._format_customer(items[0])

    def update_customer(
        self,
        customer_id: str,
        email: str | None = None,
        name: str | None = None,
        phone: str | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if email:
            params["email"] = email
        if name:
            params["name"] = name
        if phone:
            params["phone"] = phone
        if description:
            params["description"] = description
        if metadata:
            params["metadata"] = metadata
        customer = self._stripe().customers.update(customer_id, params)
        return self._format_customer(customer)

    def list_customers(
        self,
        limit: int = 10,
        starting_after: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if starting_after:
            params["starting_after"] = starting_after
        if email:
            params["email"] = email
        result = self._stripe().customers.list(params)
        return {
            "has_more": result.has_more,
            "customers": [self._format_customer(c) for c in result.data],
        }

    def _format_customer(self, c: Any) -> dict[str, Any]:
        return {
            "id": c.id,
            "email": c.email,
            "name": c.name,
            "phone": c.phone,
            "description": c.description,
            "created": c.created,
            "currency": c.currency,
            "delinquent": c.delinquent,
            "metadata": c.metadata,
        }

    # --- Subscriptions ---

    def get_subscription(self, subscription_id: str) -> dict[str, Any]:
        sub = self._stripe().subscriptions.retrieve(subscription_id)
        return self._format_subscription(sub)

    def get_subscription_status(self, customer_id: str) -> dict[str, Any]:
        result = self._stripe().subscriptions.list({"customer": customer_id, "limit": 10})
        subs = result.data
        if not subs:
            return {"customer_id": customer_id, "status": "no_subscription", "subscriptions": []}
        return {
            "customer_id": customer_id,
            "status": subs[0].status,
            "subscriptions": [self._format_subscription(s) for s in subs],
        }

    def list_subscriptions(
        self,
        customer_id: str | None = None,
        status: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if customer_id:
            params["customer"] = customer_id
        if status:
            params["status"] = status
        if starting_after:
            params["starting_after"] = starting_after
        result = self._stripe().subscriptions.list(params)
        return {
            "has_more": result.has_more,
            "subscriptions": [self._format_subscription(s) for s in result.data],
        }

    def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        quantity: int = 1,
        trial_period_days: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "customer": customer_id,
            "items": [{"price": price_id, "quantity": quantity}],
        }
        if trial_period_days is not None:
            params["trial_period_days"] = trial_period_days
        if metadata:
            params["metadata"] = metadata
        sub = self._stripe().subscriptions.create(params)
        return self._format_subscription(sub)

    def update_subscription(
        self,
        subscription_id: str,
        price_id: str | None = None,
        quantity: int | None = None,
        metadata: dict[str, str] | None = None,
        cancel_at_period_end: bool | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if metadata:
            params["metadata"] = metadata
        if cancel_at_period_end is not None:
            params["cancel_at_period_end"] = cancel_at_period_end
        if price_id or quantity is not None:
            sub = self._stripe().subscriptions.retrieve(subscription_id)
            if not sub.items.data:
                return {"error": "Subscription has no items to update"}
            item_id = sub.items.data[0].id
            item_params: dict[str, Any] = {"id": item_id}
            if price_id:
                item_params["price"] = price_id
            if quantity is not None:
                item_params["quantity"] = quantity
            params["items"] = [item_params]
        sub = self._stripe().subscriptions.update(subscription_id, params)
        return self._format_subscription(sub)

    def cancel_subscription(
        self,
        subscription_id: str,
        at_period_end: bool = False,
    ) -> dict[str, Any]:
        if at_period_end:
            sub = self._stripe().subscriptions.update(
                subscription_id, {"cancel_at_period_end": True}
            )
        else:
            sub = self._stripe().subscriptions.cancel(subscription_id)
        return self._format_subscription(sub)

    def _format_subscription(self, s: Any) -> dict[str, Any]:
        return {
            "id": s.id,
            "customer": s.customer,
            "status": s.status,
            "current_period_start": s.current_period_start,
            "current_period_end": s.current_period_end,
            "cancel_at_period_end": s.cancel_at_period_end,
            "canceled_at": s.canceled_at,
            "trial_end": s.trial_end,
            "created": s.created,
            "items": [
                {
                    "id": item.id,
                    "price_id": item.price.id,
                    "quantity": item.quantity,
                }
                for item in s.items.data
            ],
            "metadata": s.metadata,
        }

    # --- Payment Intents ---

    def create_payment_intent(
        self,
        amount: int,
        currency: str,
        customer_id: str | None = None,
        description: str | None = None,
        payment_method_types: list[str] | None = None,
        metadata: dict[str, str] | None = None,
        receipt_email: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "amount": amount,
            "currency": currency,
            "payment_method_types": payment_method_types or ["card"],
        }
        if customer_id:
            params["customer"] = customer_id
        if description:
            params["description"] = description
        if metadata:
            params["metadata"] = metadata
        if receipt_email:
            params["receipt_email"] = receipt_email
        pi = self._stripe().payment_intents.create(params)
        return self._format_payment_intent(pi)

    def get_payment_intent(self, payment_intent_id: str) -> dict[str, Any]:
        pi = self._stripe().payment_intents.retrieve(payment_intent_id)
        return self._format_payment_intent(pi)

    def confirm_payment_intent(
        self,
        payment_intent_id: str,
        payment_method: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if payment_method:
            params["payment_method"] = payment_method
        pi = self._stripe().payment_intents.confirm(payment_intent_id, params)
        return self._format_payment_intent(pi)

    def cancel_payment_intent(self, payment_intent_id: str) -> dict[str, Any]:
        pi = self._stripe().payment_intents.cancel(payment_intent_id)
        return self._format_payment_intent(pi)

    def list_payment_intents(
        self,
        customer_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if customer_id:
            params["customer"] = customer_id
        if starting_after:
            params["starting_after"] = starting_after
        result = self._stripe().payment_intents.list(params)
        return {
            "has_more": result.has_more,
            "payment_intents": [self._format_payment_intent(pi) for pi in result.data],
        }

    def _format_payment_intent(self, pi: Any) -> dict[str, Any]:
        return {
            "id": pi.id,
            "amount": pi.amount,
            "amount_received": pi.amount_received,
            "currency": pi.currency,
            "status": pi.status,
            "customer": pi.customer,
            "description": pi.description,
            "receipt_email": pi.receipt_email,
            "payment_method": pi.payment_method,
            "created": pi.created,
            "metadata": pi.metadata,
        }

    # --- Charges ---

    def list_charges(
        self,
        customer_id: str | None = None,
        payment_intent_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if customer_id:
            params["customer"] = customer_id
        if payment_intent_id:
            params["payment_intent"] = payment_intent_id
        if starting_after:
            params["starting_after"] = starting_after
        result = self._stripe().charges.list(params)
        return {
            "has_more": result.has_more,
            "charges": [self._format_charge(c) for c in result.data],
        }

    def get_charge(self, charge_id: str) -> dict[str, Any]:
        charge = self._stripe().charges.retrieve(charge_id)
        return self._format_charge(charge)

    def capture_charge(self, charge_id: str, amount: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if amount is not None:
            params["amount"] = amount
        charge = self._stripe().charges.capture(charge_id, params)
        return self._format_charge(charge)

    def _format_charge(self, c: Any) -> dict[str, Any]:
        return {
            "id": c.id,
            "amount": c.amount,
            "amount_captured": c.amount_captured,
            "amount_refunded": c.amount_refunded,
            "currency": c.currency,
            "status": c.status,
            "paid": c.paid,
            "refunded": c.refunded,
            "customer": c.customer,
            "description": c.description,
            "receipt_email": c.receipt_email,
            "receipt_url": c.receipt_url,
            "payment_intent": c.payment_intent,
            "created": c.created,
            "metadata": c.metadata,
        }

    # --- Refunds ---

    def create_refund(
        self,
        charge_id: str | None = None,
        payment_intent_id: str | None = None,
        amount: int | None = None,
        reason: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if charge_id:
            params["charge"] = charge_id
        if payment_intent_id:
            params["payment_intent"] = payment_intent_id
        if amount is not None:
            params["amount"] = amount
        if reason:
            params["reason"] = reason
        if metadata:
            params["metadata"] = metadata
        refund = self._stripe().refunds.create(params)
        return self._format_refund(refund)

    def get_refund(self, refund_id: str) -> dict[str, Any]:
        refund = self._stripe().refunds.retrieve(refund_id)
        return self._format_refund(refund)

    def list_refunds(
        self,
        charge_id: str | None = None,
        payment_intent_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if charge_id:
            params["charge"] = charge_id
        if payment_intent_id:
            params["payment_intent"] = payment_intent_id
        if starting_after:
            params["starting_after"] = starting_after
        result = self._stripe().refunds.list(params)
        return {
            "has_more": result.has_more,
            "refunds": [self._format_refund(r) for r in result.data],
        }

    def _format_refund(self, r: Any) -> dict[str, Any]:
        return {
            "id": r.id,
            "amount": r.amount,
            "currency": r.currency,
            "status": r.status,
            "charge": r.charge,
            "payment_intent": r.payment_intent,
            "reason": r.reason,
            "created": r.created,
            "metadata": r.metadata,
        }

    # --- Invoices ---

    def list_invoices(
        self,
        customer_id: str | None = None,
        status: str | None = None,
        subscription_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if customer_id:
            params["customer"] = customer_id
        if status:
            params["status"] = status
        if subscription_id:
            params["subscription"] = subscription_id
        if starting_after:
            params["starting_after"] = starting_after
        result = self._stripe().invoices.list(params)
        return {
            "has_more": result.has_more,
            "invoices": [self._format_invoice(inv) for inv in result.data],
        }

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        inv = self._stripe().invoices.retrieve(invoice_id)
        return self._format_invoice(inv)

    def create_invoice(
        self,
        customer_id: str,
        description: str | None = None,
        auto_advance: bool = True,
        collection_method: str = "charge_automatically",
        days_until_due: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "customer": customer_id,
            "auto_advance": auto_advance,
            "collection_method": collection_method,
        }
        if description:
            params["description"] = description
        if days_until_due is not None:
            params["days_until_due"] = days_until_due
        if metadata:
            params["metadata"] = metadata
        inv = self._stripe().invoices.create(params)
        return self._format_invoice(inv)

    def finalize_invoice(self, invoice_id: str) -> dict[str, Any]:
        inv = self._stripe().invoices.finalize_invoice(invoice_id)
        return self._format_invoice(inv)

    def pay_invoice(self, invoice_id: str) -> dict[str, Any]:
        inv = self._stripe().invoices.pay(invoice_id)
        return self._format_invoice(inv)

    def void_invoice(self, invoice_id: str) -> dict[str, Any]:
        inv = self._stripe().invoices.void_invoice(invoice_id)
        return self._format_invoice(inv)

    def _format_invoice(self, inv: Any) -> dict[str, Any]:
        return {
            "id": inv.id,
            "customer": inv.customer,
            "subscription": inv.subscription,
            "status": inv.status,
            "amount_due": inv.amount_due,
            "amount_paid": inv.amount_paid,
            "amount_remaining": inv.amount_remaining,
            "currency": inv.currency,
            "description": inv.description,
            "hosted_invoice_url": inv.hosted_invoice_url,
            "invoice_pdf": inv.invoice_pdf,
            "due_date": inv.due_date,
            "created": inv.created,
            "period_start": inv.period_start,
            "period_end": inv.period_end,
            "metadata": inv.metadata,
        }

    # --- Invoice Items ---

    def create_invoice_item(
        self,
        customer_id: str,
        amount: int,
        currency: str,
        description: str | None = None,
        invoice_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "customer": customer_id,
            "amount": amount,
            "currency": currency,
        }
        if description:
            params["description"] = description
        if invoice_id:
            params["invoice"] = invoice_id
        if metadata:
            params["metadata"] = metadata
        item = self._stripe().invoice_items.create(params)
        return self._format_invoice_item(item)

    def list_invoice_items(
        self,
        customer_id: str | None = None,
        invoice_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if customer_id:
            params["customer"] = customer_id
        if invoice_id:
            params["invoice"] = invoice_id
        if starting_after:
            params["starting_after"] = starting_after
        result = self._stripe().invoice_items.list(params)
        return {
            "has_more": result.has_more,
            "invoice_items": [self._format_invoice_item(i) for i in result.data],
        }

    def delete_invoice_item(self, invoice_item_id: str) -> dict[str, Any]:
        deleted = self._stripe().invoice_items.delete(invoice_item_id)
        return {"id": deleted.id, "deleted": deleted.deleted}

    def _format_invoice_item(self, item: Any) -> dict[str, Any]:
        return {
            "id": item.id,
            "customer": item.customer,
            "invoice": item.invoice,
            "amount": item.amount,
            "currency": item.currency,
            "description": item.description,
            "quantity": item.quantity,
            "created": item.created,
            "metadata": item.metadata,
        }

    # --- Products ---

    def create_product(
        self,
        name: str,
        description: str | None = None,
        active: bool = True,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"name": name, "active": active}
        if description:
            params["description"] = description
        if metadata:
            params["metadata"] = metadata
        product = self._stripe().products.create(params)
        return self._format_product(product)

    def get_product(self, product_id: str) -> dict[str, Any]:
        product = self._stripe().products.retrieve(product_id)
        return self._format_product(product)

    def list_products(
        self,
        active: bool | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if active is not None:
            params["active"] = active
        if starting_after:
            params["starting_after"] = starting_after
        result = self._stripe().products.list(params)
        return {
            "has_more": result.has_more,
            "products": [self._format_product(p) for p in result.data],
        }

    def update_product(
        self,
        product_id: str,
        name: str | None = None,
        description: str | None = None,
        active: bool | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if name:
            params["name"] = name
        if description:
            params["description"] = description
        if active is not None:
            params["active"] = active
        if metadata:
            params["metadata"] = metadata
        product = self._stripe().products.update(product_id, params)
        return self._format_product(product)

    def _format_product(self, p: Any) -> dict[str, Any]:
        return {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "active": p.active,
            "created": p.created,
            "updated": p.updated,
            "metadata": p.metadata,
        }

    # --- Prices ---

    def create_price(
        self,
        unit_amount: int,
        currency: str,
        product_id: str,
        recurring_interval: str | None = None,
        recurring_interval_count: int | None = None,
        nickname: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "unit_amount": unit_amount,
            "currency": currency,
            "product": product_id,
        }
        if recurring_interval:
            params["recurring"] = {"interval": recurring_interval}
            if recurring_interval_count is not None:
                params["recurring"]["interval_count"] = recurring_interval_count
        if nickname:
            params["nickname"] = nickname
        if metadata:
            params["metadata"] = metadata
        price = self._stripe().prices.create(params)
        return self._format_price(price)

    def get_price(self, price_id: str) -> dict[str, Any]:
        price = self._stripe().prices.retrieve(price_id)
        return self._format_price(price)

    def list_prices(
        self,
        product_id: str | None = None,
        active: bool | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if product_id:
            params["product"] = product_id
        if active is not None:
            params["active"] = active
        if starting_after:
            params["starting_after"] = starting_after
        result = self._stripe().prices.list(params)
        return {
            "has_more": result.has_more,
            "prices": [self._format_price(p) for p in result.data],
        }

    def update_price(
        self,
        price_id: str,
        active: bool | None = None,
        nickname: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if active is not None:
            params["active"] = active
        if nickname:
            params["nickname"] = nickname
        if metadata:
            params["metadata"] = metadata
        price = self._stripe().prices.update(price_id, params)
        return self._format_price(price)

    def _format_price(self, p: Any) -> dict[str, Any]:
        recurring = None
        if p.recurring:
            recurring = {
                "interval": p.recurring.interval,
                "interval_count": p.recurring.interval_count,
            }
        return {
            "id": p.id,
            "product": p.product,
            "currency": p.currency,
            "unit_amount": p.unit_amount,
            "nickname": p.nickname,
            "active": p.active,
            "type": p.type,
            "recurring": recurring,
            "created": p.created,
            "metadata": p.metadata,
        }

    # --- Payment Links ---

    def create_payment_link(
        self,
        price_id: str,
        quantity: int = 1,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "line_items": [{"price": price_id, "quantity": quantity}],
        }
        if metadata:
            params["metadata"] = metadata
        link = self._stripe().payment_links.create(params)
        return self._format_payment_link(link)

    def get_payment_link(self, payment_link_id: str) -> dict[str, Any]:
        link = self._stripe().payment_links.retrieve(payment_link_id)
        return self._format_payment_link(link)

    def list_payment_links(
        self,
        active: bool | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if active is not None:
            params["active"] = active
        if starting_after:
            params["starting_after"] = starting_after
        result = self._stripe().payment_links.list(params)
        return {
            "has_more": result.has_more,
            "payment_links": [self._format_payment_link(link) for link in result.data],
        }

    def _format_payment_link(self, link: Any) -> dict[str, Any]:
        return {
            "id": link.id,
            "url": link.url,
            "active": link.active,
            "currency": link.currency,
            "line_items": [
                {
                    "price": item.price.id if item.price else None,
                    "quantity": item.quantity,
                }
                for item in (link.line_items.data if link.line_items else [])
            ],
            "created": link.created,
            "metadata": link.metadata,
        }

    # --- Coupons ---

    def create_coupon(
        self,
        percent_off: float | None = None,
        amount_off: int | None = None,
        currency: str | None = None,
        duration: str = "once",
        duration_in_months: int | None = None,
        name: str | None = None,
        max_redemptions: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"duration": duration}
        if percent_off is not None:
            params["percent_off"] = percent_off
        if amount_off is not None:
            params["amount_off"] = amount_off
        if currency:
            params["currency"] = currency
        if duration_in_months is not None:
            params["duration_in_months"] = duration_in_months
        if name:
            params["name"] = name
        if max_redemptions is not None:
            params["max_redemptions"] = max_redemptions
        if metadata:
            params["metadata"] = metadata
        coupon = self._stripe().coupons.create(params)
        return self._format_coupon(coupon)

    def list_coupons(
        self,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if starting_after:
            params["starting_after"] = starting_after
        result = self._stripe().coupons.list(params)
        return {
            "has_more": result.has_more,
            "coupons": [self._format_coupon(c) for c in result.data],
        }

    def delete_coupon(self, coupon_id: str) -> dict[str, Any]:
        deleted = self._stripe().coupons.delete(coupon_id)
        return {"id": deleted.id, "deleted": deleted.deleted}

    def _format_coupon(self, c: Any) -> dict[str, Any]:
        return {
            "id": c.id,
            "name": c.name,
            "percent_off": c.percent_off,
            "amount_off": c.amount_off,
            "currency": c.currency,
            "duration": c.duration,
            "duration_in_months": c.duration_in_months,
            "max_redemptions": c.max_redemptions,
            "times_redeemed": c.times_redeemed,
            "valid": c.valid,
            "created": c.created,
            "metadata": c.metadata,
        }

    # --- Balance ---

    def get_balance(self) -> dict[str, Any]:
        bal = self._stripe().balance.retrieve()
        return {
            "available": [{"amount": b.amount, "currency": b.currency} for b in bal.available],
            "pending": [{"amount": b.amount, "currency": b.currency} for b in bal.pending],
        }

    def list_balance_transactions(
        self,
        type_filter: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if type_filter:
            params["type"] = type_filter
        if starting_after:
            params["starting_after"] = starting_after
        result = self._stripe().balance_transactions.list(params)
        return {
            "has_more": result.has_more,
            "transactions": [
                {
                    "id": t.id,
                    "amount": t.amount,
                    "currency": t.currency,
                    "net": t.net,
                    "fee": t.fee,
                    "type": t.type,
                    "status": t.status,
                    "description": t.description,
                    "created": t.created,
                }
                for t in result.data
            ],
        }

    # --- Webhook Endpoints ---

    def list_webhook_endpoints(
        self,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if starting_after:
            params["starting_after"] = starting_after
        result = self._stripe().webhook_endpoints.list(params)
        return {
            "has_more": result.has_more,
            "webhook_endpoints": [
                {
                    "id": we.id,
                    "url": we.url,
                    "status": we.status,
                    "enabled_events": we.enabled_events,
                    "created": we.created,
                }
                for we in result.data
            ],
        }

    # --- Payment Methods ---

    def list_payment_methods(
        self,
        customer_id: str,
        type_filter: str = "card",
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "customer": customer_id,
            "type": type_filter,
            "limit": min(limit, 100),
        }
        if starting_after:
            params["starting_after"] = starting_after
        result = self._stripe().payment_methods.list(params)
        return {
            "has_more": result.has_more,
            "payment_methods": [self._format_payment_method(pm) for pm in result.data],
        }

    def get_payment_method(self, payment_method_id: str) -> dict[str, Any]:
        pm = self._stripe().payment_methods.retrieve(payment_method_id)
        return self._format_payment_method(pm)

    def detach_payment_method(self, payment_method_id: str) -> dict[str, Any]:
        pm = self._stripe().payment_methods.detach(payment_method_id)
        return self._format_payment_method(pm)

    def _format_payment_method(self, pm: Any) -> dict[str, Any]:
        card = None
        if pm.card:
            card = {
                "brand": pm.card.brand,
                "last4": pm.card.last4,
                "exp_month": pm.card.exp_month,
                "exp_year": pm.card.exp_year,
                "country": pm.card.country,
            }
        return {
            "id": pm.id,
            "type": pm.type,
            "customer": pm.customer,
            "card": card,
            "created": pm.created,
            "metadata": pm.metadata,
        }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Stripe payment tools with the MCP server."""

    def _get_api_key() -> str | dict[str, str]:
        """Get Stripe API key from credential manager or environment."""
        if credentials is not None:
            api_key = credentials.get("stripe")
            if api_key and isinstance(api_key, str):
                return api_key
        else:
            api_key = os.getenv("STRIPE_API_KEY")
            if api_key:
                return api_key

        return {
            "error": "Stripe credentials not configured",
            "help": (
                "Set STRIPE_API_KEY environment variable. "
                "Get your credentials at https://dashboard.stripe.com/apikeys"
            ),
        }

    def _get_client() -> _StripeClient | dict[str, str]:
        """Get a Stripe client, or return an error dict if no credentials."""
        key = _get_api_key()
        if isinstance(key, dict):
            return key
        return _StripeClient(key)

    def _stripe_error(e: stripe.StripeError) -> dict[str, Any]:
        return {"error": str(e)}

    # --- Customer Tools ---

    @mcp.tool()
    def stripe_create_customer(
        email: str | None = None,
        name: str | None = None,
        phone: str | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        Create a new Stripe customer.

        Args:
            email: Customer email address
            name: Customer full name
            phone: Customer phone number
            description: Arbitrary description for the customer
            metadata: Key-value metadata to attach

        Returns:
            Dict with customer details or error

        Example:
            stripe_create_customer(email="alice@example.com", name="Alice Smith")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_customer(email, name, phone, description, metadata)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_get_customer(customer_id: str) -> dict:
        """
        Retrieve a Stripe customer by ID.

        Args:
            customer_id: Stripe customer ID (e.g., "cus_AbcDefGhijkLmn")

        Returns:
            Dict with customer details or error

        Example:
            stripe_get_customer("cus_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not customer_id or not customer_id.startswith("cus_"):
            return {"error": "Invalid customer_id. Must start with: cus_"}
        try:
            return client.get_customer(customer_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_get_customer_by_email(email: str) -> dict:
        """
        Look up a Stripe customer by email address.

        Args:
            email: Customer email address to search for

        Returns:
            Dict with customer details or error

        Example:
            stripe_get_customer_by_email("alice@example.com")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not email or "@" not in email:
            return {"error": "Invalid email address"}
        try:
            return client.get_customer_by_email(email)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_update_customer(
        customer_id: str,
        email: str | None = None,
        name: str | None = None,
        phone: str | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        Update an existing Stripe customer.

        Args:
            customer_id: Stripe customer ID (e.g., "cus_AbcDefGhijkLmn")
            email: Updated email address
            name: Updated full name
            phone: Updated phone number
            description: Updated description
            metadata: Updated key-value metadata

        Returns:
            Dict with updated customer details or error

        Example:
            stripe_update_customer("cus_AbcDefGhijkLmn", email="new@example.com")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not customer_id or not customer_id.startswith("cus_"):
            return {"error": "Invalid customer_id. Must start with: cus_"}
        try:
            return client.update_customer(customer_id, email, name, phone, description, metadata)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_list_customers(
        limit: int = 10,
        starting_after: str | None = None,
        email: str | None = None,
    ) -> dict:
        """
        List Stripe customers with optional filters.

        Args:
            limit: Number of customers to fetch (1-100, default 10)
            starting_after: Cursor for pagination (last customer ID from previous page)
            email: Filter by email address

        Returns:
            Dict with customer list or error

        Example:
            stripe_list_customers(limit=20)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_customers(limit, starting_after, email)
        except stripe.StripeError as e:
            return _stripe_error(e)

    # --- Subscription Tools ---

    @mcp.tool()
    def stripe_get_subscription(subscription_id: str) -> dict:
        """
        Retrieve a Stripe subscription by ID.

        Args:
            subscription_id: Stripe subscription ID (e.g., "sub_AbcDefGhijkLmn")

        Returns:
            Dict with subscription details or error

        Example:
            stripe_get_subscription("sub_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not subscription_id or not subscription_id.startswith("sub_"):
            return {"error": "Invalid subscription_id. Must start with: sub_"}
        try:
            return client.get_subscription(subscription_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_get_subscription_status(customer_id: str) -> dict:
        """
        Check the subscription status for a customer.

        Args:
            customer_id: Stripe customer ID (e.g., "cus_AbcDefGhijkLmn")

        Returns:
            Dict with status and subscription list or error

        Example:
            stripe_get_subscription_status("cus_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not customer_id or not customer_id.startswith("cus_"):
            return {"error": "Invalid customer_id. Must start with: cus_"}
        try:
            return client.get_subscription_status(customer_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_list_subscriptions(
        customer_id: str | None = None,
        status: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict:
        """
        List Stripe subscriptions with optional filters.

        Args:
            customer_id: Filter by customer ID
            status: Filter by status (active, past_due, canceled, etc.)
            limit: Number of subscriptions to fetch (1-100, default 10)
            starting_after: Cursor for pagination

        Returns:
            Dict with subscription list or error

        Example:
            stripe_list_subscriptions(status="active", limit=20)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_subscriptions(customer_id, status, limit, starting_after)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_create_subscription(
        customer_id: str,
        price_id: str,
        quantity: int = 1,
        trial_period_days: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        Create a new subscription for a customer.

        Args:
            customer_id: Stripe customer ID (e.g., "cus_AbcDefGhijkLmn")
            price_id: Stripe price ID (e.g., "price_AbcDefGhijkLmn")
            quantity: Quantity of the price to subscribe to (default 1)
            trial_period_days: Number of trial days before billing begins
            metadata: Key-value metadata to attach

        Returns:
            Dict with subscription details or error

        Example:
            stripe_create_subscription("cus_AbcDefGhijkLmn", "price_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not customer_id or not customer_id.startswith("cus_"):
            return {"error": "Invalid customer_id. Must start with: cus_"}
        if not price_id or not price_id.startswith("price_"):
            return {"error": "Invalid price_id. Must start with: price_"}
        if quantity < 1:
            return {"error": "Quantity must be at least 1"}
        try:
            return client.create_subscription(
                customer_id, price_id, quantity, trial_period_days, metadata
            )
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_update_subscription(
        subscription_id: str,
        price_id: str | None = None,
        quantity: int | None = None,
        metadata: dict[str, str] | None = None,
        cancel_at_period_end: bool | None = None,
    ) -> dict:
        """
        Update an existing subscription.

        Args:
            subscription_id: Stripe subscription ID (e.g., "sub_AbcDefGhijkLmn")
            price_id: New price ID to switch to
            quantity: Updated quantity
            metadata: Updated key-value metadata
            cancel_at_period_end: If True, cancel at end of current billing period

        Returns:
            Dict with updated subscription details or error

        Example:
            stripe_update_subscription("sub_AbcDefGhijkLmn", cancel_at_period_end=True)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not subscription_id or not subscription_id.startswith("sub_"):
            return {"error": "Invalid subscription_id. Must start with: sub_"}
        try:
            return client.update_subscription(
                subscription_id, price_id, quantity, metadata, cancel_at_period_end
            )
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_cancel_subscription(
        subscription_id: str,
        at_period_end: bool = False,
    ) -> dict:
        """
        Cancel a Stripe subscription.

        Args:
            subscription_id: Stripe subscription ID (e.g., "sub_AbcDefGhijkLmn")
            at_period_end: If True, cancel at end of current billing period instead of immediately

        Returns:
            Dict with updated subscription details or error

        Example:
            stripe_cancel_subscription("sub_AbcDefGhijkLmn", at_period_end=True)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not subscription_id or not subscription_id.startswith("sub_"):
            return {"error": "Invalid subscription_id. Must start with: sub_"}
        try:
            return client.cancel_subscription(subscription_id, at_period_end)
        except stripe.StripeError as e:
            return _stripe_error(e)

    # --- Payment Intent Tools ---

    @mcp.tool()
    def stripe_create_payment_intent(
        amount: int,
        currency: str,
        customer_id: str | None = None,
        description: str | None = None,
        payment_method_types: list[str] | None = None,
        metadata: dict[str, str] | None = None,
        receipt_email: str | None = None,
    ) -> dict:
        """
        Create a PaymentIntent to collect a payment.

        Args:
            amount: Amount in smallest currency unit (e.g., cents for USD)
            currency: ISO 4217 currency code (e.g., "usd", "inr")
            customer_id: Stripe customer ID to attach to the intent
            description: Description of the payment
            payment_method_types: List of payment method types (default ["card"])
            metadata: Key-value metadata to attach
            receipt_email: Email to send receipt to

        Returns:
            Dict with payment intent details including client_secret or error

        Example:
            stripe_create_payment_intent(amount=2000, currency="usd", description="Order #123")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if amount <= 0:
            return {"error": "Amount must be positive"}
        if not currency or len(currency) != 3:
            return {"error": "Currency must be a 3-letter ISO code (e.g., usd, inr)"}
        try:
            return client.create_payment_intent(
                amount,
                currency,
                customer_id,
                description,
                payment_method_types,
                metadata,
                receipt_email,
            )
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_get_payment_intent(payment_intent_id: str) -> dict:
        """
        Retrieve a PaymentIntent by ID.

        Args:
            payment_intent_id: Stripe PaymentIntent ID (e.g., "pi_AbcDefGhijkLmn")

        Returns:
            Dict with payment intent details or error

        Example:
            stripe_get_payment_intent("pi_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not payment_intent_id or not payment_intent_id.startswith("pi_"):
            return {"error": "Invalid payment_intent_id. Must start with: pi_"}
        try:
            return client.get_payment_intent(payment_intent_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_confirm_payment_intent(
        payment_intent_id: str,
        payment_method: str | None = None,
    ) -> dict:
        """
        Confirm a PaymentIntent to attempt payment collection.

        Args:
            payment_intent_id: Stripe PaymentIntent ID (e.g., "pi_AbcDefGhijkLmn")
            payment_method: Payment method ID to use for this payment

        Returns:
            Dict with confirmed payment intent details or error

        Example:
            stripe_confirm_payment_intent("pi_AbcDefGhijkLmn", payment_method="pm_card_visa")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not payment_intent_id or not payment_intent_id.startswith("pi_"):
            return {"error": "Invalid payment_intent_id. Must start with: pi_"}
        try:
            return client.confirm_payment_intent(payment_intent_id, payment_method)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_cancel_payment_intent(payment_intent_id: str) -> dict:
        """
        Cancel a PaymentIntent.

        Args:
            payment_intent_id: Stripe PaymentIntent ID (e.g., "pi_AbcDefGhijkLmn")

        Returns:
            Dict with canceled payment intent details or error

        Example:
            stripe_cancel_payment_intent("pi_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not payment_intent_id or not payment_intent_id.startswith("pi_"):
            return {"error": "Invalid payment_intent_id. Must start with: pi_"}
        try:
            return client.cancel_payment_intent(payment_intent_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_list_payment_intents(
        customer_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict:
        """
        List PaymentIntents with optional filters.

        Args:
            customer_id: Filter by customer ID
            limit: Number of payment intents to fetch (1-100, default 10)
            starting_after: Cursor for pagination

        Returns:
            Dict with payment intent list or error

        Example:
            stripe_list_payment_intents(limit=20)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_payment_intents(customer_id, limit, starting_after)
        except stripe.StripeError as e:
            return _stripe_error(e)

    # --- Charge Tools ---

    @mcp.tool()
    def stripe_list_charges(
        customer_id: str | None = None,
        payment_intent_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict:
        """
        List Stripe charges with optional filters.

        Args:
            customer_id: Filter by customer ID
            payment_intent_id: Filter by payment intent ID
            limit: Number of charges to fetch (1-100, default 10)
            starting_after: Cursor for pagination

        Returns:
            Dict with charge list or error

        Example:
            stripe_list_charges(limit=20)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_charges(customer_id, payment_intent_id, limit, starting_after)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_get_charge(charge_id: str) -> dict:
        """
        Retrieve a charge by ID.

        Args:
            charge_id: Stripe charge ID (e.g., "ch_AbcDefGhijkLmn")

        Returns:
            Dict with charge details or error

        Example:
            stripe_get_charge("ch_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not charge_id or not charge_id.startswith("ch_"):
            return {"error": "Invalid charge_id. Must start with: ch_"}
        try:
            return client.get_charge(charge_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_capture_charge(
        charge_id: str,
        amount: int | None = None,
    ) -> dict:
        """
        Capture an uncaptured charge.

        Args:
            charge_id: Stripe charge ID (e.g., "ch_AbcDefGhijkLmn")
            amount: Amount to capture in smallest currency unit (omit to capture full amount)

        Returns:
            Dict with captured charge details or error

        Example:
            stripe_capture_charge("ch_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not charge_id or not charge_id.startswith("ch_"):
            return {"error": "Invalid charge_id. Must start with: ch_"}
        if amount is not None and amount <= 0:
            return {"error": "Amount must be positive"}
        try:
            return client.capture_charge(charge_id, amount)
        except stripe.StripeError as e:
            return _stripe_error(e)

    # --- Refund Tools ---

    @mcp.tool()
    def stripe_create_refund(
        charge_id: str | None = None,
        payment_intent_id: str | None = None,
        amount: int | None = None,
        reason: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        Create a full or partial refund.

        Args:
            charge_id: Stripe charge ID to refund (e.g., "ch_AbcDefGhijkLmn")
            payment_intent_id: Stripe PaymentIntent ID to refund (e.g., "pi_AbcDefGhijkLmn")
            amount: Amount to refund in smallest currency unit (omit for full refund)
            reason: Reason for refund (duplicate, fraudulent, customer_request)
            metadata: Key-value metadata to attach

        Returns:
            Dict with refund details or error

        Example:
            stripe_create_refund(charge_id="ch_AbcDefGhijkLmn", amount=1000)
            stripe_create_refund(payment_intent_id="pi_AbcDefGhijkLmn", reason="customer_request")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not charge_id and not payment_intent_id:
            return {"error": "Either charge_id or payment_intent_id is required"}
        if amount is not None and amount <= 0:
            return {"error": "Refund amount must be positive"}
        try:
            return client.create_refund(charge_id, payment_intent_id, amount, reason, metadata)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_get_refund(refund_id: str) -> dict:
        """
        Retrieve a refund by ID.

        Args:
            refund_id: Stripe refund ID (e.g., "re_AbcDefGhijkLmn")

        Returns:
            Dict with refund details or error

        Example:
            stripe_get_refund("re_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not refund_id or not refund_id.startswith("re_"):
            return {"error": "Invalid refund_id. Must start with: re_"}
        try:
            return client.get_refund(refund_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_list_refunds(
        charge_id: str | None = None,
        payment_intent_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict:
        """
        List refunds with optional filters.

        Args:
            charge_id: Filter by charge ID
            payment_intent_id: Filter by payment intent ID
            limit: Number of refunds to fetch (1-100, default 10)
            starting_after: Cursor for pagination

        Returns:
            Dict with refund list or error

        Example:
            stripe_list_refunds(charge_id="ch_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_refunds(charge_id, payment_intent_id, limit, starting_after)
        except stripe.StripeError as e:
            return _stripe_error(e)

    # --- Invoice Tools ---

    @mcp.tool()
    def stripe_list_invoices(
        customer_id: str | None = None,
        status: str | None = None,
        subscription_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict:
        """
        List Stripe invoices with optional filters.

        Args:
            customer_id: Filter by customer ID
            status: Filter by status (draft, open, paid, uncollectible, void)
            subscription_id: Filter by subscription ID
            limit: Number of invoices to fetch (1-100, default 10)
            starting_after: Cursor for pagination

        Returns:
            Dict with invoice list or error

        Example:
            stripe_list_invoices(status="open", limit=20)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_invoices(customer_id, status, subscription_id, limit, starting_after)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_get_invoice(invoice_id: str) -> dict:
        """
        Retrieve an invoice by ID.

        Args:
            invoice_id: Stripe invoice ID (e.g., "in_AbcDefGhijkLmn")

        Returns:
            Dict with invoice details or error

        Example:
            stripe_get_invoice("in_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not invoice_id or not invoice_id.startswith("in_"):
            return {"error": "Invalid invoice_id. Must start with: in_"}
        try:
            return client.get_invoice(invoice_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_create_invoice(
        customer_id: str,
        description: str | None = None,
        auto_advance: bool = True,
        collection_method: str = "charge_automatically",
        days_until_due: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        Create a new invoice for a customer.

        Args:
            customer_id: Stripe customer ID (e.g., "cus_AbcDefGhijkLmn")
            description: Description shown on the invoice
            auto_advance: If True, invoice will auto-finalize (default True)
            collection_method: "charge_automatically" or "send_invoice"
              (default "charge_automatically")
            days_until_due: Days until invoice is due (required for send_invoice)
            metadata: Key-value metadata to attach

        Returns:
            Dict with invoice details or error

        Example:
            stripe_create_invoice("cus_AbcDefGhijkLmn", collection_method="send_invoice",
            days_until_due=30)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not customer_id or not customer_id.startswith("cus_"):
            return {"error": "Invalid customer_id. Must start with: cus_"}
        try:
            return client.create_invoice(
                customer_id,
                description,
                auto_advance,
                collection_method,
                days_until_due,
                metadata,
            )
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_finalize_invoice(invoice_id: str) -> dict:
        """
        Finalize a draft invoice, moving it to open status.

        Args:
            invoice_id: Stripe invoice ID (e.g., "in_AbcDefGhijkLmn")

        Returns:
            Dict with finalized invoice details or error

        Example:
            stripe_finalize_invoice("in_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not invoice_id or not invoice_id.startswith("in_"):
            return {"error": "Invalid invoice_id. Must start with: in_"}
        try:
            return client.finalize_invoice(invoice_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_pay_invoice(invoice_id: str) -> dict:
        """
        Attempt to pay an open invoice immediately.

        Args:
            invoice_id: Stripe invoice ID (e.g., "in_AbcDefGhijkLmn")

        Returns:
            Dict with paid invoice details or error

        Example:
            stripe_pay_invoice("in_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not invoice_id or not invoice_id.startswith("in_"):
            return {"error": "Invalid invoice_id. Must start with: in_"}
        try:
            return client.pay_invoice(invoice_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_void_invoice(invoice_id: str) -> dict:
        """
        Void an open invoice, marking it uncollectible.

        Args:
            invoice_id: Stripe invoice ID (e.g., "in_AbcDefGhijkLmn")

        Returns:
            Dict with voided invoice details or error

        Example:
            stripe_void_invoice("in_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not invoice_id or not invoice_id.startswith("in_"):
            return {"error": "Invalid invoice_id. Must start with: in_"}
        try:
            return client.void_invoice(invoice_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    # --- Invoice Item Tools ---

    @mcp.tool()
    def stripe_create_invoice_item(
        customer_id: str,
        amount: int,
        currency: str,
        description: str | None = None,
        invoice_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        Add a line item to an existing or upcoming invoice.

        Args:
            customer_id: Stripe customer ID (e.g., "cus_AbcDefGhijkLmn")
            amount: Amount in smallest currency unit (e.g., cents for USD)
            currency: ISO 4217 currency code (e.g., "usd")
            description: Description of the line item
            invoice_id: Specific invoice to add item to (omit for upcoming invoice)
            metadata: Key-value metadata to attach

        Returns:
            Dict with invoice item details or error

        Example:
            stripe_create_invoice_item("cus_AbcDefGhijkLmn", amount=1500, currency="usd",
              description="Setup fee")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not customer_id or not customer_id.startswith("cus_"):
            return {"error": "Invalid customer_id. Must start with: cus_"}
        if amount == 0:
            return {"error": "Amount must be non-zero"}
        if not currency or len(currency) != 3:
            return {"error": "Currency must be a 3-letter ISO code (e.g., usd)"}
        try:
            return client.create_invoice_item(
                customer_id, amount, currency, description, invoice_id, metadata
            )
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_list_invoice_items(
        customer_id: str | None = None,
        invoice_id: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict:
        """
        List invoice items with optional filters.

        Args:
            customer_id: Filter by customer ID
            invoice_id: Filter by invoice ID
            limit: Number of items to fetch (1-100, default 10)
            starting_after: Cursor for pagination

        Returns:
            Dict with invoice item list or error

        Example:
            stripe_list_invoice_items(customer_id="cus_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_invoice_items(customer_id, invoice_id, limit, starting_after)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_delete_invoice_item(invoice_item_id: str) -> dict:
        """
        Delete a pending invoice item.

        Args:
            invoice_item_id: Stripe invoice item ID (e.g., "ii_AbcDefGhijkLmn")

        Returns:
            Dict with deletion confirmation or error

        Example:
            stripe_delete_invoice_item("ii_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not invoice_item_id or not invoice_item_id.startswith("ii_"):
            return {"error": "Invalid invoice_item_id. Must start with: ii_"}
        try:
            return client.delete_invoice_item(invoice_item_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    # --- Product Tools ---

    @mcp.tool()
    def stripe_create_product(
        name: str,
        description: str | None = None,
        active: bool = True,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        Create a new Stripe product.

        Args:
            name: Product name
            description: Product description
            active: Whether the product is available (default True)
            metadata: Key-value metadata to attach

        Returns:
            Dict with product details or error

        Example:
            stripe_create_product(name="Premium Plan", description="Full access subscription")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not name:
            return {"error": "Product name is required"}
        try:
            return client.create_product(name, description, active, metadata)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_get_product(product_id: str) -> dict:
        """
        Retrieve a product by ID.

        Args:
            product_id: Stripe product ID (e.g., "prod_AbcDefGhijkLmn")

        Returns:
            Dict with product details or error

        Example:
            stripe_get_product("prod_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not product_id or not product_id.startswith("prod_"):
            return {"error": "Invalid product_id. Must start with: prod_"}
        try:
            return client.get_product(product_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_list_products(
        active: bool | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict:
        """
        List Stripe products with optional filters.

        Args:
            active: Filter by active status
            limit: Number of products to fetch (1-100, default 10)
            starting_after: Cursor for pagination

        Returns:
            Dict with product list or error

        Example:
            stripe_list_products(active=True, limit=20)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_products(active, limit, starting_after)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_update_product(
        product_id: str,
        name: str | None = None,
        description: str | None = None,
        active: bool | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        Update an existing product.

        Args:
            product_id: Stripe product ID (e.g., "prod_AbcDefGhijkLmn")
            name: Updated product name
            description: Updated description
            active: Updated active status
            metadata: Updated key-value metadata

        Returns:
            Dict with updated product details or error

        Example:
            stripe_update_product("prod_AbcDefGhijkLmn", name="Premium Plan v2")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not product_id or not product_id.startswith("prod_"):
            return {"error": "Invalid product_id. Must start with: prod_"}
        try:
            return client.update_product(product_id, name, description, active, metadata)
        except stripe.StripeError as e:
            return _stripe_error(e)

    # --- Price Tools ---

    @mcp.tool()
    def stripe_create_price(
        unit_amount: int,
        currency: str,
        product_id: str,
        recurring_interval: str | None = None,
        recurring_interval_count: int | None = None,
        nickname: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        Create a price for a product.

        Args:
            unit_amount: Amount in smallest currency unit (e.g., cents for USD)
            currency: ISO 4217 currency code (e.g., "usd")
            product_id: Stripe product ID (e.g., "prod_AbcDefGhijkLmn")
            recurring_interval: Billing interval for subscriptions (day, week, month, year)
            recurring_interval_count: Number of intervals between billing cycles
            nickname: Friendly label for the price
            metadata: Key-value metadata to attach

        Returns:
            Dict with price details or error

        Example:
            stripe_create_price(unit_amount=999, currency="usd", product_id="prod_AbcDefGhijkLmn",
              recurring_interval="month")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if unit_amount <= 0:
            return {"error": "unit_amount must be positive"}
        if not currency or len(currency) != 3:
            return {"error": "Currency must be a 3-letter ISO code (e.g., usd)"}
        if not product_id or not product_id.startswith("prod_"):
            return {"error": "Invalid product_id. Must start with: prod_"}
        try:
            return client.create_price(
                unit_amount,
                currency,
                product_id,
                recurring_interval,
                recurring_interval_count,
                nickname,
                metadata,
            )
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_get_price(price_id: str) -> dict:
        """
        Retrieve a price by ID.

        Args:
            price_id: Stripe price ID (e.g., "price_AbcDefGhijkLmn")

        Returns:
            Dict with price details or error

        Example:
            stripe_get_price("price_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not price_id or not price_id.startswith("price_"):
            return {"error": "Invalid price_id. Must start with: price_"}
        try:
            return client.get_price(price_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_list_prices(
        product_id: str | None = None,
        active: bool | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict:
        """
        List Stripe prices with optional filters.

        Args:
            product_id: Filter by product ID
            active: Filter by active status
            limit: Number of prices to fetch (1-100, default 10)
            starting_after: Cursor for pagination

        Returns:
            Dict with price list or error

        Example:
            stripe_list_prices(product_id="prod_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_prices(product_id, active, limit, starting_after)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_update_price(
        price_id: str,
        active: bool | None = None,
        nickname: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        Update an existing price (only active, nickname, and metadata can be updated).

        Args:
            price_id: Stripe price ID (e.g., "price_AbcDefGhijkLmn")
            active: Updated active status
            nickname: Updated friendly label
            metadata: Updated key-value metadata

        Returns:
            Dict with updated price details or error

        Example:
            stripe_update_price("price_AbcDefGhijkLmn", active=False)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not price_id or not price_id.startswith("price_"):
            return {"error": "Invalid price_id. Must start with: price_"}
        try:
            return client.update_price(price_id, active, nickname, metadata)
        except stripe.StripeError as e:
            return _stripe_error(e)

    # --- Payment Link Tools ---

    @mcp.tool()
    def stripe_create_payment_link(
        price_id: str,
        quantity: int = 1,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        Create a shareable payment link for a price.

        Args:
            price_id: Stripe price ID (e.g., "price_AbcDefGhijkLmn")
            quantity: Quantity of the price to include (default 1)
            metadata: Key-value metadata to attach

        Returns:
            Dict with payment link details including URL or error

        Example:
            stripe_create_payment_link("price_AbcDefGhijkLmn", quantity=1)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not price_id or not price_id.startswith("price_"):
            return {"error": "Invalid price_id. Must start with: price_"}
        if quantity < 1:
            return {"error": "Quantity must be at least 1"}
        try:
            return client.create_payment_link(price_id, quantity, metadata)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_get_payment_link(payment_link_id: str) -> dict:
        """
        Retrieve a payment link by ID.

        Args:
            payment_link_id: Stripe payment link ID (e.g., "plink_AbcDefGhijkLmn")

        Returns:
            Dict with payment link details or error

        Example:
            stripe_get_payment_link("plink_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not payment_link_id or not payment_link_id.startswith("plink_"):
            return {"error": "Invalid payment_link_id. Must start with: plink_"}
        try:
            return client.get_payment_link(payment_link_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_list_payment_links(
        active: bool | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict:
        """
        List payment links with optional filters.

        Args:
            active: Filter by active status
            limit: Number of payment links to fetch (1-100, default 10)
            starting_after: Cursor for pagination

        Returns:
            Dict with payment link list or error

        Example:
            stripe_list_payment_links(active=True)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_payment_links(active, limit, starting_after)
        except stripe.StripeError as e:
            return _stripe_error(e)

    # --- Coupon Tools ---

    @mcp.tool()
    def stripe_create_coupon(
        percent_off: float | None = None,
        amount_off: int | None = None,
        currency: str | None = None,
        duration: str = "once",
        duration_in_months: int | None = None,
        name: str | None = None,
        max_redemptions: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        Create a discount coupon.

        Args:
            percent_off: Percentage discount (e.g., 25.0 for 25% off)
            amount_off: Fixed discount in smallest currency unit
            currency: Currency for amount_off (required when using amount_off)
            duration: How long the coupon applies: "once", "repeating", or "forever"
            duration_in_months: Months the coupon applies (required for "repeating")
            name: Friendly name for the coupon
            max_redemptions: Maximum number of times the coupon can be redeemed
            metadata: Key-value metadata to attach

        Returns:
            Dict with coupon details or error

        Example:
            stripe_create_coupon(percent_off=20.0, duration="once", name="WELCOME20")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if percent_off is None and amount_off is None:
            return {"error": "Either percent_off or amount_off is required"}
        if percent_off is not None and amount_off is not None:
            return {"error": "Only one of percent_off or amount_off can be specified"}
        if amount_off is not None and not currency:
            return {"error": "currency is required when using amount_off"}
        if duration not in ("once", "repeating", "forever"):
            return {"error": "duration must be one of: once, repeating, forever"}
        if duration == "repeating" and duration_in_months is None:
            return {"error": "duration_in_months is required when duration is repeating"}
        try:
            return client.create_coupon(
                percent_off,
                amount_off,
                currency,
                duration,
                duration_in_months,
                name,
                max_redemptions,
                metadata,
            )
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_list_coupons(
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict:
        """
        List all coupons.

        Args:
            limit: Number of coupons to fetch (1-100, default 10)
            starting_after: Cursor for pagination

        Returns:
            Dict with coupon list or error

        Example:
            stripe_list_coupons(limit=20)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_coupons(limit, starting_after)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_delete_coupon(coupon_id: str) -> dict:
        """
        Delete a coupon.

        Args:
            coupon_id: Stripe coupon ID

        Returns:
            Dict with deletion confirmation or error

        Example:
            stripe_delete_coupon("WELCOME20")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not coupon_id:
            return {"error": "coupon_id is required"}
        try:
            return client.delete_coupon(coupon_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    # --- Balance Tools ---

    @mcp.tool()
    def stripe_get_balance() -> dict:
        """
        Retrieve the current account balance.

        Returns:
            Dict with available and pending balance amounts or error

        Example:
            stripe_get_balance()
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_balance()
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_list_balance_transactions(
        type_filter: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict:
        """
        List balance transactions (payouts, charges, refunds, etc.).

        Args:
            type_filter: Filter by type (charge, refund, payout, payment, etc.)
            limit: Number of transactions to fetch (1-100, default 10)
            starting_after: Cursor for pagination

        Returns:
            Dict with transaction list or error

        Example:
            stripe_list_balance_transactions(type_filter="charge", limit=20)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_balance_transactions(type_filter, limit, starting_after)
        except stripe.StripeError as e:
            return _stripe_error(e)

    # --- Webhook Endpoint Tools ---

    @mcp.tool()
    def stripe_list_webhook_endpoints(
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict:
        """
        List all configured webhook endpoints.

        Args:
            limit: Number of endpoints to fetch (1-100, default 10)
            starting_after: Cursor for pagination

        Returns:
            Dict with webhook endpoint list or error

        Example:
            stripe_list_webhook_endpoints()
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_webhook_endpoints(limit, starting_after)
        except stripe.StripeError as e:
            return _stripe_error(e)

    # --- Payment Method Tools ---

    @mcp.tool()
    def stripe_list_payment_methods(
        customer_id: str,
        type_filter: str = "card",
        limit: int = 10,
        starting_after: str | None = None,
    ) -> dict:
        """
        List payment methods attached to a customer.

        Args:
            customer_id: Stripe customer ID (e.g., "cus_AbcDefGhijkLmn")
            type_filter: Payment method type to list (default "card")
            limit: Number of payment methods to fetch (1-100, default 10)
            starting_after: Cursor for pagination

        Returns:
            Dict with payment method list or error

        Example:
            stripe_list_payment_methods("cus_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not customer_id or not customer_id.startswith("cus_"):
            return {"error": "Invalid customer_id. Must start with: cus_"}
        try:
            return client.list_payment_methods(customer_id, type_filter, limit, starting_after)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_get_payment_method(payment_method_id: str) -> dict:
        """
        Retrieve a payment method by ID.

        Args:
            payment_method_id: Stripe payment method ID (e.g., "pm_AbcDefGhijkLmn")

        Returns:
            Dict with payment method details or error

        Example:
            stripe_get_payment_method("pm_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not payment_method_id or not payment_method_id.startswith("pm_"):
            return {"error": "Invalid payment_method_id. Must start with: pm_"}
        try:
            return client.get_payment_method(payment_method_id)
        except stripe.StripeError as e:
            return _stripe_error(e)

    @mcp.tool()
    def stripe_detach_payment_method(payment_method_id: str) -> dict:
        """
        Detach a payment method from its customer.

        Args:
            payment_method_id: Stripe payment method ID (e.g., "pm_AbcDefGhijkLmn")

        Returns:
            Dict with detached payment method details or error

        Example:
            stripe_detach_payment_method("pm_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if not payment_method_id or not payment_method_id.startswith("pm_"):
            return {"error": "Invalid payment_method_id. Must start with: pm_"}
        try:
            return client.detach_payment_method(payment_method_id)
        except stripe.StripeError as e:
            return _stripe_error(e)
