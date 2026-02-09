"""
QuickBooks Tool - Real QuickBooks Online API integration via FastMCP tools.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Union

import httpx
from fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)


class QuickBooksClient:
    """Client for interacting with QuickBooks Online API v3."""

    BASE_URL = "https://quickbooks.api.intuit.com/v3/company"

    def __init__(self, access_token: str, realm_id: str):
        self.access_token = access_token
        self.realm_id = realm_id
        self.client = httpx.Client(
            base_url=f"{self.BASE_URL}/{self.realm_id}",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            params={"minorversion": "65"},
            timeout=30.0,
        )

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """Send request to QuickBooks API with standardized error handling."""
        try:
            response = self.client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            content_type = e.response.headers.get("Content-Type", "")

            if "application/json" in content_type:
                error_data = e.response.json()
                error_msg = error_data.get("Fault", {}).get("Error", [{}])[0].get("Detail", str(error_data))
            else:
                error_msg = e.response.text[:200]

            if status == 401:
                logger.error("QuickBooks: Invalid or expired token.")
            elif status == 403:
                logger.error("QuickBooks: Insufficient permissions or scope.")
            elif status == 400:
                logger.error(f"QuickBooks: Bad request / validation error - {error_msg}")
            elif status == 429:
                logger.error("QuickBooks: Rate limit exceeded.")
            else:
                logger.error(f"QuickBooks HTTP {status}: {error_msg}")

            raise RuntimeError(f"QuickBooks API failed ({status}): {error_msg}") from e

        except httpx.RequestError as e:
            logger.error(f"QuickBooks network error: {str(e)}")
            raise RuntimeError(f"Network error contacting QuickBooks: {str(e)}") from e

        except Exception as e:
            logger.exception("Unexpected QuickBooks client error")
            raise RuntimeError(f"Unexpected QuickBooks error: {str(e)}") from e


def register_tools(mcp: FastMCP, credentials=None) -> None:
    """Register QuickBooks tools with FastMCP."""

    def get_client() -> QuickBooksClient:
        if credentials is None:
            raise ValueError("Credentials provider not available for QuickBooks tools")

        # Adjust according to your actual credentials interface
        credentials.validate_for_tools(["quickbooks"])
        access_token = credentials.get("quickbooks_access_token")
        realm_id = credentials.get("quickbooks_realm_id")

        if not access_token or not realm_id:
            raise ValueError("Missing QuickBooks access token or realm ID")

        return QuickBooksClient(access_token, realm_id)

    @mcp.tool()
    def quickbooks_create_invoice(
        customer_id: str,
        line_items: List[Dict[str, Any]],
        due_date: str,
        memo: Optional[str] = None,
        custom_fields: Optional[List[Dict[str, Any]]] = None,
        discount: Optional[float] = None,
        tax: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create an invoice for a customer in QuickBooks Online.
        Returns JSON string with basic invoice info or error message.
        """
        try:
            client = get_client()

            payload: Dict[str, Any] = {
                "Line": line_items,
                "CustomerRef": {"value": customer_id},
                "DueDate": due_date,
            }

            if memo:
                payload["CustomerMemo"] = {"value": memo}

            if custom_fields:
                payload["CustomField"] = custom_fields

            # Note: discount and tax usually require special Line items in QBO
            # Simple total discount line would need to be added to `Line` here

            result = client._request("POST", "/invoice", json=payload)
            invoice = result["Invoice"]

            return json.dumps(
                {
                    "success": True,
                    "InvoiceID": invoice["Id"],
                    "InvoiceNumber": invoice.get("DocNumber"),
                    "TotalAmount": invoice.get("TotalAmt"),
                    "Balance": invoice.get("Balance"),
                    "Status": invoice.get("EmailStatus", "NotEmailed"),
                    "Created": invoice.get("MetaData", {}).get("CreateTime"),
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @mcp.tool()
    def quickbooks_get_invoice(invoice_id: str) -> str:
        """Retrieve complete invoice details by ID. Returns JSON."""
        try:
            client = get_client()
            result = client._request("GET", f"/invoice/{invoice_id}")
            return json.dumps(result.get("Invoice", {}), indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @mcp.tool()
    def quickbooks_search_customers(
        query: str,
        limit: int = 10,
        active_only: bool = True,
    ) -> str:
        """Search customers by name or email. Returns JSON list."""
        try:
            client = get_client()

            where = f"DisplayName LIKE '%{query.replace("'", "\\'")}%' OR PrimaryEmailAddr.Address LIKE '%{query.replace("'", "\\'")}%'"
            if active_only:
                where += " AND Active = true"

            sql = f"SELECT * FROM Customer WHERE {where} MAXRESULTS {limit}"
            result = client._request("GET", "/query", params={"query": sql})

            customers = result.get("QueryResponse", {}).get("Customer", [])

            formatted = [
                {
                    "ID": c["Id"],
                    "Name": c.get("DisplayName"),
                    "Email": c.get("PrimaryEmailAddr", {}).get("Address"),
                    "Company": c.get("CompanyName"),
                    "Balance": c.get("Balance", 0.0),
                    "Active": c.get("Active", True),
                }
                for c in customers
            ]

            return json.dumps({"success": True, "customers": formatted}, indent=2)

        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @mcp.tool()
    def quickbooks_create_customer(
        display_name: str,
        email: str,
        phone: Optional[str] = None,
        billing_address: Optional[Dict[str, Any]] = None,
        company_name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> str:
        """Create a new customer in QuickBooks. Returns JSON."""
        try:
            client = get_client()

            payload: Dict[str, Any] = {
                "DisplayName": display_name,
                "PrimaryEmailAddr": {"Address": email},
            }

            if phone:
                payload["PrimaryPhone"] = {"FreeFormNumber": phone}
            if company_name:
                payload["CompanyName"] = company_name
            if notes:
                payload["Note"] = notes
            if billing_address:
                payload["BillAddr"] = billing_address

            result = client._request("POST", "/customer", json=payload)
            customer = result["Customer"]

            return json.dumps(
                {
                    "success": True,
                    "CustomerID": customer["Id"],
                    "DisplayName": customer["DisplayName"],
                    "Email": customer.get("PrimaryEmailAddr", {}).get("Address"),
                    "Created": customer.get("MetaData", {}).get("CreateTime"),
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @mcp.tool()
    def quickbooks_record_payment(
        invoice_id: str,
        amount: float,
        payment_date: str,
        payment_method: Optional[str] = None,
        reference_number: Optional[str] = None,
    ) -> str:
        """Record a payment against an invoice. Returns JSON summary."""
        try:
            client = get_client()

            # Get customer ref from invoice
            inv_data = client._request("GET", f"/invoice/{invoice_id}")
            customer_ref = inv_data["Invoice"]["CustomerRef"]

            payload = {
                "TotalAmt": amount,
                "TxnDate": payment_date,
                "CustomerRef": customer_ref,
                "Line": [
                    {
                        "Amount": amount,
                        "LinkedTxn": [{"TxnId": invoice_id, "TxnType": "Invoice"}],
                    }
                ],
            }

            if reference_number:
                payload["PaymentRefNum"] = reference_number
            # payment_method would require PaymentMethodRef (list entity)

            result = client._request("POST", "/payment", json=payload)
            payment = result["Payment"]

            # Optional: refresh invoice to get updated balance
            updated_inv = client._request("GET", f"/invoice/{invoice_id}")["Invoice"]

            return json.dumps(
                {
                    "success": True,
                    "PaymentID": payment["Id"],
                    "AmountApplied": payment["TotalAmt"],
                    "PaymentDate": payment["TxnDate"],
                    "RemainingBalance": updated_inv.get("Balance", 0.0),
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @mcp.tool()
    def quickbooks_create_expense(
        payee: str,               # vendor name (will try to match or create minimally)
        amount: float,
        expense_account_id: str,  # expense category account ID
        bank_account_id: Optional[str] = None,
        date: Optional[str] = None,
        memo: Optional[str] = None,
        payment_method: Optional[str] = None,
    ) -> str:
        """
        Create an expense (Purchase) in QuickBooks.
        payee is treated as Vendor name (simple version).
        """
        try:
            client = get_client()

            line_detail = {
                "Amount": amount,
                "DetailType": "AccountBasedExpenseLineDetail",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": expense_account_id},
                },
            }

            payload = {
                "Line": [line_detail],
                "PaymentType": "Cash",  # can be Cash, Check, CreditCard, etc.
                "EntityRef": {"name": payee, "type": "Vendor"},
            }

            if bank_account_id:
                payload["AccountRef"] = {"value": bank_account_id}  # account paid from

            if date:
                payload["TxnDate"] = date
            if memo:
                payload["PrivateNote"] = memo

            # payment_method would require reference to PaymentMethod entity

            result = client._request("POST", "/purchase", json=payload)
            expense = result["Purchase"]

            return json.dumps(
                {
                    "success": True,
                    "ExpenseID": expense["Id"],
                    "Amount": expense["TotalAmt"],
                    "Date": expense.get("TxnDate"),
                    "Payee": expense.get("EntityRef", {}).get("name"),
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)