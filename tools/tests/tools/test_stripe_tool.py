"""
Comprehensive test suite for Stripe Tool

Tests cover all functionality with mocked Stripe API calls.
"""

from unittest.mock import Mock, patch

import pytest
import stripe

from aden_tools.tools.stripe_tool import StripeTool, StripeToolConfig


@pytest.fixture
def stripe_config():
    """Fixture providing test Stripe configuration"""
    return StripeToolConfig(api_key="sk_test_123456789")


@pytest.fixture
def stripe_tool(stripe_config):
    """Fixture providing initialized StripeTool instance"""
    return StripeTool(config=stripe_config)


@pytest.fixture
def mock_customer():
    """Fixture providing mock customer data"""
    return {
        "id": "cus_test123",
        "object": "customer",
        "email": "test@example.com",
        "name": "Test Customer",
        "description": "Test customer account",
        "metadata": {"user_id": "123"},
        "created": 1609459200,
        "balance": 0,
        "delinquent": False,
    }


@pytest.fixture
def mock_subscription():
    """Fixture providing mock subscription data"""
    return {
        "id": "sub_test123",
        "object": "subscription",
        "customer": "cus_test123",
        "status": "active",
        "current_period_start": 1609459200,
        "current_period_end": 1612137600,
        "items": {"data": [{"id": "si_test123", "price": {"id": "price_test123"}}]},
    }


@pytest.fixture
def mock_invoice():
    """Fixture providing mock invoice data"""
    return {
        "id": "in_test123",
        "object": "invoice",
        "customer": "cus_test123",
        "status": "open",
        "amount_due": 1000,
        "amount_paid": 0,
        "currency": "usd",
    }


@pytest.fixture
def mock_payment_intent():
    """Fixture providing mock payment intent data"""
    return {
        "id": "pi_test123",
        "object": "payment_intent",
        "amount": 2000,
        "currency": "usd",
        "status": "requires_payment_method",
    }


# ==================== CUSTOMERs TESTS ====================


class TestCustomerManagement:
    """Tests for customer management functionality"""

    @patch("stripe.Customer.create")
    def test_create_customer_basic(self, mock_create, stripe_tool, mock_customer):
        """Test basic customer creation"""
        mock_create.return_value = Mock(to_dict=Mock(return_value=mock_customer))

        result = stripe_tool.create_customer(email="test@example.com", name="Test Customer")

        assert result["email"] == "test@example.com"
        assert result["name"] == "Test Customer"
        mock_create.assert_called_once()

    @patch("stripe.Customer.create")
    def test_create_customer_full(self, mock_create, stripe_tool, mock_customer):
        """Test customer creation with all parameters"""
        mock_create.return_value = Mock(to_dict=Mock(return_value=mock_customer))

        result = stripe_tool.create_customer(
            email="test@example.com",
            name="Test Customer",
            description="VIP customer",
            metadata={"user_id": "123"},
            phone="+1234567890",
            address={
                "line1": "123 Main St",
                "city": "San Francisco",
                "state": "CA",
                "postal_code": "94102",
                "country": "US",
            },
        )

        assert result["id"] == "cus_test123"
        mock_create.assert_called_once()

    @patch("stripe.Customer.list")
    def test_get_customer_by_email(self, mock_list, stripe_tool, mock_customer):
        """Test retrieving customer by email"""
        mock_list.return_value = Mock(data=[Mock(to_dict=Mock(return_value=mock_customer))])

        result = stripe_tool.get_customer_by_email("test@example.com")

        assert result is not None
        assert result["email"] == "test@example.com"
        mock_list.assert_called_once_with(email="test@example.com", limit=1)

    @patch("stripe.Customer.list")
    def test_get_customer_by_email_not_found(self, mock_list, stripe_tool):
        """Test customer not found by email"""
        mock_list.return_value = Mock(data=[])

        result = stripe_tool.get_customer_by_email("notfound@example.com")

        assert result is None

    @patch("stripe.Customer.retrieve")
    def test_get_customer_by_id(self, mock_retrieve, stripe_tool, mock_customer):
        """Test retrieving customer by ID"""
        mock_retrieve.return_value = Mock(to_dict=Mock(return_value=mock_customer))

        result = stripe_tool.get_customer_by_id("cus_test123")

        assert result["id"] == "cus_test123"
        mock_retrieve.assert_called_once_with("cus_test123")

    @patch("stripe.Customer.modify")
    def test_update_customer(self, mock_modify, stripe_tool, mock_customer):
        """Test customer update"""
        updated_customer = mock_customer.copy()
        updated_customer["name"] = "Updated Name"
        mock_modify.return_value = Mock(to_dict=Mock(return_value=updated_customer))

        result = stripe_tool.update_customer(customer_id="cus_test123", name="Updated Name")

        assert result["name"] == "Updated Name"
        mock_modify.assert_called_once()

    @patch("stripe.Customer.list")
    def test_list_customers(self, mock_list, stripe_tool, mock_customer):
        """Test listing customers"""
        mock_list.return_value = Mock(
            to_dict=Mock(return_value={"data": [mock_customer], "has_more": False})
        )

        result = stripe_tool.list_customers(limit=10)

        assert "data" in result
        assert len(result["data"]) == 1
        mock_list.assert_called_once()

    @patch("stripe.Customer.delete")
    def test_delete_customer(self, mock_delete, stripe_tool):
        """Test customer deletion"""
        mock_delete.return_value = Mock(
            to_dict=Mock(return_value={"id": "cus_test123", "deleted": True})
        )

        result = stripe_tool.delete_customer("cus_test123")

        assert result["deleted"] is True
        mock_delete.assert_called_once_with("cus_test123")


