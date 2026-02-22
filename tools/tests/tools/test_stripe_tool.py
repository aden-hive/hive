"""
Tests for Stripe payment tool.

Covers:
- _StripeClient methods (all customer, subscription, payment intent, charge,
  refund, invoice, invoice item, product, price, payment link, coupon,
  balance, webhook endpoint, and payment method operations)
- Error handling (StripeError, invalid credentials, missing credentials)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 52 MCP tool functions
- Input validation
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import stripe

from aden_tools.tools.stripe_tool.stripe_tool import (
    _StripeClient,
    register_tools,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stripe_list(items: list, has_more: bool = False):
    """Return a mock object that looks like a stripe ListObject."""
    obj = MagicMock()
    obj.data = items
    obj.has_more = has_more
    return obj


def _customer(**kwargs):
    defaults = {
        "id": "cus_test123",
        "email": "test@example.com",
        "name": "Test User",
        "phone": "+10000000000",
        "description": "A test customer",
        "created": 1700000000,
        "currency": "usd",
        "delinquent": False,
        "metadata": {},
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _subscription(**kwargs):
    defaults = {
        "id": "sub_test123",
        "customer": "cus_test123",
        "status": "active",
        "current_period_start": 1700000000,
        "current_period_end": 1702592000,
        "cancel_at_period_end": False,
        "canceled_at": None,
        "trial_end": None,
        "created": 1700000000,
        "metadata": {},
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    item = MagicMock()
    item.id = "si_test123"
    item.price.id = "price_test123"
    item.quantity = 1
    obj.items = MagicMock()
    obj.items.data = [item]
    return obj


def _payment_intent(**kwargs):
    defaults = {
        "id": "pi_test123",
        "amount": 2000,
        "amount_received": 0,
        "currency": "usd",
        "status": "requires_payment_method",
        "customer": "cus_test123",
        "description": "Test payment",
        "receipt_email": None,
        "payment_method": None,
        "created": 1700000000,
        "metadata": {},
        "client_secret": "pi_test123_secret_abc",
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _charge(**kwargs):
    defaults = {
        "id": "ch_test123",
        "amount": 2000,
        "amount_captured": 2000,
        "amount_refunded": 0,
        "currency": "usd",
        "status": "succeeded",
        "paid": True,
        "refunded": False,
        "customer": "cus_test123",
        "description": "Test charge",
        "receipt_email": None,
        "receipt_url": "https://pay.stripe.com/receipts/test",
        "payment_intent": "pi_test123",
        "created": 1700000000,
        "metadata": {},
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _refund(**kwargs):
    defaults = {
        "id": "re_test123",
        "amount": 1000,
        "currency": "usd",
        "status": "succeeded",
        "charge": "ch_test123",
        "payment_intent": "pi_test123",
        "reason": "customer_request",
        "created": 1700000000,
        "metadata": {},
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _invoice(**kwargs):
    defaults = {
        "id": "in_test123",
        "customer": "cus_test123",
        "subscription": "sub_test123",
        "status": "open",
        "amount_due": 2000,
        "amount_paid": 0,
        "amount_remaining": 2000,
        "currency": "usd",
        "description": "Test invoice",
        "hosted_invoice_url": "https://invoice.stripe.com/test",
        "invoice_pdf": "https://invoice.stripe.com/test/pdf",
        "due_date": None,
        "created": 1700000000,
        "period_start": 1700000000,
        "period_end": 1702592000,
        "metadata": {},
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _invoice_item(**kwargs):
    defaults = {
        "id": "ii_test123",
        "customer": "cus_test123",
        "invoice": "in_test123",
        "amount": 1500,
        "currency": "usd",
        "description": "Setup fee",
        "quantity": 1,
        "created": 1700000000,
        "metadata": {},
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _product(**kwargs):
    defaults = {
        "id": "prod_test123",
        "name": "Premium Plan",
        "description": "Full access",
        "active": True,
        "created": 1700000000,
        "updated": 1700000000,
        "metadata": {},
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _price(**kwargs):
    rec = MagicMock()
    rec.interval = "month"
    rec.interval_count = 1
    defaults = {
        "id": "price_test123",
        "product": "prod_test123",
        "currency": "usd",
        "unit_amount": 999,
        "nickname": "Monthly",
        "active": True,
        "type": "recurring",
        "recurring": rec,
        "created": 1700000000,
        "metadata": {},
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _payment_link(**kwargs):
    line_item = MagicMock()
    line_item.price.id = "price_test123"
    line_item.quantity = 1
    line_items_obj = MagicMock()
    line_items_obj.data = [line_item]
    defaults = {
        "id": "plink_test123",
        "url": "https://buy.stripe.com/test",
        "active": True,
        "currency": "usd",
        "line_items": line_items_obj,
        "created": 1700000000,
        "metadata": {},
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _coupon(**kwargs):
    defaults = {
        "id": "WELCOME20",
        "name": "Welcome 20% off",
        "percent_off": 20.0,
        "amount_off": None,
        "currency": None,
        "duration": "once",
        "duration_in_months": None,
        "max_redemptions": None,
        "times_redeemed": 0,
        "valid": True,
        "created": 1700000000,
        "metadata": {},
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _payment_method(**kwargs):
    card = MagicMock()
    card.brand = "visa"
    card.last4 = "4242"
    card.exp_month = 12
    card.exp_year = 2025
    card.country = "US"
    defaults = {
        "id": "pm_test123",
        "type": "card",
        "customer": "cus_test123",
        "card": card,
        "created": 1700000000,
        "metadata": {},
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


# ---------------------------------------------------------------------------
# _StripeClient unit tests
# ---------------------------------------------------------------------------


class TestStripeClientCustomers:
    def setup_method(self):
        self.client = _StripeClient("sk_test_key123")

    def _mock_stripe(self):
        return MagicMock()

    def test_create_customer(self):
        sc = self._mock_stripe()
        sc.customers.create.return_value = _customer()
        with patch.object(self.client, "_client", sc):
            result = self.client.create_customer(
                email="test@example.com",
                name="Test User",
                phone="+10000000000",
                description="desc",
                metadata={"key": "val"},
            )
        sc.customers.create.assert_called_once_with(
            {
                "email": "test@example.com",
                "name": "Test User",
                "phone": "+10000000000",
                "description": "desc",
                "metadata": {"key": "val"},
            }
        )
        assert result["id"] == "cus_test123"
        assert result["email"] == "test@example.com"

    def test_create_customer_minimal(self):
        sc = self._mock_stripe()
        sc.customers.create.return_value = _customer(email=None, name=None)
        with patch.object(self.client, "_client", sc):
            self.client.create_customer()
        call_args = sc.customers.create.call_args[0][0]
        assert "email" not in call_args
        assert "name" not in call_args

    def test_get_customer(self):
        sc = self._mock_stripe()
        sc.customers.retrieve.return_value = _customer()
        with patch.object(self.client, "_client", sc):
            result = self.client.get_customer("cus_test123")
        sc.customers.retrieve.assert_called_once_with("cus_test123")
        assert result["id"] == "cus_test123"

    def test_get_customer_by_email_found(self):
        sc = self._mock_stripe()
        sc.customers.list.return_value = _make_stripe_list([_customer()])
        with patch.object(self.client, "_client", sc):
            result = self.client.get_customer_by_email("test@example.com")
        sc.customers.list.assert_called_once_with({"email": "test@example.com", "limit": 1})
        assert result["id"] == "cus_test123"

    def test_get_customer_by_email_not_found(self):
        sc = self._mock_stripe()
        sc.customers.list.return_value = _make_stripe_list([])
        with patch.object(self.client, "_client", sc):
            result = self.client.get_customer_by_email("nobody@example.com")
        assert "error" in result
        assert "nobody@example.com" in result["error"]

    def test_update_customer(self):
        sc = self._mock_stripe()
        sc.customers.update.return_value = _customer(name="Updated Name")
        with patch.object(self.client, "_client", sc):
            result = self.client.update_customer("cus_test123", name="Updated Name")
        sc.customers.update.assert_called_once_with("cus_test123", {"name": "Updated Name"})
        assert result["name"] == "Updated Name"

    def test_list_customers(self):
        sc = self._mock_stripe()
        sc.customers.list.return_value = _make_stripe_list([_customer(), _customer(id="cus_456")])
        with patch.object(self.client, "_client", sc):
            result = self.client.list_customers(limit=10)
        assert len(result["customers"]) == 2
        assert result["has_more"] is False

    def test_list_customers_limit_capped(self):
        sc = self._mock_stripe()
        sc.customers.list.return_value = _make_stripe_list([])
        with patch.object(self.client, "_client", sc):
            self.client.list_customers(limit=500)
        call_params = sc.customers.list.call_args[0][0]
        assert call_params["limit"] == 100


class TestStripeClientSubscriptions:
    def setup_method(self):
        self.client = _StripeClient("sk_test_key123")

    def _mock_stripe(self):
        return MagicMock()

    def test_get_subscription(self):
        sc = self._mock_stripe()
        sc.subscriptions.retrieve.return_value = _subscription()
        with patch.object(self.client, "_client", sc):
            result = self.client.get_subscription("sub_test123")
        sc.subscriptions.retrieve.assert_called_once_with("sub_test123")
        assert result["id"] == "sub_test123"
        assert result["status"] == "active"

    def test_get_subscription_status_active(self):
        sc = self._mock_stripe()
        sc.subscriptions.list.return_value = _make_stripe_list([_subscription()])
        with patch.object(self.client, "_client", sc):
            result = self.client.get_subscription_status("cus_test123")
        assert result["status"] == "active"
        assert result["customer_id"] == "cus_test123"
        assert len(result["subscriptions"]) == 1

    def test_get_subscription_status_no_subscription(self):
        sc = self._mock_stripe()
        sc.subscriptions.list.return_value = _make_stripe_list([])
        with patch.object(self.client, "_client", sc):
            result = self.client.get_subscription_status("cus_test123")
        assert result["status"] == "no_subscription"
        assert result["subscriptions"] == []

    def test_list_subscriptions(self):
        sc = self._mock_stripe()
        sc.subscriptions.list.return_value = _make_stripe_list([_subscription()])
        with patch.object(self.client, "_client", sc):
            result = self.client.list_subscriptions(customer_id="cus_test123", status="active")
        call_params = sc.subscriptions.list.call_args[0][0]
        assert call_params["customer"] == "cus_test123"
        assert call_params["status"] == "active"
        assert len(result["subscriptions"]) == 1

    def test_create_subscription(self):
        sc = self._mock_stripe()
        sc.subscriptions.create.return_value = _subscription()
        with patch.object(self.client, "_client", sc):
            result = self.client.create_subscription(
                "cus_test123",
                "price_test123",
                quantity=1,
                trial_period_days=14,
            )
        call_params = sc.subscriptions.create.call_args[0][0]
        assert call_params["customer"] == "cus_test123"
        assert call_params["items"][0]["price"] == "price_test123"
        assert call_params["trial_period_days"] == 14
        assert result["id"] == "sub_test123"

    def test_update_subscription_metadata(self):
        sc = self._mock_stripe()
        sc.subscriptions.update.return_value = _subscription()
        with patch.object(self.client, "_client", sc):
            self.client.update_subscription(
                "sub_test123", metadata={"note": "updated"}, cancel_at_period_end=True
            )
        call_params = sc.subscriptions.update.call_args[0][1]
        assert call_params["cancel_at_period_end"] is True
        assert call_params["metadata"] == {"note": "updated"}

    def test_update_subscription_quantity_only(self):
        sc = self._mock_stripe()
        sc.subscriptions.retrieve.return_value = _subscription()
        sc.subscriptions.update.return_value = _subscription()
        with patch.object(self.client, "_client", sc):
            self.client.update_subscription("sub_test123", quantity=3)
        call_params = sc.subscriptions.update.call_args[0][1]
        assert call_params["items"][0]["quantity"] == 3
        assert "price" not in call_params["items"][0]

    def test_update_subscription_no_items_returns_error(self):
        sc = self._mock_stripe()
        empty_sub = _subscription()
        empty_sub.items.data = []
        sc.subscriptions.retrieve.return_value = empty_sub
        with patch.object(self.client, "_client", sc):
            result = self.client.update_subscription("sub_test123", price_id="price_new")
        assert "error" in result
        assert "no items" in result["error"]

    def test_cancel_subscription_immediately(self):
        sc = self._mock_stripe()
        sc.subscriptions.cancel.return_value = _subscription(status="canceled")
        with patch.object(self.client, "_client", sc):
            result = self.client.cancel_subscription("sub_test123", at_period_end=False)
        sc.subscriptions.cancel.assert_called_once_with("sub_test123")
        assert result["status"] == "canceled"

    def test_cancel_subscription_at_period_end(self):
        sc = self._mock_stripe()
        sc.subscriptions.update.return_value = _subscription(cancel_at_period_end=True)
        with patch.object(self.client, "_client", sc):
            result = self.client.cancel_subscription("sub_test123", at_period_end=True)
        sc.subscriptions.update.assert_called_once_with(
            "sub_test123", {"cancel_at_period_end": True}
        )
        assert result["cancel_at_period_end"] is True


class TestStripeClientPaymentIntents:
    def setup_method(self):
        self.client = _StripeClient("sk_test_key123")

    def _mock_stripe(self):
        return MagicMock()

    def test_create_payment_intent(self):
        sc = self._mock_stripe()
        sc.payment_intents.create.return_value = _payment_intent()
        with patch.object(self.client, "_client", sc):
            result = self.client.create_payment_intent(
                amount=2000,
                currency="usd",
                customer_id="cus_test123",
                description="Test",
                receipt_email="test@example.com",
            )
        call_params = sc.payment_intents.create.call_args[0][0]
        assert call_params["amount"] == 2000
        assert call_params["currency"] == "usd"
        assert call_params["customer"] == "cus_test123"
        assert result["id"] == "pi_test123"
        assert result["status"] == "requires_payment_method"

    def test_get_payment_intent(self):
        sc = self._mock_stripe()
        sc.payment_intents.retrieve.return_value = _payment_intent()
        with patch.object(self.client, "_client", sc):
            result = self.client.get_payment_intent("pi_test123")
        sc.payment_intents.retrieve.assert_called_once_with("pi_test123")
        assert result["id"] == "pi_test123"

    def test_confirm_payment_intent(self):
        sc = self._mock_stripe()
        sc.payment_intents.confirm.return_value = _payment_intent(status="succeeded")
        with patch.object(self.client, "_client", sc):
            result = self.client.confirm_payment_intent("pi_test123", payment_method="pm_card_visa")
        sc.payment_intents.confirm.assert_called_once_with(
            "pi_test123", {"payment_method": "pm_card_visa"}
        )
        assert result["status"] == "succeeded"

    def test_cancel_payment_intent(self):
        sc = self._mock_stripe()
        sc.payment_intents.cancel.return_value = _payment_intent(status="canceled")
        with patch.object(self.client, "_client", sc):
            result = self.client.cancel_payment_intent("pi_test123")
        sc.payment_intents.cancel.assert_called_once_with("pi_test123")
        assert result["status"] == "canceled"

    def test_list_payment_intents(self):
        sc = self._mock_stripe()
        sc.payment_intents.list.return_value = _make_stripe_list([_payment_intent()])
        with patch.object(self.client, "_client", sc):
            result = self.client.list_payment_intents(customer_id="cus_test123", limit=5)
        call_params = sc.payment_intents.list.call_args[0][0]
        assert call_params["customer"] == "cus_test123"
        assert call_params["limit"] == 5
        assert len(result["payment_intents"]) == 1


class TestStripeClientCharges:
    def setup_method(self):
        self.client = _StripeClient("sk_test_key123")

    def _mock_stripe(self):
        return MagicMock()

    def test_list_charges(self):
        sc = self._mock_stripe()
        sc.charges.list.return_value = _make_stripe_list([_charge(), _charge(id="ch_456")])
        with patch.object(self.client, "_client", sc):
            result = self.client.list_charges(customer_id="cus_test123")
        call_params = sc.charges.list.call_args[0][0]
        assert call_params["customer"] == "cus_test123"
        assert len(result["charges"]) == 2

    def test_get_charge(self):
        sc = self._mock_stripe()
        sc.charges.retrieve.return_value = _charge()
        with patch.object(self.client, "_client", sc):
            result = self.client.get_charge("ch_test123")
        sc.charges.retrieve.assert_called_once_with("ch_test123")
        assert result["id"] == "ch_test123"
        assert result["paid"] is True

    def test_capture_charge(self):
        sc = self._mock_stripe()
        sc.charges.capture.return_value = _charge(amount_captured=2000)
        with patch.object(self.client, "_client", sc):
            result = self.client.capture_charge("ch_test123", amount=2000)
        sc.charges.capture.assert_called_once_with("ch_test123", {"amount": 2000})
        assert result["amount_captured"] == 2000

    def test_capture_charge_full(self):
        sc = self._mock_stripe()
        sc.charges.capture.return_value = _charge()
        with patch.object(self.client, "_client", sc):
            self.client.capture_charge("ch_test123")
        call_params = sc.charges.capture.call_args[0][1]
        assert call_params == {}  # No amount means full capture


class TestStripeClientRefunds:
    def setup_method(self):
        self.client = _StripeClient("sk_test_key123")

    def _mock_stripe(self):
        return MagicMock()

    def test_create_refund_by_charge(self):
        sc = self._mock_stripe()
        sc.refunds.create.return_value = _refund()
        with patch.object(self.client, "_client", sc):
            result = self.client.create_refund(charge_id="ch_test123", amount=1000)
        call_params = sc.refunds.create.call_args[0][0]
        assert call_params["charge"] == "ch_test123"
        assert call_params["amount"] == 1000
        assert result["id"] == "re_test123"

    def test_create_refund_by_payment_intent(self):
        sc = self._mock_stripe()
        sc.refunds.create.return_value = _refund()
        with patch.object(self.client, "_client", sc):
            self.client.create_refund(
                payment_intent_id="pi_test123",
                reason="customer_request",
            )
        call_params = sc.refunds.create.call_args[0][0]
        assert call_params["payment_intent"] == "pi_test123"
        assert call_params["reason"] == "customer_request"

    def test_get_refund(self):
        sc = self._mock_stripe()
        sc.refunds.retrieve.return_value = _refund()
        with patch.object(self.client, "_client", sc):
            result = self.client.get_refund("re_test123")
        sc.refunds.retrieve.assert_called_once_with("re_test123")
        assert result["id"] == "re_test123"

    def test_list_refunds(self):
        sc = self._mock_stripe()
        sc.refunds.list.return_value = _make_stripe_list([_refund()])
        with patch.object(self.client, "_client", sc):
            result = self.client.list_refunds(charge_id="ch_test123", limit=10)
        call_params = sc.refunds.list.call_args[0][0]
        assert call_params["charge"] == "ch_test123"
        assert len(result["refunds"]) == 1


class TestStripeClientInvoices:
    def setup_method(self):
        self.client = _StripeClient("sk_test_key123")

    def _mock_stripe(self):
        return MagicMock()

    def test_list_invoices(self):
        sc = self._mock_stripe()
        sc.invoices.list.return_value = _make_stripe_list([_invoice(), _invoice(id="in_456")])
        with patch.object(self.client, "_client", sc):
            result = self.client.list_invoices(customer_id="cus_test123", status="open")
        call_params = sc.invoices.list.call_args[0][0]
        assert call_params["customer"] == "cus_test123"
        assert call_params["status"] == "open"
        assert len(result["invoices"]) == 2

    def test_get_invoice(self):
        sc = self._mock_stripe()
        sc.invoices.retrieve.return_value = _invoice()
        with patch.object(self.client, "_client", sc):
            result = self.client.get_invoice("in_test123")
        sc.invoices.retrieve.assert_called_once_with("in_test123")
        assert result["id"] == "in_test123"
        assert result["hosted_invoice_url"] == "https://invoice.stripe.com/test"

    def test_create_invoice(self):
        sc = self._mock_stripe()
        sc.invoices.create.return_value = _invoice(status="draft")
        with patch.object(self.client, "_client", sc):
            self.client.create_invoice(
                "cus_test123",
                description="Test invoice",
                collection_method="send_invoice",
                days_until_due=30,
            )
        call_params = sc.invoices.create.call_args[0][0]
        assert call_params["customer"] == "cus_test123"
        assert call_params["collection_method"] == "send_invoice"
        assert call_params["days_until_due"] == 30

    def test_finalize_invoice(self):
        sc = self._mock_stripe()
        sc.invoices.finalize_invoice.return_value = _invoice(status="open")
        with patch.object(self.client, "_client", sc):
            result = self.client.finalize_invoice("in_test123")
        sc.invoices.finalize_invoice.assert_called_once_with("in_test123")
        assert result["status"] == "open"

    def test_pay_invoice(self):
        sc = self._mock_stripe()
        sc.invoices.pay.return_value = _invoice(status="paid", amount_paid=2000)
        with patch.object(self.client, "_client", sc):
            result = self.client.pay_invoice("in_test123")
        sc.invoices.pay.assert_called_once_with("in_test123")
        assert result["status"] == "paid"

    def test_void_invoice(self):
        sc = self._mock_stripe()
        sc.invoices.void_invoice.return_value = _invoice(status="void")
        with patch.object(self.client, "_client", sc):
            result = self.client.void_invoice("in_test123")
        sc.invoices.void_invoice.assert_called_once_with("in_test123")
        assert result["status"] == "void"


class TestStripeClientInvoiceItems:
    def setup_method(self):
        self.client = _StripeClient("sk_test_key123")

    def _mock_stripe(self):
        return MagicMock()

    def test_create_invoice_item(self):
        sc = self._mock_stripe()
        sc.invoice_items.create.return_value = _invoice_item()
        with patch.object(self.client, "_client", sc):
            result = self.client.create_invoice_item(
                customer_id="cus_test123",
                amount=1500,
                currency="usd",
                description="Setup fee",
                invoice_id="in_test123",
            )
        call_params = sc.invoice_items.create.call_args[0][0]
        assert call_params["customer"] == "cus_test123"
        assert call_params["amount"] == 1500
        assert call_params["invoice"] == "in_test123"
        assert result["id"] == "ii_test123"

    def test_list_invoice_items(self):
        sc = self._mock_stripe()
        sc.invoice_items.list.return_value = _make_stripe_list([_invoice_item()])
        with patch.object(self.client, "_client", sc):
            result = self.client.list_invoice_items(
                customer_id="cus_test123", invoice_id="in_test123"
            )
        call_params = sc.invoice_items.list.call_args[0][0]
        assert call_params["customer"] == "cus_test123"
        assert call_params["invoice"] == "in_test123"
        assert len(result["invoice_items"]) == 1

    def test_delete_invoice_item(self):
        sc = self._mock_stripe()
        deleted = MagicMock()
        deleted.id = "ii_test123"
        deleted.deleted = True
        sc.invoice_items.delete.return_value = deleted
        with patch.object(self.client, "_client", sc):
            result = self.client.delete_invoice_item("ii_test123")
        sc.invoice_items.delete.assert_called_once_with("ii_test123")
        assert result["deleted"] is True
        assert result["id"] == "ii_test123"


class TestStripeClientProducts:
    def setup_method(self):
        self.client = _StripeClient("sk_test_key123")

    def _mock_stripe(self):
        return MagicMock()

    def test_create_product(self):
        sc = self._mock_stripe()
        sc.products.create.return_value = _product()
        with patch.object(self.client, "_client", sc):
            result = self.client.create_product(
                name="Premium Plan",
                description="Full access",
                active=True,
                metadata={"tier": "premium"},
            )
        call_params = sc.products.create.call_args[0][0]
        assert call_params["name"] == "Premium Plan"
        assert call_params["active"] is True
        assert result["id"] == "prod_test123"

    def test_get_product(self):
        sc = self._mock_stripe()
        sc.products.retrieve.return_value = _product()
        with patch.object(self.client, "_client", sc):
            result = self.client.get_product("prod_test123")
        sc.products.retrieve.assert_called_once_with("prod_test123")
        assert result["name"] == "Premium Plan"

    def test_list_products(self):
        sc = self._mock_stripe()
        sc.products.list.return_value = _make_stripe_list([_product(), _product(id="prod_456")])
        with patch.object(self.client, "_client", sc):
            result = self.client.list_products(active=True)
        call_params = sc.products.list.call_args[0][0]
        assert call_params["active"] is True
        assert len(result["products"]) == 2

    def test_update_product(self):
        sc = self._mock_stripe()
        sc.products.update.return_value = _product(name="Updated Plan", active=False)
        with patch.object(self.client, "_client", sc):
            self.client.update_product("prod_test123", name="Updated Plan", active=False)
        call_params = sc.products.update.call_args[0][1]
        assert call_params["name"] == "Updated Plan"
        assert call_params["active"] is False


class TestStripeClientPrices:
    def setup_method(self):
        self.client = _StripeClient("sk_test_key123")

    def _mock_stripe(self):
        return MagicMock()

    def test_create_price_recurring(self):
        sc = self._mock_stripe()
        sc.prices.create.return_value = _price()
        with patch.object(self.client, "_client", sc):
            result = self.client.create_price(
                unit_amount=999,
                currency="usd",
                product_id="prod_test123",
                recurring_interval="month",
            )
        call_params = sc.prices.create.call_args[0][0]
        assert call_params["recurring"]["interval"] == "month"
        assert result["id"] == "price_test123"

    def test_create_price_one_time(self):
        sc = self._mock_stripe()
        sc.prices.create.return_value = _price(recurring=None, type="one_time")
        with patch.object(self.client, "_client", sc):
            self.client.create_price(
                unit_amount=4999,
                currency="usd",
                product_id="prod_test123",
            )
        call_params = sc.prices.create.call_args[0][0]
        assert "recurring" not in call_params

    def test_get_price(self):
        sc = self._mock_stripe()
        sc.prices.retrieve.return_value = _price()
        with patch.object(self.client, "_client", sc):
            result = self.client.get_price("price_test123")
        sc.prices.retrieve.assert_called_once_with("price_test123")
        assert result["unit_amount"] == 999
        assert result["recurring"]["interval"] == "month"

    def test_list_prices(self):
        sc = self._mock_stripe()
        sc.prices.list.return_value = _make_stripe_list([_price()])
        with patch.object(self.client, "_client", sc):
            result = self.client.list_prices(product_id="prod_test123", active=True)
        call_params = sc.prices.list.call_args[0][0]
        assert call_params["product"] == "prod_test123"
        assert call_params["active"] is True
        assert len(result["prices"]) == 1

    def test_update_price(self):
        sc = self._mock_stripe()
        sc.prices.update.return_value = _price(active=False, nickname="Legacy")
        with patch.object(self.client, "_client", sc):
            self.client.update_price("price_test123", active=False, nickname="Legacy")
        call_params = sc.prices.update.call_args[0][1]
        assert call_params["active"] is False
        assert call_params["nickname"] == "Legacy"


class TestStripeClientPaymentLinks:
    def setup_method(self):
        self.client = _StripeClient("sk_test_key123")

    def _mock_stripe(self):
        return MagicMock()

    def test_create_payment_link(self):
        sc = self._mock_stripe()
        sc.payment_links.create.return_value = _payment_link()
        with patch.object(self.client, "_client", sc):
            result = self.client.create_payment_link("price_test123", quantity=2)
        call_params = sc.payment_links.create.call_args[0][0]
        assert call_params["line_items"][0]["price"] == "price_test123"
        assert call_params["line_items"][0]["quantity"] == 2
        assert result["id"] == "plink_test123"
        assert result["url"] == "https://buy.stripe.com/test"

    def test_get_payment_link(self):
        sc = self._mock_stripe()
        sc.payment_links.retrieve.return_value = _payment_link()
        with patch.object(self.client, "_client", sc):
            result = self.client.get_payment_link("plink_test123")
        sc.payment_links.retrieve.assert_called_once_with("plink_test123")
        assert result["active"] is True

    def test_list_payment_links(self):
        sc = self._mock_stripe()
        sc.payment_links.list.return_value = _make_stripe_list([_payment_link()])
        with patch.object(self.client, "_client", sc):
            result = self.client.list_payment_links(active=True)
        call_params = sc.payment_links.list.call_args[0][0]
        assert call_params["active"] is True
        assert len(result["payment_links"]) == 1


class TestStripeClientCoupons:
    def setup_method(self):
        self.client = _StripeClient("sk_test_key123")

    def _mock_stripe(self):
        return MagicMock()

    def test_create_coupon_percent_off(self):
        sc = self._mock_stripe()
        sc.coupons.create.return_value = _coupon()
        with patch.object(self.client, "_client", sc):
            result = self.client.create_coupon(
                percent_off=20.0,
                duration="once",
                name="WELCOME20",
            )
        call_params = sc.coupons.create.call_args[0][0]
        assert call_params["percent_off"] == 20.0
        assert call_params["duration"] == "once"
        assert result["id"] == "WELCOME20"

    def test_create_coupon_amount_off(self):
        sc = self._mock_stripe()
        sc.coupons.create.return_value = _coupon(percent_off=None, amount_off=500, currency="usd")
        with patch.object(self.client, "_client", sc):
            self.client.create_coupon(
                amount_off=500,
                currency="usd",
                duration="forever",
            )
        call_params = sc.coupons.create.call_args[0][0]
        assert call_params["amount_off"] == 500
        assert call_params["currency"] == "usd"

    def test_create_coupon_repeating(self):
        sc = self._mock_stripe()
        sc.coupons.create.return_value = _coupon(duration="repeating", duration_in_months=3)
        with patch.object(self.client, "_client", sc):
            self.client.create_coupon(
                percent_off=10.0,
                duration="repeating",
                duration_in_months=3,
            )
        call_params = sc.coupons.create.call_args[0][0]
        assert call_params["duration_in_months"] == 3

    def test_list_coupons(self):
        sc = self._mock_stripe()
        sc.coupons.list.return_value = _make_stripe_list([_coupon()])
        with patch.object(self.client, "_client", sc):
            result = self.client.list_coupons(limit=5)
        assert len(result["coupons"]) == 1

    def test_delete_coupon(self):
        sc = self._mock_stripe()
        deleted = MagicMock()
        deleted.id = "WELCOME20"
        deleted.deleted = True
        sc.coupons.delete.return_value = deleted
        with patch.object(self.client, "_client", sc):
            result = self.client.delete_coupon("WELCOME20")
        sc.coupons.delete.assert_called_once_with("WELCOME20")
        assert result["deleted"] is True


class TestStripeClientBalance:
    def setup_method(self):
        self.client = _StripeClient("sk_test_key123")

    def _mock_stripe(self):
        return MagicMock()

    def test_get_balance(self):
        sc = self._mock_stripe()
        avail = MagicMock()
        avail.amount = 10000
        avail.currency = "usd"
        pend = MagicMock()
        pend.amount = 5000
        pend.currency = "usd"
        sc.balance.retrieve.return_value = MagicMock(available=[avail], pending=[pend])
        with patch.object(self.client, "_client", sc):
            result = self.client.get_balance()
        assert result["available"][0]["amount"] == 10000
        assert result["pending"][0]["currency"] == "usd"

    def test_list_balance_transactions(self):
        txn = MagicMock()
        txn.id = "txn_test123"
        txn.amount = 2000
        txn.currency = "usd"
        txn.net = 1942
        txn.fee = 58
        txn.type = "charge"
        txn.status = "available"
        txn.description = "Test"
        txn.created = 1700000000
        sc = self._mock_stripe()
        sc.balance_transactions.list.return_value = _make_stripe_list([txn])
        with patch.object(self.client, "_client", sc):
            result = self.client.list_balance_transactions(type_filter="charge")
        call_params = sc.balance_transactions.list.call_args[0][0]
        assert call_params["type"] == "charge"
        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["net"] == 1942


class TestStripeClientWebhookEndpoints:
    def setup_method(self):
        self.client = _StripeClient("sk_test_key123")

    def _mock_stripe(self):
        return MagicMock()

    def test_list_webhook_endpoints(self):
        we = MagicMock()
        we.id = "we_test123"
        we.url = "https://example.com/webhook"
        we.status = "enabled"
        we.enabled_events = ["payment_intent.succeeded"]
        we.created = 1700000000
        sc = self._mock_stripe()
        sc.webhook_endpoints.list.return_value = _make_stripe_list([we])
        with patch.object(self.client, "_client", sc):
            result = self.client.list_webhook_endpoints(limit=10)
        assert len(result["webhook_endpoints"]) == 1
        assert result["webhook_endpoints"][0]["url"] == "https://example.com/webhook"
        assert result["webhook_endpoints"][0]["status"] == "enabled"


class TestStripeClientPaymentMethods:
    def setup_method(self):
        self.client = _StripeClient("sk_test_key123")

    def _mock_stripe(self):
        return MagicMock()

    def test_list_payment_methods(self):
        sc = self._mock_stripe()
        sc.payment_methods.list.return_value = _make_stripe_list([_payment_method()])
        with patch.object(self.client, "_client", sc):
            result = self.client.list_payment_methods("cus_test123", type_filter="card")
        call_params = sc.payment_methods.list.call_args[0][0]
        assert call_params["customer"] == "cus_test123"
        assert call_params["type"] == "card"
        assert len(result["payment_methods"]) == 1
        assert result["payment_methods"][0]["card"]["last4"] == "4242"

    def test_get_payment_method(self):
        sc = self._mock_stripe()
        sc.payment_methods.retrieve.return_value = _payment_method()
        with patch.object(self.client, "_client", sc):
            result = self.client.get_payment_method("pm_test123")
        sc.payment_methods.retrieve.assert_called_once_with("pm_test123")
        assert result["type"] == "card"

    def test_detach_payment_method(self):
        sc = self._mock_stripe()
        detached = _payment_method(customer=None)
        sc.payment_methods.detach.return_value = detached
        with patch.object(self.client, "_client", sc):
            result = self.client.detach_payment_method("pm_test123")
        sc.payment_methods.detach.assert_called_once_with("pm_test123")
        assert result["customer"] is None


# ---------------------------------------------------------------------------
# MCP tool registration and credential tests
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_register_tools_registers_all_tools(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        assert mcp.tool.call_count == 51

    def test_no_credentials_returns_error(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        with patch.dict("os.environ", {}, clear=True):
            register_tools(mcp, credentials=None)
            list_fn = next(f for f in registered_fns if f.__name__ == "stripe_list_customers")
            result = list_fn()

        assert "error" in result
        assert "not configured" in result["error"]

    def test_credentials_from_credential_manager(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        cred_manager = MagicMock()
        cred_manager.get.return_value = "sk_test_fromcredstore"

        register_tools(mcp, credentials=cred_manager)

        fn = next(f for f in registered_fns if f.__name__ == "stripe_get_balance")

        with patch("aden_tools.tools.stripe_tool.stripe_tool._StripeClient") as MockClient:
            instance = MockClient.return_value
            instance.get_balance.return_value = {"available": [], "pending": []}
            fn()

        MockClient.assert_called_once_with("sk_test_fromcredstore")
        cred_manager.get.assert_called_with("stripe")

    def test_credentials_from_env_vars(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        register_tools(mcp, credentials=None)

        fn = next(f for f in registered_fns if f.__name__ == "stripe_get_balance")

        with (
            patch.dict("os.environ", {"STRIPE_API_KEY": "sk_test_fromenv"}),
            patch("aden_tools.tools.stripe_tool.stripe_tool._StripeClient") as MockClient,
        ):
            instance = MockClient.return_value
            instance.get_balance.return_value = {"available": [], "pending": []}
            fn()

        MockClient.assert_called_once_with("sk_test_fromenv")

    def test_stripe_error_is_caught(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        cred_manager = MagicMock()
        cred_manager.get.return_value = "sk_test_key"

        register_tools(mcp, credentials=cred_manager)

        fn = next(f for f in registered_fns if f.__name__ == "stripe_get_balance")

        with patch("aden_tools.tools.stripe_tool.stripe_tool._StripeClient") as MockClient:
            instance = MockClient.return_value
            instance.get_balance.side_effect = stripe.AuthenticationError("Invalid API key")
            result = fn()

        assert "error" in result


# ---------------------------------------------------------------------------
# Individual MCP tool validation tests
# ---------------------------------------------------------------------------


def _setup_tools():
    """Helper to register tools with a mock credential manager."""
    mcp = MagicMock()
    fns = []
    mcp.tool.return_value = lambda fn: fns.append(fn) or fn
    cred = MagicMock()
    cred.get.return_value = "sk_test_key"
    register_tools(mcp, credentials=cred)
    fn_map = {f.__name__: f for f in fns}
    return fn_map


class TestCustomerToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_get_customer_invalid_id(self):
        result = self.fns["stripe_get_customer"](customer_id="not_a_customer")
        assert "error" in result
        assert "cus_" in result["error"]

    def test_update_customer_invalid_id(self):
        result = self.fns["stripe_update_customer"](customer_id="bad_id")
        assert "error" in result
        assert "cus_" in result["error"]

    def test_get_customer_by_email_invalid(self):
        result = self.fns["stripe_get_customer_by_email"](email="notanemail")
        assert "error" in result

    def test_list_customers_success(self):
        with patch("aden_tools.tools.stripe_tool.stripe_tool._StripeClient") as MockClient:
            MockClient.return_value.list_customers.return_value = {
                "has_more": False,
                "customers": [],
            }
            result = self.fns["stripe_list_customers"](limit=5)
        assert "customers" in result

    def test_create_customer_success(self):
        with patch("aden_tools.tools.stripe_tool.stripe_tool._StripeClient") as MockClient:
            MockClient.return_value.create_customer.return_value = {
                "id": "cus_new",
                "email": "new@example.com",
            }
            result = self.fns["stripe_create_customer"](email="new@example.com")
        assert result["id"] == "cus_new"


class TestSubscriptionToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_get_subscription_invalid_id(self):
        result = self.fns["stripe_get_subscription"](subscription_id="not_a_sub")
        assert "error" in result
        assert "sub_" in result["error"]

    def test_get_subscription_status_invalid_customer(self):
        result = self.fns["stripe_get_subscription_status"](customer_id="bad_id")
        assert "error" in result
        assert "cus_" in result["error"]

    def test_create_subscription_invalid_customer(self):
        result = self.fns["stripe_create_subscription"](customer_id="bad", price_id="price_test123")
        assert "error" in result
        assert "cus_" in result["error"]

    def test_create_subscription_invalid_price(self):
        result = self.fns["stripe_create_subscription"](
            customer_id="cus_test123", price_id="bad_price"
        )
        assert "error" in result
        assert "price_" in result["error"]

    def test_create_subscription_invalid_quantity(self):
        result = self.fns["stripe_create_subscription"](
            customer_id="cus_test123", price_id="price_test123", quantity=0
        )
        assert "error" in result
        assert "Quantity" in result["error"]

    def test_update_subscription_invalid_id(self):
        result = self.fns["stripe_update_subscription"](subscription_id="bad_id")
        assert "error" in result
        assert "sub_" in result["error"]

    def test_cancel_subscription_invalid_id(self):
        result = self.fns["stripe_cancel_subscription"](subscription_id="bad_id")
        assert "error" in result
        assert "sub_" in result["error"]


class TestPaymentIntentToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_create_payment_intent_zero_amount(self):
        result = self.fns["stripe_create_payment_intent"](amount=0, currency="usd")
        assert "error" in result
        assert "positive" in result["error"]

    def test_create_payment_intent_negative_amount(self):
        result = self.fns["stripe_create_payment_intent"](amount=-100, currency="usd")
        assert "error" in result
        assert "positive" in result["error"]

    def test_create_payment_intent_invalid_currency(self):
        result = self.fns["stripe_create_payment_intent"](amount=2000, currency="INVALID")
        assert "error" in result
        assert "3-letter" in result["error"]

    def test_get_payment_intent_invalid_id(self):
        result = self.fns["stripe_get_payment_intent"](payment_intent_id="bad_id")
        assert "error" in result
        assert "pi_" in result["error"]

    def test_confirm_payment_intent_invalid_id(self):
        result = self.fns["stripe_confirm_payment_intent"](payment_intent_id="bad_id")
        assert "error" in result
        assert "pi_" in result["error"]

    def test_cancel_payment_intent_invalid_id(self):
        result = self.fns["stripe_cancel_payment_intent"](payment_intent_id="bad_id")
        assert "error" in result
        assert "pi_" in result["error"]


class TestChargeToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_get_charge_invalid_id(self):
        result = self.fns["stripe_get_charge"](charge_id="bad_id")
        assert "error" in result
        assert "ch_" in result["error"]

    def test_capture_charge_invalid_id(self):
        result = self.fns["stripe_capture_charge"](charge_id="bad_id")
        assert "error" in result
        assert "ch_" in result["error"]

    def test_capture_charge_negative_amount(self):
        result = self.fns["stripe_capture_charge"](charge_id="ch_test123", amount=-100)
        assert "error" in result
        assert "positive" in result["error"]


class TestRefundToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_create_refund_no_identifiers(self):
        result = self.fns["stripe_create_refund"]()
        assert "error" in result
        assert "charge_id" in result["error"]

    def test_create_refund_negative_amount(self):
        result = self.fns["stripe_create_refund"](charge_id="ch_test123", amount=-100)
        assert "error" in result
        assert "positive" in result["error"]

    def test_get_refund_invalid_id(self):
        result = self.fns["stripe_get_refund"](refund_id="bad_id")
        assert "error" in result
        assert "re_" in result["error"]


class TestInvoiceToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_get_invoice_invalid_id(self):
        result = self.fns["stripe_get_invoice"](invoice_id="bad_id")
        assert "error" in result
        assert "in_" in result["error"]

    def test_create_invoice_invalid_customer(self):
        result = self.fns["stripe_create_invoice"](customer_id="bad_id")
        assert "error" in result
        assert "cus_" in result["error"]

    def test_finalize_invoice_invalid_id(self):
        result = self.fns["stripe_finalize_invoice"](invoice_id="bad_id")
        assert "error" in result
        assert "in_" in result["error"]

    def test_pay_invoice_invalid_id(self):
        result = self.fns["stripe_pay_invoice"](invoice_id="bad_id")
        assert "error" in result
        assert "in_" in result["error"]

    def test_void_invoice_invalid_id(self):
        result = self.fns["stripe_void_invoice"](invoice_id="bad_id")
        assert "error" in result
        assert "in_" in result["error"]


class TestInvoiceItemToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_create_invoice_item_invalid_customer(self):
        result = self.fns["stripe_create_invoice_item"](
            customer_id="bad", amount=1000, currency="usd"
        )
        assert "error" in result
        assert "cus_" in result["error"]

    def test_create_invoice_item_zero_amount(self):
        result = self.fns["stripe_create_invoice_item"](
            customer_id="cus_test123", amount=0, currency="usd"
        )
        assert "error" in result
        assert "non-zero" in result["error"]

    def test_create_invoice_item_negative_amount_allowed(self):
        with patch("aden_tools.tools.stripe_tool.stripe_tool._StripeClient") as MockClient:
            MockClient.return_value.create_invoice_item.return_value = {
                "id": "ii_credit",
                "amount": -500,
                "currency": "usd",
            }
            result = self.fns["stripe_create_invoice_item"](
                customer_id="cus_test123",
                amount=-500,
                currency="usd",
                description="Discount credit",
            )
        assert result["id"] == "ii_credit"

    def test_create_invoice_item_invalid_currency(self):
        result = self.fns["stripe_create_invoice_item"](
            customer_id="cus_test123", amount=1000, currency="INVALID"
        )
        assert "error" in result
        assert "3-letter" in result["error"]

    def test_delete_invoice_item_invalid_id(self):
        result = self.fns["stripe_delete_invoice_item"](invoice_item_id="bad_id")
        assert "error" in result
        assert "ii_" in result["error"]


class TestProductToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_get_product_invalid_id(self):
        result = self.fns["stripe_get_product"](product_id="bad_id")
        assert "error" in result
        assert "prod_" in result["error"]

    def test_update_product_invalid_id(self):
        result = self.fns["stripe_update_product"](product_id="bad_id")
        assert "error" in result
        assert "prod_" in result["error"]

    def test_create_product_missing_name(self):
        result = self.fns["stripe_create_product"](name="")
        assert "error" in result
        assert "name" in result["error"]


class TestPriceToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_get_price_invalid_id(self):
        result = self.fns["stripe_get_price"](price_id="bad_id")
        assert "error" in result
        assert "price_" in result["error"]

    def test_update_price_invalid_id(self):
        result = self.fns["stripe_update_price"](price_id="bad_id")
        assert "error" in result
        assert "price_" in result["error"]

    def test_create_price_zero_amount(self):
        result = self.fns["stripe_create_price"](
            unit_amount=0, currency="usd", product_id="prod_test123"
        )
        assert "error" in result
        assert "positive" in result["error"]

    def test_create_price_invalid_currency(self):
        result = self.fns["stripe_create_price"](
            unit_amount=999, currency="INVALID", product_id="prod_test123"
        )
        assert "error" in result
        assert "3-letter" in result["error"]

    def test_create_price_invalid_product(self):
        result = self.fns["stripe_create_price"](
            unit_amount=999, currency="usd", product_id="bad_id"
        )
        assert "error" in result
        assert "prod_" in result["error"]


class TestPaymentLinkToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_create_payment_link_invalid_price(self):
        result = self.fns["stripe_create_payment_link"](price_id="bad_id")
        assert "error" in result
        assert "price_" in result["error"]

    def test_create_payment_link_zero_quantity(self):
        result = self.fns["stripe_create_payment_link"](price_id="price_test123", quantity=0)
        assert "error" in result
        assert "Quantity" in result["error"]

    def test_get_payment_link_invalid_id(self):
        result = self.fns["stripe_get_payment_link"](payment_link_id="bad_id")
        assert "error" in result
        assert "plink_" in result["error"]


class TestCouponToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_create_coupon_no_discount(self):
        result = self.fns["stripe_create_coupon"](duration="once")
        assert "error" in result
        assert "percent_off" in result["error"]

    def test_create_coupon_both_discount_types(self):
        result = self.fns["stripe_create_coupon"](percent_off=20.0, amount_off=500, duration="once")
        assert "error" in result
        assert "one of" in result["error"]

    def test_create_coupon_amount_off_missing_currency(self):
        result = self.fns["stripe_create_coupon"](amount_off=500, duration="once")
        assert "error" in result
        assert "currency" in result["error"]

    def test_create_coupon_invalid_duration(self):
        result = self.fns["stripe_create_coupon"](percent_off=20.0, duration="invalid")
        assert "error" in result
        assert "duration" in result["error"]

    def test_create_coupon_repeating_missing_months(self):
        result = self.fns["stripe_create_coupon"](percent_off=20.0, duration="repeating")
        assert "error" in result
        assert "duration_in_months" in result["error"]

    def test_delete_coupon_missing_id(self):
        result = self.fns["stripe_delete_coupon"](coupon_id="")
        assert "error" in result
        assert "coupon_id" in result["error"]


class TestPaymentMethodToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_list_payment_methods_invalid_customer(self):
        result = self.fns["stripe_list_payment_methods"](customer_id="bad_id")
        assert "error" in result
        assert "cus_" in result["error"]

    def test_get_payment_method_invalid_id(self):
        result = self.fns["stripe_get_payment_method"](payment_method_id="bad_id")
        assert "error" in result
        assert "pm_" in result["error"]

    def test_detach_payment_method_invalid_id(self):
        result = self.fns["stripe_detach_payment_method"](payment_method_id="bad_id")
        assert "error" in result
        assert "pm_" in result["error"]


# ---------------------------------------------------------------------------
# Stripe error propagation across tool categories
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_name,kwargs",
    [
        ("stripe_get_customer", {"customer_id": "cus_test123"}),
        ("stripe_get_subscription", {"subscription_id": "sub_test123"}),
        ("stripe_get_payment_intent", {"payment_intent_id": "pi_test123"}),
        ("stripe_get_charge", {"charge_id": "ch_test123"}),
        ("stripe_get_refund", {"refund_id": "re_test123"}),
        ("stripe_get_invoice", {"invoice_id": "in_test123"}),
        ("stripe_get_product", {"product_id": "prod_test123"}),
        ("stripe_get_price", {"price_id": "price_test123"}),
        ("stripe_get_payment_link", {"payment_link_id": "plink_test123"}),
        ("stripe_get_payment_method", {"payment_method_id": "pm_test123"}),
        ("stripe_get_balance", {}),
    ],
)
def test_stripe_error_propagation(tool_name, kwargs):
    fns = _setup_tools()
    with patch("aden_tools.tools.stripe_tool.stripe_tool._StripeClient") as MockClient:
        method_name = tool_name.replace("stripe_", "")
        getattr(MockClient.return_value, method_name).side_effect = stripe.APIConnectionError(
            "Network error"
        )
        result = fns[tool_name](**kwargs)
    assert "error" in result


# ---------------------------------------------------------------------------
# Credential spec tests
# ---------------------------------------------------------------------------


class TestCredentialSpec:
    def test_stripe_credential_spec_exists(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "stripe" in CREDENTIAL_SPECS

    def test_stripe_spec_env_var(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["stripe"]
        assert spec.env_var == "STRIPE_API_KEY"

    def test_stripe_spec_tool_count(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["stripe"]
        assert len(spec.tools) == 51

    def test_stripe_spec_tools_include_core_methods(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["stripe"]
        expected = [
            "stripe_create_customer",
            "stripe_get_customer",
            "stripe_get_customer_by_email",
            "stripe_update_customer",
            "stripe_list_customers",
            "stripe_get_subscription",
            "stripe_get_subscription_status",
            "stripe_list_subscriptions",
            "stripe_create_subscription",
            "stripe_update_subscription",
            "stripe_cancel_subscription",
            "stripe_create_payment_intent",
            "stripe_get_payment_intent",
            "stripe_confirm_payment_intent",
            "stripe_cancel_payment_intent",
            "stripe_list_payment_intents",
            "stripe_list_charges",
            "stripe_get_charge",
            "stripe_capture_charge",
            "stripe_create_refund",
            "stripe_get_refund",
            "stripe_list_refunds",
            "stripe_list_invoices",
            "stripe_get_invoice",
            "stripe_create_invoice",
            "stripe_finalize_invoice",
            "stripe_pay_invoice",
            "stripe_void_invoice",
            "stripe_create_invoice_item",
            "stripe_list_invoice_items",
            "stripe_delete_invoice_item",
            "stripe_create_product",
            "stripe_get_product",
            "stripe_list_products",
            "stripe_update_product",
            "stripe_create_price",
            "stripe_get_price",
            "stripe_list_prices",
            "stripe_update_price",
            "stripe_create_payment_link",
            "stripe_get_payment_link",
            "stripe_list_payment_links",
            "stripe_create_coupon",
            "stripe_list_coupons",
            "stripe_delete_coupon",
            "stripe_get_balance",
            "stripe_list_balance_transactions",
            "stripe_list_webhook_endpoints",
            "stripe_list_payment_methods",
            "stripe_get_payment_method",
            "stripe_detach_payment_method",
        ]
        for tool in expected:
            assert tool in spec.tools, f"Missing tool in credential spec: {tool}"

    def test_stripe_spec_health_check(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["stripe"]
        assert spec.health_check_endpoint == "https://api.stripe.com/v1/balance"
        assert spec.health_check_method == "GET"

    def test_stripe_spec_auth_support(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["stripe"]
        assert spec.aden_supported is False
        assert spec.direct_api_key_supported is True
        assert "dashboard.stripe.com" in spec.api_key_instructions

    def test_stripe_spec_credential_store_fields(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["stripe"]
        assert spec.credential_id == "stripe"
        assert spec.credential_key == "api_key"
        assert spec.credential_group == ""

    def test_stripe_spec_required_not_startup(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["stripe"]
        assert spec.required is True
        assert spec.startup_required is False
