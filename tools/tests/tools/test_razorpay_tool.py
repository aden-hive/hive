"""
Tests for Razorpay payment tool.

Covers:
- _RazorpayClient methods (list_payments, get_payment, create_payment_link, list_invoices,
  get_invoice, create_refund)
- Error handling (401, 403, 404, 400, 429, 500, timeout)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 6 MCP tool functions
- Input validation
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from aden_tools.tools.razorpay_tool.razorpay_tool import (
    RAZORPAY_API_BASE,
    _RazorpayClient,
    register_tools,
)

# --- _RazorpayClient tests ---


class TestRazorpayClient:
    def setup_method(self):
        self.client = _RazorpayClient("rzp_test_key123", "secret456")

    def test_auth_tuple(self):
        auth = self.client._auth
        assert auth == ("rzp_test_key123", "secret456")

    def test_handle_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"id": "pay_123", "amount": 50000}
        assert self.client._handle_response(response) == {"id": "pay_123", "amount": 50000}

    @pytest.mark.parametrize(
        "status_code,expected_substring",
        [
            (401, "Invalid Razorpay API credentials"),
            (403, "Insufficient permissions"),
            (404, "not found"),
            (400, "Bad request"),
            (429, "rate limit"),
        ],
    )
    def test_handle_response_errors(self, status_code, expected_substring):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = {"error": {"description": "Test error"}}
        response.text = "Test error"
        result = self.client._handle_response(response)
        assert "error" in result
        assert expected_substring in result["error"]

    def test_handle_response_generic_error(self):
        response = MagicMock()
        response.status_code = 500
        response.json.return_value = {"error": {"description": "Internal Server Error"}}
        result = self.client._handle_response(response)
        assert "error" in result
        assert "500" in result["error"]

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get")
    def test_list_payments(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "count": 2,
            "items": [
                {
                    "id": "pay_123",
                    "amount": 50000,
                    "currency": "INR",
                    "status": "captured",
                    "method": "card",
                    "email": "test@example.com",
                    "contact": "+919876543210",
                    "created_at": 1640995200,
                    "description": "Test payment",
                    "order_id": "order_456",
                },
                {
                    "id": "pay_789",
                    "amount": 100000,
                    "currency": "INR",
                    "status": "authorized",
                    "method": "upi",
                    "email": "user@example.com",
                    "contact": "+919999999999",
                    "created_at": 1640995300,
                    "description": "Another test",
                    "order_id": None,
                },
            ],
        }
        mock_get.return_value = mock_response

        result = self.client.list_payments(count=10, skip=0)

        mock_get.assert_called_once_with(
            f"{RAZORPAY_API_BASE}/payments",
            auth=self.client._auth,
            params={"count": 10, "skip": 0},
            timeout=30.0,
        )
        assert result["count"] == 2
        assert len(result["payments"]) == 2
        assert result["payments"][0]["id"] == "pay_123"
        assert result["payments"][0]["amount"] == 50000
        assert result["payments"][1]["status"] == "authorized"

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get")
    def test_list_payments_with_filters(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"count": 1, "items": []}
        mock_get.return_value = mock_response

        self.client.list_payments(
            count=20, skip=5, from_timestamp=1640000000, to_timestamp=1650000000
        )

        call_params = mock_get.call_args.kwargs["params"]
        assert call_params["count"] == 20
        assert call_params["skip"] == 5
        assert call_params["from"] == 1640000000
        assert call_params["to"] == 1650000000

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get")
    def test_list_payments_limit_capped(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"count": 0, "items": []}
        mock_get.return_value = mock_response

        self.client.list_payments(count=200)

        call_params = mock_get.call_args.kwargs["params"]
        assert call_params["count"] == 100  # Capped at 100

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get")
    def test_get_payment(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "pay_123",
            "amount": 50000,
            "currency": "INR",
            "status": "captured",
            "method": "card",
            "email": "test@example.com",
            "contact": "+919876543210",
            "created_at": 1640995200,
            "description": "Test payment",
            "order_id": "order_456",
            "error_code": None,
            "error_description": None,
            "captured": True,
            "fee": 1000,
            "tax": 180,
            "refund_status": None,
            "amount_refunded": 0,
        }
        mock_get.return_value = mock_response

        result = self.client.get_payment("pay_123")

        mock_get.assert_called_once_with(
            f"{RAZORPAY_API_BASE}/payments/pay_123",
            auth=self.client._auth,
            timeout=30.0,
        )
        assert result["id"] == "pay_123"
        assert result["amount"] == 50000
        assert result["status"] == "captured"
        assert result["captured"] is True
        assert result["fee"] == 1000

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.post")
    def test_create_payment_link(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "plink_123",
            "short_url": "https://rzp.io/rzp/abc123",
            "amount": 50000,
            "currency": "INR",
            "description": "Test payment link",
            "status": "created",
            "created_at": 1640995200,
            "customer": {
                "name": "Test Customer",
                "email": "test@example.com",
                "contact": "+919876543210",
            },
        }
        mock_post.return_value = mock_response

        result = self.client.create_payment_link(
            amount=50000,
            currency="INR",
            description="Test payment link",
            customer_name="Test Customer",
            customer_email="test@example.com",
            customer_contact="+919876543210",
        )

        mock_post.assert_called_once_with(
            f"{RAZORPAY_API_BASE}/payment_links",
            auth=self.client._auth,
            json={
                "amount": 50000,
                "currency": "INR",
                "description": "Test payment link",
                "customer": {
                    "name": "Test Customer",
                    "email": "test@example.com",
                    "contact": "+919876543210",
                },
            },
            timeout=30.0,
        )
        assert result["id"] == "plink_123"
        assert result["short_url"] == "https://rzp.io/rzp/abc123"
        assert result["status"] == "created"

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.post")
    def test_create_payment_link_minimal(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "plink_456",
            "short_url": "https://rzp.io/rzp/xyz",
            "amount": 10000,
            "currency": "INR",
            "description": "Minimal link",
            "status": "created",
            "created_at": 1640995200,
        }
        mock_post.return_value = mock_response

        result = self.client.create_payment_link(
            amount=10000,
            currency="INR",
            description="Minimal link",
        )

        call_json = mock_post.call_args.kwargs["json"]
        assert "customer" not in call_json  # No customer details provided
        assert result["id"] == "plink_456"

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get")
    def test_list_invoices(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "count": 1,
            "items": [
                {
                    "id": "inv_123",
                    "amount": 50000,
                    "currency": "INR",
                    "status": "issued",
                    "customer_id": "cust_456",
                    "created_at": 1640995200,
                    "description": "Test invoice",
                    "short_url": "https://rzp.io/i/abc",
                }
            ],
        }
        mock_get.return_value = mock_response

        result = self.client.list_invoices(count=10)

        mock_get.assert_called_once_with(
            f"{RAZORPAY_API_BASE}/invoices",
            auth=self.client._auth,
            params={"count": 10, "skip": 0},
            timeout=30.0,
        )
        assert result["count"] == 1
        assert len(result["invoices"]) == 1
        assert result["invoices"][0]["id"] == "inv_123"
        assert result["invoices"][0]["status"] == "issued"

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get")
    def test_get_invoice(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "inv_123",
            "amount": 50000,
            "currency": "INR",
            "status": "paid",
            "customer_id": "cust_456",
            "customer_details": {
                "name": "Test Customer",
                "email": "test@example.com",
            },
            "line_items": [
                {
                    "name": "Product A",
                    "amount": 30000,
                },
                {
                    "name": "Product B",
                    "amount": 20000,
                },
            ],
            "created_at": 1640995200,
            "description": "Test invoice",
            "short_url": "https://rzp.io/i/abc",
            "paid_at": 1641000000,
            "cancelled_at": None,
        }
        mock_get.return_value = mock_response

        result = self.client.get_invoice("inv_123")

        mock_get.assert_called_once_with(
            f"{RAZORPAY_API_BASE}/invoices/inv_123",
            auth=self.client._auth,
            timeout=30.0,
        )
        assert result["id"] == "inv_123"
        assert result["status"] == "paid"
        assert len(result["line_items"]) == 2
        assert result["paid_at"] == 1641000000

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.post")
    def test_create_refund_full(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "rfnd_123",
            "payment_id": "pay_456",
            "amount": 50000,
            "currency": "INR",
            "status": "processed",
            "created_at": 1640995200,
            "notes": {},
            "speed_processed": "normal",
        }
        mock_post.return_value = mock_response

        result = self.client.create_refund("pay_456")

        mock_post.assert_called_once_with(
            f"{RAZORPAY_API_BASE}/payments/pay_456/refund",
            auth=self.client._auth,
            json={},
            timeout=30.0,
        )
        assert result["id"] == "rfnd_123"
        assert result["status"] == "processed"

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.post")
    def test_create_refund_partial(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "rfnd_789",
            "payment_id": "pay_456",
            "amount": 10000,
            "currency": "INR",
            "status": "processed",
            "created_at": 1640995200,
            "notes": {"reason": "Customer request"},
            "speed_processed": "normal",
        }
        mock_post.return_value = mock_response

        result = self.client.create_refund(
            "pay_456",
            amount=10000,
            notes={"reason": "Customer request"},
        )

        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["amount"] == 10000
        assert call_json["notes"]["reason"] == "Customer request"
        assert result["amount"] == 10000


# --- MCP tool registration and credential tests ---


class TestToolRegistration:
    def test_register_tools_registers_all_tools(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        assert mcp.tool.call_count == 6

    def test_no_credentials_returns_error(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        with patch.dict("os.environ", {}, clear=True):
            register_tools(mcp, credentials=None)

        list_fn = next(fn for fn in registered_fns if fn.__name__ == "razorpay_list_payments")
        result = list_fn()
        assert "error" in result
        assert "not configured" in result["error"]

    def test_credentials_from_credential_manager(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        cred_manager = MagicMock()
        cred_manager.get.side_effect = lambda key: {
            "razorpay": "rzp_test_key123",
            "razorpay_secret": "secret456",
        }.get(key)

        register_tools(mcp, credentials=cred_manager)

        list_fn = next(fn for fn in registered_fns if fn.__name__ == "razorpay_list_payments")

        with patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"count": 0, "items": []}
            mock_get.return_value = mock_response

            result = list_fn()

        assert cred_manager.get.call_count == 2
        cred_manager.get.assert_any_call("razorpay")
        cred_manager.get.assert_any_call("razorpay_secret")
        assert "count" in result

    def test_credentials_from_env_vars(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        register_tools(mcp, credentials=None)

        list_fn = next(fn for fn in registered_fns if fn.__name__ == "razorpay_list_payments")

        with (
            patch.dict(
                "os.environ",
                {"RAZORPAY_API_KEY": "rzp_test_env", "RAZORPAY_API_SECRET": "secret_env"},
            ),
            patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get") as mock_get,
        ):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"count": 0, "items": []}
            mock_get.return_value = mock_response

            result = list_fn()

        assert "count" in result
        # Verify auth used env vars
        call_auth = mock_get.call_args.kwargs["auth"]
        assert call_auth == ("rzp_test_env", "secret_env")


# --- Individual tool function tests ---


class TestListPaymentsTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        self.cred = MagicMock()
        self.cred.get.return_value = "rzp_test_key"
        self.env_patcher = patch.dict("os.environ", {"RAZORPAY_API_SECRET": "secret"})
        self.env_patcher.start()
        register_tools(self.mcp, credentials=self.cred)

    def teardown_method(self):
        self.env_patcher.stop()

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get")
    def test_list_payments_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "count": 1,
                    "items": [{"id": "pay_123", "amount": 50000, "status": "captured"}],
                }
            ),
        )
        result = self._fn("razorpay_list_payments")(count=10)
        assert result["count"] == 1
        assert len(result["payments"]) == 1

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get")
    def test_list_payments_normalizes_count(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"count": 0, "items": []})
        )
        # Count too high
        self._fn("razorpay_list_payments")(count=500)
        assert mock_get.call_args.kwargs["params"]["count"] == 100

        # Count too low
        self._fn("razorpay_list_payments")(count=-5)
        assert mock_get.call_args.kwargs["params"]["count"] == 1

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get")
    def test_list_payments_timeout(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("timed out")
        result = self._fn("razorpay_list_payments")()
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get")
    def test_list_payments_network_error(self, mock_get):
        mock_get.side_effect = httpx.RequestError("connection failed")
        result = self._fn("razorpay_list_payments")()
        assert "error" in result
        assert "Network error" in result["error"]


class TestGetPaymentTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        self.cred = MagicMock()
        self.cred.get.return_value = "rzp_test_key"
        self.env_patcher = patch.dict("os.environ", {"RAZORPAY_API_SECRET": "secret"})
        self.env_patcher.start()
        register_tools(self.mcp, credentials=self.cred)

    def teardown_method(self):
        self.env_patcher.stop()

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get")
    def test_get_payment_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "id": "pay_123",
                    "amount": 50000,
                    "status": "captured",
                    "method": "card",
                }
            ),
        )
        result = self._fn("razorpay_get_payment")(payment_id="pay_123")
        assert result["id"] == "pay_123"
        assert result["status"] == "captured"

    def test_get_payment_invalid_id(self):
        result = self._fn("razorpay_get_payment")(payment_id="invalid_id")
        assert "error" in result
        assert "Must match pattern" in result["error"]


class TestCreatePaymentLinkTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        self.cred = MagicMock()
        self.cred.get.return_value = "rzp_test_key"
        self.env_patcher = patch.dict("os.environ", {"RAZORPAY_API_SECRET": "secret"})
        self.env_patcher.start()
        register_tools(self.mcp, credentials=self.cred)

    def teardown_method(self):
        self.env_patcher.stop()

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.post")
    def test_create_payment_link_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "id": "plink_123",
                    "short_url": "https://rzp.io/rzp/test",
                    "amount": 50000,
                    "status": "created",
                }
            ),
        )
        result = self._fn("razorpay_create_payment_link")(
            amount=50000, currency="INR", description="Test"
        )
        assert result["id"] == "plink_123"
        assert result["short_url"] == "https://rzp.io/rzp/test"

    def test_create_payment_link_validation(self):
        # Negative amount
        result = self._fn("razorpay_create_payment_link")(
            amount=-100, currency="INR", description="Test"
        )
        assert "error" in result
        assert "positive" in result["error"]

        # Invalid currency
        result = self._fn("razorpay_create_payment_link")(
            amount=50000, currency="INVALID", description="Test"
        )
        assert "error" in result
        assert "3-letter code" in result["error"]

        # Missing description
        result = self._fn("razorpay_create_payment_link")(
            amount=50000, currency="INR", description=""
        )
        assert "error" in result
        assert "required" in result["error"]


class TestListInvoicesTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        self.cred = MagicMock()
        self.cred.get.return_value = "rzp_test_key"
        self.env_patcher = patch.dict("os.environ", {"RAZORPAY_API_SECRET": "secret"})
        self.env_patcher.start()
        register_tools(self.mcp, credentials=self.cred)

    def teardown_method(self):
        self.env_patcher.stop()

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get")
    def test_list_invoices_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "count": 2,
                    "items": [
                        {"id": "inv_1", "amount": 50000, "status": "paid"},
                        {"id": "inv_2", "amount": 30000, "status": "issued"},
                    ],
                }
            ),
        )
        result = self._fn("razorpay_list_invoices")(count=10)
        assert result["count"] == 2
        assert len(result["invoices"]) == 2

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get")
    def test_list_invoices_with_filter(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"count": 0, "items": []})
        )
        self._fn("razorpay_list_invoices")(count=10, type_filter="invoice")
        call_params = mock_get.call_args.kwargs["params"]
        assert call_params["type"] == "invoice"


class TestGetInvoiceTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        self.cred = MagicMock()
        self.cred.get.return_value = "rzp_test_key"
        self.env_patcher = patch.dict("os.environ", {"RAZORPAY_API_SECRET": "secret"})
        self.env_patcher.start()
        register_tools(self.mcp, credentials=self.cred)

    def teardown_method(self):
        self.env_patcher.stop()

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.get")
    def test_get_invoice_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "id": "inv_123",
                    "amount": 50000,
                    "status": "paid",
                    "line_items": [{"name": "Item 1", "amount": 50000}],
                }
            ),
        )
        result = self._fn("razorpay_get_invoice")(invoice_id="inv_123")
        assert result["id"] == "inv_123"
        assert len(result["line_items"]) == 1

    def test_get_invoice_invalid_id(self):
        result = self._fn("razorpay_get_invoice")(invoice_id="invalid_id")
        assert "error" in result
        assert "Must match pattern" in result["error"]


class TestCreateRefundTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        self.cred = MagicMock()
        self.cred.get.return_value = "rzp_test_key"
        self.env_patcher = patch.dict("os.environ", {"RAZORPAY_API_SECRET": "secret"})
        self.env_patcher.start()
        register_tools(self.mcp, credentials=self.cred)

    def teardown_method(self):
        self.env_patcher.stop()

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.post")
    def test_create_refund_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "id": "rfnd_123",
                    "payment_id": "pay_456",
                    "amount": 50000,
                    "status": "processed",
                }
            ),
        )
        result = self._fn("razorpay_create_refund")(payment_id="pay_456")
        assert result["id"] == "rfnd_123"
        assert result["status"] == "processed"

    def test_create_refund_validation(self):
        # Invalid payment ID
        result = self._fn("razorpay_create_refund")(payment_id="invalid")
        assert "error" in result
        assert "Must match pattern: pay_[A-Za-z0-9]+" in result["error"]

        # Negative amount
        result = self._fn("razorpay_create_refund")(payment_id="pay_123", amount=-100)
        assert "error" in result
        assert "positive" in result["error"]

    @patch("aden_tools.tools.razorpay_tool.razorpay_tool.httpx.post")
    def test_create_refund_timeout(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timed out")
        result = self._fn("razorpay_create_refund")(payment_id="pay_123")
        assert "error" in result
        assert "timed out" in result["error"]


# --- Credential spec tests ---


class TestCredentialSpec:
    def test_razorpay_credential_spec_exists(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "razorpay" in CREDENTIAL_SPECS

    def test_razorpay_spec_env_var(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["razorpay"]
        assert spec.env_var == "RAZORPAY_API_KEY"

    def test_razorpay_spec_tools(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["razorpay"]
        expected_tools = [
            "razorpay_list_payments",
            "razorpay_get_payment",
            "razorpay_create_payment_link",
            "razorpay_list_invoices",
            "razorpay_get_invoice",
            "razorpay_create_refund",
        ]
        for tool in expected_tools:
            assert tool in spec.tools
        assert len(spec.tools) == 6

    def test_razorpay_spec_health_check(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["razorpay"]
        assert spec.health_check_endpoint == "https://api.razorpay.com/v1/payments?count=1"
        assert spec.health_check_method == "GET"

    def test_razorpay_spec_auth_support(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["razorpay"]
        assert spec.aden_supported is False
        assert spec.direct_api_key_supported is True
        assert "dashboard.razorpay.com" in spec.api_key_instructions

    def test_razorpay_secret_credential_spec_exists(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "razorpay_secret" in CREDENTIAL_SPECS
        spec = CREDENTIAL_SPECS["razorpay_secret"]
        assert spec.env_var == "RAZORPAY_API_SECRET"
        assert spec.credential_group == "razorpay"
        assert spec.credential_id == "razorpay_secret"
        assert spec.credential_key == "api_secret"

    def test_razorpay_credentials_share_group(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        razorpay_spec = CREDENTIAL_SPECS["razorpay"]
        razorpay_secret_spec = CREDENTIAL_SPECS["razorpay_secret"]

        # Both should be in the same credential group
        assert razorpay_spec.credential_group == "razorpay"
        assert razorpay_secret_spec.credential_group == "razorpay"

        # Both should have the same tools list
        assert razorpay_spec.tools == razorpay_secret_spec.tools