# ==================== SUBSCRIPTION TESTS ====================


class TestSubscriptionManagement:
    """Tests for subscription management functionality"""

    @patch("stripe.Subscription.create")
    def test_create_subscription(self, mock_create, stripe_tool, mock_subscription):
        """Test subscription creation"""
        mock_create.return_value = Mock(to_dict=Mock(return_value=mock_subscription))

        result = stripe_tool.create_subscription(
            customer_id="cus_test123", items=[{"price": "price_test123", "quantity": 1}]
        )

        assert result["id"] == "sub_test123"
        assert result["status"] == "active"
        mock_create.assert_called_once()

    @patch("stripe.Subscription.create")
    def test_create_subscription_with_trial(self, mock_create, stripe_tool, mock_subscription):
        """Test subscription creation with trial period"""
        trial_subscription = mock_subscription.copy()
        trial_subscription["trial_end"] = 1612137600
        mock_create.return_value = Mock(to_dict=Mock(return_value=trial_subscription))

        result = stripe_tool.create_subscription(
            customer_id="cus_test123", items=[{"price": "price_test123"}], trial_period_days=30
        )

        assert "trial_end" in result
        mock_create.assert_called_once()

    @patch("stripe.Subscription.retrieve")
    def test_get_subscription_status(self, mock_retrieve, stripe_tool, mock_subscription):
        """Test getting subscription status"""
        mock_retrieve.return_value = Mock(status="active")

        status = stripe_tool.get_subscription_status("sub_test123")

        assert status == "active"
        mock_retrieve.assert_called_once_with("sub_test123")

    @patch("stripe.Subscription.modify")
    def test_update_subscription(self, mock_modify, stripe_tool, mock_subscription):
        """Test subscription update"""
        mock_modify.return_value = Mock(to_dict=Mock(return_value=mock_subscription))

        result = stripe_tool.update_subscription(
            subscription_id="sub_test123", metadata={"plan": "premium"}
        )

        assert result["id"] == "sub_test123"
        mock_modify.assert_called_once()

    @patch("stripe.Subscription.cancel")
    def test_cancel_subscription_immediate(self, mock_cancel, stripe_tool, mock_subscription):
        """Test immediate subscription cancellation"""
        canceled = mock_subscription.copy()
        canceled["status"] = "canceled"
        mock_cancel.return_value = Mock(to_dict=Mock(return_value=canceled))

        result = stripe_tool.cancel_subscription("sub_test123")

        assert result["status"] == "canceled"
        mock_cancel.assert_called_once()

    @patch("stripe.Subscription.modify")
    def test_cancel_subscription_at_period_end(self, mock_modify, stripe_tool, mock_subscription):
        """Test subscription cancellation at period end"""
        canceled = mock_subscription.copy()
        canceled["cancel_at_period_end"] = True
        mock_modify.return_value = Mock(to_dict=Mock(return_value=canceled))

        result = stripe_tool.cancel_subscription("sub_test123", at_period_end=True)

        assert result["cancel_at_period_end"] is True
        mock_modify.assert_called_once()

    @patch("stripe.Subscription.modify")
    def test_pause_subscription(self, mock_modify, stripe_tool, mock_subscription):
        """Test subscription pause"""
        paused = mock_subscription.copy()
        paused["pause_collection"] = {"behavior": "void"}
        mock_modify.return_value = Mock(to_dict=Mock(return_value=paused))

        result = stripe_tool.pause_subscription("sub_test123")

        assert result["pause_collection"] is not None
        mock_modify.assert_called_once()

    @patch("stripe.Subscription.modify")
    def test_resume_subscription(self, mock_modify, stripe_tool, mock_subscription):
        """Test subscription resume"""
        mock_modify.return_value = Mock(to_dict=Mock(return_value=mock_subscription))

        result = stripe_tool.resume_subscription("sub_test123")

        assert result["id"] == "sub_test123"
        mock_modify.assert_called_once()

    @patch("stripe.Subscription.list")
    def test_list_subscriptions(self, mock_list, stripe_tool, mock_subscription):
        """Test listing subscriptions"""
        mock_list.return_value = Mock(
            to_dict=Mock(return_value={"data": [mock_subscription], "has_more": False})
        )

        result = stripe_tool.list_subscriptions(customer_id="cus_test123")

        assert "data" in result
        mock_list.assert_called_once()


