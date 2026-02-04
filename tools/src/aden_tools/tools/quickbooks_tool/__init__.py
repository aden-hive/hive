import logging
from typing import Any, Optional, Union
import httpx
from fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)

class QuickBooksClient:
    """Client for interacting with QuickBooks Online API."""
    
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
            params={"minorversion": "65"}
        )

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Handle API requests with error management."""
        try:
            response = self.client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            error_data = e.response.json() if e.response.headers.get("Content-Type") == "application/json" else e.response.text
            
            if status_code == 401:
                logger.error("QuickBooks: Invalid or expired token.")
            elif status_code == 403:
                logger.error("QuickBooks: Insufficient permissions.")
            elif status_code == 400:
                logger.error(f"QuickBooks: Validation error: {error_data}")
            elif status_code == 429:
                logger.error("QuickBooks: Rate limit exceeded.")
            
            raise e
        except Exception as e:
            logger.error(f"QuickBooks API Error: {str(e)}")
            raise e

    def create_invoice(self, customer_id: str, line_items: list[dict], due_date: str, **kwargs) -> dict:
        """Create an invoice in QuickBooks."""
        payload = {
            "Line": line_items,
            "CustomerRef": {"value": customer_id},
            "DueDate": due_date
        }
        # Add optional fields if provided
        if "memo" in kwargs:
            payload["CustomerMemo"] = {"value": kwargs["memo"]}
        if "discount" in kwargs:
            # Discount can be complex in QBO, usually a special Line item
            pass # Implementation depends on specific QBO requirements
        
        return self._request("POST", "/invoice", json=payload)["Invoice"]

    def get_invoice(self, invoice_id: str) -> dict:
        """Retrieve invoice details."""
        return self._request("GET", f"/invoice/{invoice_id}")["Invoice"]

    def search_customers(self, query: str, limit: int = 10, active_only: bool = True) -> list[dict]:
        """Search for customers using SQL-like query."""
        # QBO uses a SQL-like query language
        where_clause = f"DisplayName LIKE '%{query}%' OR PrimaryEmailAddr LIKE '%{query}%'"
        if active_only:
            where_clause = f"({where_clause}) AND Active = true"
            
        sql = f"SELECT * FROM Customer WHERE {where_clause} MAXRESULTS {limit}"
        return self._request("GET", f"/query?query={sql}").get("QueryResponse", {}).get("Customer", [])

    def create_customer(self, display_name: str, email: str, **kwargs) -> dict:
        """Add a new customer."""
        payload = {
            "DisplayName": display_name,
            "PrimaryEmailAddr": {"Address": email}
        }
        if "phone" in kwargs:
            payload["PrimaryPhone"] = {"FreeFormNumber": kwargs["phone"]}
        if "billing_address" in kwargs:
            payload["BillAddr"] = kwargs["billing_address"]
        if "company_name" in kwargs:
            payload["CompanyName"] = kwargs["company_name"]
        if "notes" in kwargs:
            payload["Notes"] = kwargs["notes"]
            
        return self._request("POST", "/customer", json=payload)["Customer"]

    def record_payment(self, invoice_id: str, amount: float, payment_date: str, **kwargs) -> dict:
        """Record a payment against an invoice."""
        payload = {
            "TotalAmt": amount,
            "TxnDate": payment_date,
            "Line": [{
                "Amount": amount,
                "LinkedTxn": [{"TxnId": invoice_id, "TxnType": "Invoice"}]
            }],
            "CustomerRef": self.get_invoice(invoice_id)["CustomerRef"]
        }
        if "payment_method" in kwargs:
            # PaymentMethod is usually a reference to an existing object
            pass
        if "reference_number" in kwargs:
            payload["PaymentRefNum"] = kwargs["reference_number"]
            
        return self._request("POST", "/payment", json=payload)["Payment"]

    def create_expense(self, payee: str, amount: float, account_id: str, **kwargs) -> dict:
        """Track expenses (Purchase in QBO)."""
        payload = {
            "PaymentType": "Cash", # Defaulting for MVP
            "AccountRef": {"value": account_id}, # Usually the bank account paid from
            "Line": [{
                "Amount": amount,
                "DetailType": "AccountBasedExpenseLineDetail",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": account_id} # The expense category account
                }
            }],
            "EntityRef": {"name": payee, "type": "Vendor"}
        }
        if "memo" in kwargs:
            payload["PrivateNote"] = kwargs["memo"]
        if "date" in kwargs:
            payload["TxnDate"] = kwargs["date"]
            
        return self._request("POST", "/purchase", json=payload)["Purchase"]

def register_tools(mcp: FastMCP, credentials=None):
    """Register QuickBooks tools."""

    def get_client() -> QuickBooksClient:
        if not credentials:
            raise ValueError("Credential manager not provided.")
        
        credentials.validate_for_tools(["quickbooks_create_invoice"])
        access_token = credentials.get("quickbooks_access_token")
        realm_id = credentials.get("quickbooks_realm_id")
        
        if not access_token or not realm_id:
            raise ValueError("QuickBooks credentials missing.")
            
        return QuickBooksClient(access_token, realm_id)

    @mcp.tool()
    def quickbooks_create_invoice(
        customer_id: str, 
        line_items: list[dict], 
        due_date: str,
        memo: Optional[str] = None,
        custom_fields: Optional[list[dict]] = None,
        discount: Optional[float] = None,
        tax: Optional[dict] = None
    ) -> str:
        """
        Create an invoice for a customer.
        
        Args:
            customer_id: QuickBooks Customer ID.
            line_items: List of line items, e.g., [{"Amount": 100.0, "Description": "Service", "DetailType": "SalesItemLineDetail", "SalesItemLineDetail": {"ItemRef": {"value": "1"}}}]
            due_date: Due date in YYYY-MM-DD format.
            memo: Optional memo for the invoice.
            custom_fields: Optional list of custom fields: [{"DefinitionId": "1", "StringValue": "value"}]
            discount: Optional discount amount.
            tax: Optional tax detail.
        """
        try:
            client = get_client()
            params = {"memo": memo}
            if custom_fields:
                params["custom_fields"] = custom_fields
            if discount:
                # Add discount as a line item if possible or special handling
                pass
            if tax:
                params["tax"] = tax
                
            invoice = client.create_invoice(customer_id, line_items, due_date, **params)
            import json
            return json.dumps({
                "InvoiceID": invoice["Id"],
                "InvoiceNumber": invoice.get("DocNumber"),
                "TotalAmount": invoice["TotalAmt"],
                "Status": invoice.get("EmailStatus", "Created")
            }, indent=2)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def quickbooks_get_invoice(invoice_id: str) -> str:
        """Retrieve complete invoice details by ID."""
        try:
            client = get_client()
            invoice = client.get_invoice(invoice_id)
            import json
            return json.dumps(invoice, indent=2)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def quickbooks_search_customers(query: str, limit: int = 10, active_only: bool = True) -> str:
        """Search for customers by name, email, or ID."""
        try:
            client = get_client()
            customers = client.search_customers(query, limit, active_only)
            import json
            # Returns: List of matching customers with ID, name, email, balance
            formatted = []
            for c in customers:
                formatted.append({
                    "ID": c["Id"],
                    "Name": c.get("DisplayName"),
                    "Email": c.get("PrimaryEmailAddr", {}).get("Address"),
                    "Balance": c.get("Balance")
                })
            return json.dumps(formatted, indent=2)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def quickbooks_create_customer(
        display_name: str, 
        email: str,
        phone: Optional[str] = None,
        billing_address: Optional[dict] = None,
        company_name: Optional[str] = None,
        notes: Optional[str] = None
    ) -> str:
        """Add a new customer to QuickBooks."""
        try:
            client = get_client()
            customer = client.create_customer(
                display_name, 
                email, 
                phone=phone, 
                billing_address=billing_address,
                company_name=company_name, 
                notes=notes
            )
            import json
            return json.dumps(customer, indent=2)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def quickbooks_record_payment(
        invoice_id: str, 
        amount: float, 
        payment_date: str,
        payment_method: Optional[str] = None,
        reference_number: Optional[str] = None
    ) -> str:
        """Record a payment against an invoice."""
        try:
            client = get_client()
            payment = client.record_payment(
                invoice_id, 
                amount, 
                payment_date, 
                payment_method=payment_method,
                reference_number=reference_number
            )
            
            # Fetch updated invoice to get remaining balance
            updated_invoice = client.get_invoice(invoice_id)
            
            import json
            # Returns: Payment ID, amount applied, remaining balance
            return json.dumps({
                "PaymentID": payment["Id"],
                "AmountApplied": amount,
                "RemainingBalance": updated_invoice.get("Balance")
            }, indent=2)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def quickbooks_create_expense(
        payee: str, 
        amount: float, 
        account_id: str,
        payment_method: Optional[str] = None,
        date: Optional[str] = None,
        memo: Optional[str] = None,
        attachments: Optional[list[str]] = None
    ) -> str:
        """Track business expenses and bills."""
        try:
            client = get_client()
            expense = client.create_expense(
                payee, 
                amount, 
                account_id, 
                payment_method=payment_method,
                date=date,
                memo=memo
            )
            if attachments:
                # QBO attachments are handled via Attachable endpoint, not implemented in MVP
                logger.warning("QuickBooks: Attachments not yet supported in MVP.")
                
            import json
            return json.dumps(expense, indent=2)
        except Exception as e:
            return f"Error: {str(e)}"
