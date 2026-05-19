"""QuickBooks Online Accounting API integration.

Provides accounting operations via the QuickBooks Online REST API.
Requires QUICKBOOKS_ACCESS_TOKEN and QUICKBOOKS_REALM_ID.
Uses OAuth 2.0 Bearer token auth.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP

PROD_URL = "https://quickbooks.api.intuit.com/v3/company"
SANDBOX_URL = "https://sandbox-quickbooks.api.intuit.com/v3/company"


def _get_config() -> tuple[str, str] | dict:
    """Return (base_url, headers) or error dict."""
    token = os.getenv("QUICKBOOKS_ACCESS_TOKEN", "")
    realm_id = os.getenv("QUICKBOOKS_REALM_ID", "")
    if not token or not realm_id:
        return {
            "error": "QUICKBOOKS_ACCESS_TOKEN and QUICKBOOKS_REALM_ID are required",
            "help": "Set QUICKBOOKS_ACCESS_TOKEN and QUICKBOOKS_REALM_ID environment variables",
        }

    use_sandbox = os.getenv("QUICKBOOKS_SANDBOX", "").lower() in ("1", "true")
    base = SANDBOX_URL if use_sandbox else PROD_URL
    base_url = f"{base}/{realm_id}"
    return base_url, token


def _headers(token: str, content_type: str = "application/json") -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": content_type,
    }


def _get(url: str, token: str, params: dict | None = None) -> dict:
    resp = httpx.get(url, headers=_headers(token), params=params, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _post(url: str, token: str, body: dict) -> dict:
    resp = httpx.post(url, headers=_headers(token), json=body, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register QuickBooks tools."""

    @mcp.tool()
    def quickbooks_query(
        entity: str,
        where: str = "",
        order_by: str = "",
        max_results: int = 100,
        start_position: int = 1,
    ) -> dict:
        """Query QuickBooks entities using the query API.

        Args:
            entity: Entity type to query (e.g. 'Customer', 'Invoice',
                'Item', 'Vendor', 'Bill', 'Payment').
            where: Optional WHERE clause (e.g. "Active = true AND DisplayName LIKE 'ABC%'").
            order_by: Optional ORDER BY clause (e.g. "DisplayName ASC").
            max_results: Maximum results to return (default 100, max 1000).
            start_position: Starting position for pagination (default 1).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, token = cfg
        if not entity:
            return {"error": "entity is required"}

        query = f"SELECT * FROM {entity}"
        if where:
            query += f" WHERE {where}"
        if order_by:
            query += f" ORDERBY {order_by}"
        query += f" STARTPOSITION {start_position} MAXRESULTS {min(max_results, 1000)}"

        url = f"{base_url}/query"
        data = _get(url, token, params={"query": query, "minorversion": "73"})
        if "error" in data:
            return data

        qr = data.get("QueryResponse", {})
        entities = qr.get(entity, [])
        return {
            "count": len(entities),
            "total_count": qr.get("totalCount"),
            "entities": entities,
        }

    @mcp.tool()
    def quickbooks_get_entity(
        entity: str,
        entity_id: str,
    ) -> dict:
        """Get a specific QuickBooks entity by ID.

        Args:
            entity: Entity type (e.g. 'Customer', 'Invoice', 'Item', 'Vendor').
            entity_id: The entity ID.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, token = cfg
        if not entity or not entity_id:
            return {"error": "entity and entity_id are required"}

        url = f"{base_url}/{entity.lower()}/{entity_id}"
        data = _get(url, token, params={"minorversion": "73"})
        if "error" in data:
            return data

        return data.get(entity, data)

    @mcp.tool()
    def quickbooks_create_customer(
        display_name: str,
        email: str = "",
        phone: str = "",
    ) -> dict:
        """Create a new customer in QuickBooks.

        Args:
            display_name: Customer display name (must be unique).
            email: Customer email address.
            phone: Customer phone number.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, token = cfg
        if not display_name:
            return {"error": "display_name is required"}

        body: dict[str, Any] = {"DisplayName": display_name}
        if email:
            body["PrimaryEmailAddr"] = {"Address": email}
        if phone:
            body["PrimaryPhone"] = {"FreeFormNumber": phone}

        url = f"{base_url}/customer"
        data = _post(url, token, body)
        if "error" in data:
            return data

        customer = data.get("Customer", {})
        return {
            "result": "created",
            "id": customer.get("Id"),
            "display_name": customer.get("DisplayName"),
            "sync_token": customer.get("SyncToken"),
        }

    @mcp.tool()
    def quickbooks_create_invoice(
        customer_id: str,
        line_items: str,
    ) -> dict:
        """Create an invoice in QuickBooks.

        Args:
            customer_id: Customer ID to invoice.
            line_items: JSON array of line items. Each item:
                {"description": "...", "amount": 100.00,
                "item_id": "1"}.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, token = cfg
        if not customer_id or not line_items:
            return {"error": "customer_id and line_items are required"}

        import json

        try:
            items = json.loads(line_items)
        except json.JSONDecodeError:
            return {"error": "line_items must be valid JSON"}
        if not isinstance(items, list) or len(items) == 0:
            return {"error": "line_items must be a non-empty JSON array"}

        lines = []
        for item in items:
            line: dict[str, Any] = {
                "Amount": item.get("amount", 0),
                "DetailType": "SalesItemLineDetail",
                "Description": item.get("description", ""),
                "SalesItemLineDetail": {},
            }
            if "item_id" in item:
                line["SalesItemLineDetail"]["ItemRef"] = {"value": item["item_id"]}
            if "quantity" in item and "unit_price" in item:
                line["SalesItemLineDetail"]["Qty"] = item["quantity"]
                line["SalesItemLineDetail"]["UnitPrice"] = item["unit_price"]
            lines.append(line)

        body = {
            "CustomerRef": {"value": customer_id},
            "Line": lines,
        }

        url = f"{base_url}/invoice"
        data = _post(url, token, body)
        if "error" in data:
            return data

        invoice = data.get("Invoice", {})
        return {
            "result": "created",
            "id": invoice.get("Id"),
            "doc_number": invoice.get("DocNumber"),
            "total_amt": invoice.get("TotalAmt"),
            "balance": invoice.get("Balance"),
            "sync_token": invoice.get("SyncToken"),
        }

    @mcp.tool()
    def quickbooks_get_company_info() -> dict:
        """Get QuickBooks company information."""
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, token = cfg

        # Extract realm_id from the base_url
        realm_id = base_url.rsplit("/", 1)[-1]
        url = f"{base_url}/companyinfo/{realm_id}"
        data = _get(url, token, params={"minorversion": "73"})
        if "error" in data:
            return data

        info = data.get("CompanyInfo", {})
        return {
            "company_name": info.get("CompanyName"),
            "legal_name": info.get("LegalName"),
            "country": info.get("Country"),
            "email": info.get("Email", {}).get("Address")
            if isinstance(info.get("Email"), dict)
            else None,
            "fiscal_year_start": info.get("FiscalYearStartMonth"),
        }

    @mcp.tool()
    def quickbooks_list_invoices(
        status: str = "",
        customer_id: str = "",
        max_results: int = 100,
    ) -> dict:
        """List invoices from QuickBooks with optional filters.

        Args:
            status: Filter by status: 'Unpaid', 'Paid', 'Overdue' (optional).
                Uses Balance > 0 for Unpaid, Balance = 0 for Paid,
                DueDate < today for Overdue.
            customer_id: Filter by customer ID (optional).
            max_results: Maximum results (default 100, max 1000).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, token = cfg

        where_parts = []
        if status == "Unpaid":
            where_parts.append("Balance > '0'")
        elif status == "Paid":
            where_parts.append("Balance = '0'")
        elif status == "Overdue":
            import datetime

            today = datetime.date.today().isoformat()
            where_parts.append(f"DueDate < '{today}' AND Balance > '0'")
        if customer_id:
            where_parts.append(f"CustomerRef = '{customer_id}'")

        query = "SELECT * FROM Invoice"
        if where_parts:
            query += " WHERE " + " AND ".join(where_parts)
        query += f" MAXRESULTS {min(max_results, 1000)}"

        url = f"{base_url}/query"
        data = _get(url, token, params={"query": query, "minorversion": "73"})
        if "error" in data:
            return data

        qr = data.get("QueryResponse", {})
        invoices = qr.get("Invoice", [])
        return {
            "count": len(invoices),
            "invoices": [
                {
                    "id": inv.get("Id"),
                    "doc_number": inv.get("DocNumber"),
                    "customer_name": (inv.get("CustomerRef") or {}).get("name", ""),
                    "customer_id": (inv.get("CustomerRef") or {}).get("value", ""),
                    "total_amt": inv.get("TotalAmt"),
                    "balance": inv.get("Balance"),
                    "due_date": inv.get("DueDate"),
                    "txn_date": inv.get("TxnDate"),
                    "email_status": inv.get("EmailStatus"),
                }
                for inv in invoices
            ],
        }

    @mcp.tool()
    def quickbooks_get_customer(customer_id: str) -> dict:
        """Get detailed customer information from QuickBooks.

        Args:
            customer_id: Customer ID (required).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, token = cfg
        if not customer_id:
            return {"error": "customer_id is required"}

        url = f"{base_url}/customer/{customer_id}"
        data = _get(url, token, params={"minorversion": "73"})
        if "error" in data:
            return data

        c = data.get("Customer", {})
        email = c.get("PrimaryEmailAddr")
        phone = c.get("PrimaryPhone")
        addr = c.get("BillAddr") or {}
        return {
            "id": c.get("Id"),
            "display_name": c.get("DisplayName"),
            "company_name": c.get("CompanyName"),
            "given_name": c.get("GivenName"),
            "family_name": c.get("FamilyName"),
            "email": email.get("Address") if isinstance(email, dict) else None,
            "phone": phone.get("FreeFormNumber") if isinstance(phone, dict) else None,
            "balance": c.get("Balance"),
            "active": c.get("Active"),
            "billing_address": {
                "line1": addr.get("Line1", ""),
                "city": addr.get("City", ""),
                "state": addr.get("CountrySubDivisionCode", ""),
                "postal_code": addr.get("PostalCode", ""),
                "country": addr.get("Country", ""),
            },
            "sync_token": c.get("SyncToken"),
        }

    @mcp.tool()
    def quickbooks_create_payment(
        customer_id: str,
        total_amt: float,
        invoice_id: str = "",
    ) -> dict:
        """Record a payment in QuickBooks.

        Args:
            customer_id: Customer ID who is paying (required).
            total_amt: Payment amount (required).
            invoice_id: Invoice ID to apply payment to (optional).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, token = cfg
        if not customer_id or total_amt <= 0:
            return {"error": "customer_id and a positive total_amt are required"}

        body: dict[str, Any] = {
            "CustomerRef": {"value": customer_id},
            "TotalAmt": total_amt,
        }
        if invoice_id:
            body["Line"] = [
                {
                    "Amount": total_amt,
                    "LinkedTxn": [{"TxnId": invoice_id, "TxnType": "Invoice"}],
                }
            ]

        url = f"{base_url}/payment"
        data = _post(url, token, body)
        if "error" in data:
            return data

        payment = data.get("Payment", {})
        return {
            "result": "created",
            "id": payment.get("Id"),
            "total_amt": payment.get("TotalAmt"),
            "customer_id": (payment.get("CustomerRef") or {}).get("value"),
            "txn_date": payment.get("TxnDate"),
            "sync_token": payment.get("SyncToken"),
        }