# ==================== INVOICE TESTS ====================


class TestInvoiceManagement:
    """Tests for invoice management functionality"""

    @patch("stripe.Invoice.create")
    def test_create_invoice(self, mock_create, stripe_tool, mock_invoice):
        """Test invoice creation"""
        mock_create.return_value = Mock(to_dict=Mock(return_value=mock_invoice))

        result = stripe_tool.create_invoice(
            customer_id="cus_test123", description="Monthly subscription"
        )

        assert result["id"] == "in_test123"
        mock_create.assert_called_once()

    @patch("stripe.Invoice.retrieve")
    def test_get_invoice(self, mock_retrieve, stripe_tool, mock_invoice):
        """Test invoice retrieval"""
        mock_retrieve.return_value = Mock(to_dict=Mock(return_value=mock_invoice))

        result = stripe_tool.get_invoice("in_test123")

        assert result["id"] == "in_test123"
        mock_retrieve.assert_called_once_with("in_test123")

    @patch("stripe.Invoice.list")
    def test_list_invoices(self, mock_list, stripe_tool, mock_invoice):
        """Test listing invoices"""
        mock_list.return_value = Mock(
            to_dict=Mock(return_value={"data": [mock_invoice], "has_more": False})
        )

        result = stripe_tool.list_invoices(customer_id="cus_test123", status="open")

        assert "data" in result
        mock_list.assert_called_once()

    @patch("stripe.Invoice.pay")
    def test_pay_invoice(self, mock_pay, stripe_tool, mock_invoice):
        """Test invoice payment"""
        paid_invoice = mock_invoice.copy()
        paid_invoice["status"] = "paid"
        mock_pay.return_value = Mock(to_dict=Mock(return_value=paid_invoice))

        result = stripe_tool.pay_invoice("in_test123")

        assert result["status"] == "paid"
        mock_pay.assert_called_once()

    @patch("stripe.Invoice.void_invoice")
    def test_void_invoice(self, mock_void, stripe_tool, mock_invoice):
        """Test invoice voiding"""
        voided_invoice = mock_invoice.copy()
        voided_invoice["status"] = "void"
        mock_void.return_value = Mock(to_dict=Mock(return_value=voided_invoice))

        result = stripe_tool.void_invoice("in_test123")

        assert result["status"] == "void"
        mock_void.assert_called_once_with("in_test123")

    @patch("stripe.Invoice.finalize_invoice")
    def test_finalize_invoice(self, mock_finalize, stripe_tool, mock_invoice):
        """Test invoice finalization"""
        finalized_invoice = mock_invoice.copy()
        finalized_invoice["status"] = "open"
        mock_finalize.return_value = Mock(to_dict=Mock(return_value=finalized_invoice))

        result = stripe_tool.finalize_invoice("in_test123")

        assert result["status"] == "open"
        mock_finalize.assert_called_once()


# ==================== PAYMENT METHOD TESTS ====================


class TestPaymentMethods:
    """Tests for payment method functionality"""

    @patch("stripe.PaymentMethod.attach")
    def test_attach_payment_method(self, mock_attach, stripe_tool):
        """Test attaching payment method to customer"""
        mock_pm = {"id": "pm_test123", "customer": "cus_test123"}
        mock_attach.return_value = Mock(to_dict=Mock(return_value=mock_pm))

        result = stripe_tool.attach_payment_method("pm_test123", "cus_test123")

        assert result["customer"] == "cus_test123"
        mock_attach.assert_called_once()

    @patch("stripe.PaymentMethod.detach")
    def test_detach_payment_method(self, mock_detach, stripe_tool):
        """Test detaching payment method"""
        mock_pm = {"id": "pm_test123", "customer": None}
        mock_detach.return_value = Mock(to_dict=Mock(return_value=mock_pm))

        result = stripe_tool.detach_payment_method("pm_test123")

        assert result["customer"] is None
        mock_detach.assert_called_once_with("pm_test123")

    @patch("stripe.PaymentMethod.list")
    def test_list_payment_methods(self, mock_list, stripe_tool):
        """Test listing payment methods"""
        mock_list.return_value = Mock(
            to_dict=Mock(
                return_value={"data": [{"id": "pm_test123", "type": "card"}], "has_more": False}
            )
        )

        result = stripe_tool.list_payment_methods("cus_test123")

        assert "data" in result
        mock_list.assert_called_once()

    @patch("stripe.Customer.modify")
    def test_set_default_payment_method(self, mock_modify, stripe_tool):
        """Test setting default payment method"""
        mock_customer = {
            "id": "cus_test123",
            "invoice_settings": {"default_payment_method": "pm_test123"},
        }
        mock_modify.return_value = Mock(to_dict=Mock(return_value=mock_customer))

        result = stripe_tool.set_default_payment_method("cus_test123", "pm_test123")

        assert result["invoice_settings"]["default_payment_method"] == "pm_test123"
        mock_modify.assert_called_once()


# ==================== PAYMENT INTENT TESTS ====================


class TestPaymentIntents:
    """Tests for payment intent functionality"""

    @patch("stripe.PaymentIntent.create")
    def test_create_payment_intent(self, mock_create, stripe_tool, mock_payment_intent):
        """Test payment intent creation"""
        mock_create.return_value = Mock(to_dict=Mock(return_value=mock_payment_intent))

        result = stripe_tool.create_payment_intent(
            amount=2000, currency="usd", description="Test payment"
        )

        assert result["amount"] == 2000
        assert result["currency"] == "usd"
        mock_create.assert_called_once()

    @patch("stripe.PaymentIntent.confirm")
    def test_confirm_payment_intent(self, mock_confirm, stripe_tool, mock_payment_intent):
        """Test payment intent confirmation"""
        confirmed = mock_payment_intent.copy()
        confirmed["status"] = "succeeded"
        mock_confirm.return_value = Mock(to_dict=Mock(return_value=confirmed))

        result = stripe_tool.confirm_payment_intent("pi_test123")

        assert result["status"] == "succeeded"
        mock_confirm.assert_called_once()

    @patch("stripe.PaymentIntent.cancel")
    def test_cancel_payment_intent(self, mock_cancel, stripe_tool, mock_payment_intent):
        """Test payment intent cancellation"""
        canceled = mock_payment_intent.copy()
        canceled["status"] = "canceled"
        mock_cancel.return_value = Mock(to_dict=Mock(return_value=canceled))

        result = stripe_tool.cancel_payment_intent("pi_test123")

        assert result["status"] == "canceled"
        mock_cancel.assert_called_once()

    @patch("stripe.PaymentIntent.capture")
    def test_capture_payment_intent(self, mock_capture, stripe_tool, mock_payment_intent):
        """Test payment intent capture"""
        captured = mock_payment_intent.copy()
        captured["status"] = "succeeded"
        mock_capture.return_value = Mock(to_dict=Mock(return_value=captured))

        result = stripe_tool.capture_payment_intent("pi_test123")

        assert result["status"] == "succeeded"
        mock_capture.assert_called_once()

    @patch("stripe.PaymentIntent.list")
    def test_list_payment_intents(self, mock_list, stripe_tool, mock_payment_intent):
        """Test listing payment intents"""
        mock_list.return_value = Mock(
            to_dict=Mock(return_value={"data": [mock_payment_intent], "has_more": False})
        )

        result = stripe_tool.list_payment_intents(customer_id="cus_test123")

        assert "data" in result
        mock_list.assert_called_once()


# ==================== CHECKOUT SESSION TESTS ====================


class TestCheckoutSessions:
    """Tests for checkout session functionality"""

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session(self, mock_create, stripe_tool):
        """Test checkout session creation"""
        mock_session = {
            "id": "cs_test123",
            "url": "https://checkout.stripe.com/c/pay/test",
            "mode": "payment",
        }
        mock_create.return_value = Mock(to_dict=Mock(return_value=mock_session))

        result = stripe_tool.create_checkout_session(
            line_items=[{"price": "price_test123", "quantity": 1}],
            mode="payment",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

        assert result["id"] == "cs_test123"
        assert "url" in result
        mock_create.assert_called_once()

    @patch("stripe.checkout.Session.retrieve")
    def test_get_checkout_session(self, mock_retrieve, stripe_tool):
        """Test checkout session retrieval"""
        mock_session = {"id": "cs_test123", "status": "complete"}
        mock_retrieve.return_value = Mock(to_dict=Mock(return_value=mock_session))

        result = stripe_tool.get_checkout_session("cs_test123")

        assert result["id"] == "cs_test123"
        mock_retrieve.assert_called_once_with("cs_test123")

    @patch("stripe.checkout.Session.expire")
    def test_expire_checkout_session(self, mock_expire, stripe_tool):
        """Test checkout session expiration"""
        mock_session = {"id": "cs_test123", "status": "expired"}
        mock_expire.return_value = Mock(to_dict=Mock(return_value=mock_session))

        result = stripe_tool.expire_checkout_session("cs_test123")

        assert result["status"] == "expired"
        mock_expire.assert_called_once_with("cs_test123")


# ==================== PRODUCT & PRICE TESTS ====================


class TestProductsAndPrices:
    """Tests for product and price functionality"""

    @patch("stripe.Product.create")
    def test_create_product(self, mock_create, stripe_tool):
        """Test product creation"""
        mock_product = {"id": "prod_test123", "name": "Test Product", "active": True}
        mock_create.return_value = Mock(to_dict=Mock(return_value=mock_product))

        result = stripe_tool.create_product(name="Test Product", description="A test product")

        assert result["name"] == "Test Product"
        mock_create.assert_called_once()

    @patch("stripe.Product.modify")
    def test_update_product(self, mock_modify, stripe_tool):
        """Test product update"""
        mock_product = {"id": "prod_test123", "name": "Updated Product"}
        mock_modify.return_value = Mock(to_dict=Mock(return_value=mock_product))

        result = stripe_tool.update_product(product_id="prod_test123", name="Updated Product")

        assert result["name"] == "Updated Product"
        mock_modify.assert_called_once()

    @patch("stripe.Product.modify")
    def test_archive_product(self, mock_modify, stripe_tool):
        """Test product archival"""
        mock_product = {"id": "prod_test123", "active": False}
        mock_modify.return_value = Mock(to_dict=Mock(return_value=mock_product))

        result = stripe_tool.archive_product("prod_test123")

        assert result["active"] is False
        mock_modify.assert_called_once_with("prod_test123", active=False)

    @patch("stripe.Price.create")
    def test_create_price(self, mock_create, stripe_tool):
        """Test price creation"""
        mock_price = {
            "id": "price_test123",
            "product": "prod_test123",
            "unit_amount": 1000,
            "currency": "usd",
        }
        mock_create.return_value = Mock(to_dict=Mock(return_value=mock_price))

        result = stripe_tool.create_price(
            product_id="prod_test123", unit_amount=1000, currency="usd"
        )

        assert result["unit_amount"] == 1000
        mock_create.assert_called_once()

    @patch("stripe.Price.create")
    def test_create_recurring_price(self, mock_create, stripe_tool):
        """Test recurring price creation"""
        mock_price = {"id": "price_test123", "recurring": {"interval": "month"}}
        mock_create.return_value = Mock(to_dict=Mock(return_value=mock_price))

        result = stripe_tool.create_price(
            product_id="prod_test123",
            unit_amount=1000,
            currency="usd",
            recurring={"interval": "month"},
        )

        assert "recurring" in result
        mock_create.assert_called_once()


# ==================== REFUND TESTS ====================


class TestRefunds:
    """Tests for refund functionality"""

    @patch("stripe.Refund.create")
    def test_create_refund(self, mock_create, stripe_tool):
        """Test refund creation"""
        mock_refund = {
            "id": "re_test123",
            "payment_intent": "pi_test123",
            "amount": 1000,
            "status": "succeeded",
        }
        mock_create.return_value = Mock(to_dict=Mock(return_value=mock_refund))

        result = stripe_tool.create_refund(payment_intent_id="pi_test123", amount=1000)

        assert result["amount"] == 1000
        mock_create.assert_called_once()

    @patch("stripe.Refund.retrieve")
    def test_get_refund(self, mock_retrieve, stripe_tool):
        """Test refund retrieval"""
        mock_refund = {"id": "re_test123", "status": "succeeded"}
        mock_retrieve.return_value = Mock(to_dict=Mock(return_value=mock_refund))

        result = stripe_tool.get_refund("re_test123")

        assert result["id"] == "re_test123"
        mock_retrieve.assert_called_once_with("re_test123")

    @patch("stripe.Refund.cancel")
    def test_cancel_refund(self, mock_cancel, stripe_tool):
        """Test refund cancellation"""
        mock_refund = {"id": "re_test123", "status": "canceled"}
        mock_cancel.return_value = Mock(to_dict=Mock(return_value=mock_refund))

        result = stripe_tool.cancel_refund("re_test123")

        assert result["status"] == "canceled"
        mock_cancel.assert_called_once_with("re_test123")


# ==================== WEBHOOK TESTS ====================


class TestWebhooks:
    """Tests for webhook functionality"""

    @patch("stripe.Webhook.construct_event")
    def test_verify_webhook_signature(self, mock_construct, stripe_tool):
        """Test webhook signature verification"""
        mock_event = {
            "id": "evt_test123",
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_test123"}},
        }
        mock_construct.return_value = mock_event

        result = stripe_tool.verify_webhook_signature(
            payload='{"test": "data"}', sig_header="t=123,v1=abc", webhook_secret="whsec_test123"
        )

        assert result["id"] == "evt_test123"
        mock_construct.assert_called_once()

    @patch("stripe.Webhook.construct_event")
    def test_verify_webhook_signature_invalid(self, mock_construct, stripe_tool):
        """Test webhook signature verification failure"""
        mock_construct.side_effect = stripe.error.SignatureVerificationError(
            "Invalid signature", "sig_header"
        )

        with pytest.raises(stripe.error.SignatureVerificationError):
            stripe_tool.verify_webhook_signature(
                payload='{"test": "data"}', sig_header="invalid", webhook_secret="whsec_test123"
            )


# ==================== CONFIGURATION TESTS ====================


class TestConfiguration:
    """Tests for tool configuration"""

    def test_config_from_params(self):
        """Test configuration from parameters"""
        config = StripeToolConfig(api_key="sk_test_123")
        tool = StripeTool(config=config)

        assert tool.config.api_key == "sk_test_123"
        assert stripe.api_key == "sk_test_123"

    @patch.dict("os.environ", {"STRIPE_API_KEY": "sk_test_env"})
    def test_config_from_env(self):
        """Test configuration from environment variable"""
        tool = StripeTool()

        assert tool.config.api_key == "sk_test_env"

    def test_config_missing_api_key(self):
        """Test error when API key is missing"""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="Stripe API key not found"):
                StripeTool()

    def test_custom_api_version(self):
        """Test custom API version configuration"""
        config = StripeToolConfig(api_key="sk_test_123", api_version="2023-10-16")
        StripeTool(config=config)

        assert stripe.api_version == "2023-10-16"


# ==================== INTEGRATION SCENARIO TESTS ====================


class TestIntegrationScenarios:
    """Tests for complete workflow scenarios"""

    @patch("stripe.Customer.create")
    @patch("stripe.Subscription.create")
    @patch("stripe.Invoice.list")
    def test_customer_subscription_workflow(
        self, mock_list_invoices, mock_create_sub, mock_create_customer, stripe_tool
    ):
        """Test complete customer-to-subscription workflow"""
        # Create customer
        mock_customer = {"id": "cus_test123", "email": "test@example.com"}
        mock_create_customer.return_value = Mock(to_dict=Mock(return_value=mock_customer))

        customer = stripe_tool.create_customer(email="test@example.com")
        assert customer["id"] == "cus_test123"

        # Create subscription
        mock_sub = {"id": "sub_test123", "customer": "cus_test123", "status": "active"}
        mock_create_sub.return_value = Mock(to_dict=Mock(return_value=mock_sub))

        subscription = stripe_tool.create_subscription(
            customer_id=customer["id"], items=[{"price": "price_test123"}]
        )
        assert subscription["status"] == "active"

        # List invoices
        mock_list_invoices.return_value = Mock(
            to_dict=Mock(return_value={"data": [], "has_more": False})
        )

        invoices = stripe_tool.list_invoices(customer_id=customer["id"])
        assert "data" in invoices

    @patch("stripe.PaymentIntent.create")
    @patch("stripe.PaymentIntent.confirm")
    @patch("stripe.Refund.create")
    def test_payment_refund_workflow(
        self, mock_create_refund, mock_confirm, mock_create_pi, stripe_tool
    ):
        """Test payment and refund workflow"""
        # Create payment intent
        mock_pi = {"id": "pi_test123", "amount": 1000}
        mock_create_pi.return_value = Mock(to_dict=Mock(return_value=mock_pi))

        payment = stripe_tool.create_payment_intent(amount=1000, currency="usd")
        assert payment["amount"] == 1000

        # Confirm payment
        confirmed_pi = mock_pi.copy()
        confirmed_pi["status"] = "succeeded"
        mock_confirm.return_value = Mock(to_dict=Mock(return_value=confirmed_pi))

        confirmed = stripe_tool.confirm_payment_intent(payment["id"])
        assert confirmed["status"] == "succeeded"

        # Create refund
        mock_refund = {"id": "re_test123", "payment_intent": "pi_test123"}
        mock_create_refund.return_value = Mock(to_dict=Mock(return_value=mock_refund))

        refund = stripe_tool.create_refund(payment_intent_id=payment["id"])
        assert refund["payment_intent"] == payment["id"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
