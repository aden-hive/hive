"""
NetSuite Tool - Manage ERP records via NetSuite REST API.

Supports:
- Token Based Authentication (TBA)
- OAuth1 credentials via the credential store

API Reference: https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_1540391670.html
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any

import time
import os
import httpx
from fastmcp import FastMCP
from requests_oauthlib import OAuth1

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


class _NetSuiteClient:
    def __init__(self, 
                 account_id: str, 
                 consumer_key: str,
                 consumer_secret: str,
                 token_id: str,
                 token_secret:str):
        self.base_url = f"https://{account_id}.suitetalk.api.netsuite.com/services/rest/record/v1"
        self.account_id = account_id
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.token_id = token_id
        self.token_secret = token_secret
        self.oauth = OAuth1(
                      client_key = self.consumer_key,
                      client_secret = self.consumer_secret,
                      resource_owner_key = self.token_id,
                      resource_owner_secret = self.token_secret,
                      signature_method="HMAC-SHA256",
                      realm = self.account_id,
                      )


    @property
    def _headers(self):
        """Headers uses oauth"""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json" 
        }
    
    def _url(self, path: str) -> str:
        """Get url"""
        return f"{self.base_url}/{path}"
    
    def _handle_response(self, response) -> dict[str, Any]:
        """Handle NetSuite API responses."""
        if response.status_code >= 400:
            try:
                return {
                    "success": False,
                    "error": response.json().get("title")
                }
            except Exception:
                return {
                    "success": False,
                    "error": response.text
                }
        if response.status_code == 204:
            return {"success": True}
        return {
            "success": True,
            "data": response.json()
            }
    
    def _request(self, 
                 method: str,
                 path: str,
                 *,
                 params: dict | None = None,
                 json: dict | None = None,
                 retries: int = 3) -> dict[str, Any]:
        """Centralized HTTP request handler."""
        for attempt in range(retries):
            try:
                response = httpx.request(
                    method = method,
                    url = self._url(path),
                    headers = self._headers,
                    auth = self.oauth,
                    params = params,
                    json = json,
                    timeout = 30
                )
                if response.status_code == 429 and attempt < retries - 1:
                    time.sleep(min(2 ** attempt, 10))
                    continue
                return self._handle_response(response)
            except httpx.RequestError as e:
                if attempt == retries - 1:
                    return {
                    "success": False,
                    "error": str(e)
                }
        return {
            "success": False,
            "error": "Max retries exceeded"
        }

            
    # Customer methods
    def create_customer(
            self,
            company_name: str,
            email: str | None = None,
            phone: str | None = None
            ) -> dict[str, Any]:
        """Create a new NetSuite customer. """
        if not company_name:
            raise ValueError("companyName is required")
        body = {"companyName": company_name}
        if email:
            body["email"] = email
        if phone:
            body["phone"] = phone
        return self._request("POST", "customer", json=body)
    
    def list_customers(self,
                       limit: int = 20,
                       offset: int = 0,
                       ) -> dict[str, Any]:
        """Lists customers from NetSuite. """
        params = {
            "limit": limit,
            "offset": offset
        }
        result = self._request("GET", "customer", params = params)
        if not result["success"]:
            return result
        data = result.get("data", {})

        return {
           "success": True,
            "count": data.get("count"),
            "customers": data.get("items", [])
        }
    
    def update_customer(
            self,
            customer_id: str,
            company_name: str | None = None,
            email: str | None = None,
            phone: str | None = None
    ) -> dict[str, Any]: 
        """Update existing customer details."""
        body = {}
        if company_name:
            body["companyName"] = company_name 
        if email:
            body["email"] = email
        if phone:
            body["phone"] = phone
        if not body:
            raise ValueError("No fields provided for update.")
        return self._request("PATCH", f"customer/{customer_id}", json = body)
        
    def get_customer(
            self,
            customer_id: str
    ) -> dict[str, Any]:
        """Fetch an existing NetSuite customer. """
        if not customer_id:
            raise ValueError("customer_id is required")
        return self._request("GET", f"customer/{customer_id}")

    
    def delete_customer(
            self,
            customer_id : str,
    ) -> dict[str, Any]:
        """Delete an existing NetSuite customer. """
        if not customer_id:
            raise ValueError("customer_id is required")
        return self._request("DELETE",f"customer/{customer_id}" )
    
    # Ivoice methods
    def create_invoice(
            self,
            customer_id: str,
            items: list[dict]
    ) -> dict[str, Any]:
        """Create an invoice. """
        invoice_items = []
        for item in items:
            invoice_items.append({"item":{"id": item["item_id"]},
                                          "quantity": item["quantity"],
                                          "rate": item["rate"]
                                          })
        body = {"entity": {"id": customer_id},
                "item": {"items": invoice_items}}
        return self._request("POST","invoice", json = body)
    
    def get_invoice(
            self,
            invoice_id: str
    ) -> dict[str, Any]:
        """Fetch invoice. """
        if not invoice_id:
            raise ValueError("invoice_id is required")
        return self._request("GET", f"invoice/{invoice_id}")
    
    def update_invoice(
            self,
            invoice_id: str,
            update: dict
    ) -> dict[str, Any]:
        """Update existing invoice."""
        if not invoice_id:
            raise ValueError("invoice_id required.")
        if not update:
            raise ValueError("Update cannot be empty.")
        return self._request("PATCH",f"invoice/{invoice_id}", json = update)
    
    def delete_invoice(
            self,
            invoice_id: str
    ) -> dict[str, Any]:
        if not invoice_id:
            raise ValueError("No invoice_id to delete.")
        return self._request("DELETE",f"invoice/{invoice_id}")
    
    # Sales
    def list_sales_order(
            self,
            limit: int = 100,
            offset: int = 0
    ) -> dict[str, Any]:
        """List sales order."""
        params = {
            "limit": limit,
            "offset": offset
        }
        result = self._request("GET","salesOrder", params = params)
        if not result["success"]:
            return result
        data = result["data"]

        return {
           "success": True,
            "count": data.get("count"),
            "sales_orders": data.get("items", [])
        }
    
    def get_sales_order(
            self,
            order_id: str
    ) -> dict[str, Any]:
        """Fetch a sale order by ID. """
        if not order_id:
            raise ValueError("order_id is required")
        return self._request("GET", f"salesOrder/{order_id}")
    
    def create_sales_order(
            self,
            customer_id: str,
            items: list[dict]    
    ) -> dict[str, Any]:
        """Create sales order. """
        if not customer_id:
            raise ValueError("customer_id is required")
        if not items:
            raise ValueError("Items cannot be empty")
        sales_items = []
        for item in items:
            sales_items.append({
                "item": {"id": item["item_id"]},
                "quantity": item["quantity"],
                "rate": item["rate"]
            })
        body = {
            "entity": {"id": customer_id},
            "item": {"items": sales_items}
            }
        return self._request("POST", "salesOrder", json = body)
    
    def delete_sales_order(
            self,
            order_id : str
    ) -> dict[str, Any]:
        if not order_id:
            raise ValueError("order_id is required")
        return self._request("DELETE", f"salesOrder/{order_id}",)
    
    # Vendors
    def list_vendors(
            self,
            limit: int = 100,
            offset: int = 0
    ) -> dict[str, Any]:
        """List vendors"""
        params = {
            "limit": limit,
            "offset": offset
        }
        result = self._request("GET", "vendor", params = params)
        if not result["success"]:
            return result
        data = result["data"]

        return {
           "success": True,
            "count": data.get("count"),
            "vendors": data.get("items", [])
        }

    def get_vendor(
            self,
            vendor_id: str
    ) -> dict[str, Any]:
        """Fetch a vendor record by vendor_id. """
        if not vendor_id:
            raise ValueError("vendor_id is required")
        return self._request("GET",f"vendor/{vendor_id}")

    
    def create_vendor(
            self,
            company_name: str,
            email: str = None,
            phone: str = None
    ) -> dict[str, Any]: 
        """Create a vendor"""
        if not company_name:
            raise ValueError("company_name is required") 
        body = {"companyName": company_name}
        if email:
            body["email"] = email
        if phone:
            body["phone"] = phone
        return self._request("POST", "vendor", json = body)
    
    def delete_vendor(
            self,
            vendor_id: str
    ) -> dict[str, Any]:
        """Delete vendor"""
        if not vendor_id:
            raise ValueError("vendor_id is required")
        return self._request("DELETE", f"vendor/{vendor_id}")
    

    # transactions
    def list_transactions(
            self,
            limit: int = 100,
            offset: int = 0
    ) -> dict[str, Any]:
        """Fetch a list of transfer orders with pagination."""
        params = {
            "limit": limit,
            "offset": offset
        }
        result = self._request("GET", "transferOrder", params = params)
        if not result["success"]:
            return result
        data = result["data"]

        return {
           "success": True,
            "count": data.get("count"),
            "transactions": data.get("items", [])
        }
    
    def get_transaction(
            self,
            transaction_id: str
    ) -> dict[str, Any]:
        """Fetch a single transfer order by transaction_id."""
        if not transaction_id:
            raise ValueError("transaction_id is required")
        return self._request("GET", f"transferOrder/{transaction_id}")
    
    def create_transaction(
            self,
                location_id: str,
                items: list[dict],
                memo: str = None
        ) -> dict[str, Any]:
        """Create a transfer order (transaction) at a specific location with items."""

        if not location_id:
            raise ValueError("location_id is required")
        if not items:
            raise ValueError("items can not be empty")
        transaction_items = []
        for item in items:
            transaction_items.append({
            "item": {"id": item["item_id"]},
            "quantity": item["quantity"]
        })

        body = {
            "location": {"id": location_id},
            "item": {"items": transaction_items}
            }

        if memo:
            body["memo"] = memo
        return self._request("POST", "transferOrder", json = body)
    
    def delete_transaction(
            self,
            transaction_id: str
    ) -> dict[str, Any]:
        """Delete a transaction using transfer order ID"""
        if not transaction_id:
            raise ValueError("transaction_id can not be empty")
        return self._request("DELETE", f"transferOrder/{transaction_id}")
    

def register_tools(
        mcp: FastMCP,
        credentials: CredentialStoreAdapter | None = None
) -> None:
    """Register NetSuite Tool with the MCP server"""
    def _get_credentials(account: str = ""):
        """Get NetSuite, keys/token from credential management or environment"""
        if credentials is not None:
            return credentials.get("netsuite", account)
        return {
            "account_id": os.getenv("NETSUITE_ACCOUNT_ID"),
            "consumer_key": os.getenv("NETSUITE_CONSUMER_KEY"),
            "consumer_secret": os.getenv("NETSUITE_CONSUMER_SECRET"),
            "token_id": os.getenv("Token_ID"),
            "token_secret": os.getenv("TOKEN_SECRET")
        }
    
    def _get_client(account: str = "") ->_NetSuiteClient |dict:
        """Gets NetSuite client or return an error dictionary if no credentials"""
        cred = _get_credentials(account)
        if not cred or cred.get("account_id"):
            return {
                "error": "NetSuite credentials not configured"
            }
        

    #------Account management----------
    @mcp.tool()
    def netsuite_create_customer(
        company_name: str,
        email: str | None = None,
        phone: str | None = None,
        account: str = ""
    ) -> dict:
        """Create a NetSuite customer Record.

        Args:
            company_name: Name of the customer/company
            email: Optional email address.
            phone: Optional phone number.
            account: Optional credential alias

        Returns:
            Dictionary containing created customer data or error
        """
        if not company_name:
            return {"error": "Company name is required"}
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.create_customer(
                company_name = company_name,
                email = email,
                phone = phone)
            if not result.get("success"):
                return result
            return {
                "success": True,
                "customer": result.get("data")
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        

    @mcp.tool()
    def netsuite_get_customer(
        customer_id: str,
        account: str = ""
    ) -> dict:
        """Get a NetSuite Customer record.

        Args:
            customer_id: Customer ID
            account : Optional credential alias

        Returns:
            Dictionary containing customer details or error.
        """
        if not customer_id:
            return {"error": "customer_id is required."}
        customer_id = customer_id.strip()
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.get_customer(customer_id = customer_id)
            if not result.get("success"):
                return result
            return {
                "success": True,
                "customer": result.get("data")
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        
    @mcp.tool()
    def netsuite_update_customer(
        customer_id: str,
        company_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        account: str = ""
    ) -> dict:
        """Update NetSuite customer record.

        Args:
            customer_id: Customer ID
            company_name: Optional customer or company name.
            email: Optional email address.
            phone: Optional phone number.
            account: Optional account alias.

        Returns:
            Dictionary containing customer record update or error.
        """
        if not customer_id:
            return {"error": "customer_id is required"}
        if not any([company_name, email, phone]):
            return {"error": "At least one field must be provided for update"}
        customer_id = customer_id.strip()
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.update_customer(
                customer_id = customer_id
                company_name = company_name,
                email = email,
                phone = phone
                )
            if not result.get("success"):
                return result
            return {
                "success": True,
                "data": result.get("data")}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        
    @mcp.tool()
    def netsuite_list_customers(
        limit: int = 20,
        offset: int = 0,
        account: str = ""
    ) -> dict:
        """List NetSuite customers

        Args:
            limit: Optional number of customer per page.
            offset: Optional page to start listing customers from
            account: Optional account alias.

        Returns:
            Dictionary containing NetSuite customers
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_customers(
                limit = limit,
                offset = offset
            )
            if not result.get("success"):
                return result
            return {
                "success": True,
                "customers": result.get("data", [])
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        
        
    @mcp.tool()
    def netsuite_delete_customer(
        customer_id: str,
        account: str = ""
    ) -> dict:
        """Delete NetSuite customer record.

        Args:
            customer_id: Customer ID
            account: Optional account alias

        Returns:
            Dictionary containing success or error.
        """
        if not customer_id:
            return {"error": "customer_id is required"}
        customer_id = customer_id.strip()
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.delete_customer(customer_id = customer_id)
            if not result.get("success"):
                return result
            return {
                "success": True,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        
    #-----Invoice Tools------
    @mcp.tool()
    def netsuite_create_invoice(
        customer_id: str,
        items: list[dict],
        due_date: str | None = None,
        account: str = ""
    
    ) -> dict:
        """Create NetSuite invoice

        Args:
            customer_id: Customer ID
            items: List of items with quantity, rate and description
            due_date: Optional invoice due date
            account: Optional account alias

        Returns:
            Dictionary containing invoice details or error
        """
        if not customer_id:
            return {"error": "customer_id is required"}
        if not items:
            return {"error": "items is required"}
        customer_id = customer_id.strip()
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.create_invoice(
                customer_id = customer_id,
                items = items,
                due_date = due_date
            )
            if not result.get("success"):
                return result
            return {
                "success": True,
                "invoice": result.get("data")
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        
    
    @mcp.tool()
    def netsuite_get_invoice(
        invoice_id,
        account: str = ""
    ) -> dict:
        """Get NetSuite invoice details

        Args:
            invoice_id: ID of the invoice to retrieve
            account: Optional account alias

        Returns:
            Dictionary containing invoice details or error
        """
        if not invoice_id:
            return {"error": "invoice_id is required"}
        invoice_id = invoice_id.strip()
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.get_invoice(
                invoice_id = invoice_id
            )
            if not result.get("success"):
                return result
            return {
                "success": True,
                "invoice": result.get("invoice", [])
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        
    @mcp.tool()
    def netsuite_update_invoice(
        invoice_id: str,
        items: list[dict] | None = None,
        due_date: str | None = None,
        account: str = ""
    ) -> dict:
        """Update NetSuite invoice record.

        Args:
            invoice_id: Invoice ID
            items: Optional list of items to update (quantity, rate, description).
            due_data: Optional new due date
            account: Optional account alias

        Returns:
            Dictionary indicating success or error
        """
        if not invoice_id:
            return {"error": "invoice_id is required"}
        invoice_id = invoice_id.strip()
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.update_invoice(
                invoice_id = invoice_id,
                items = items,
                due_date = due_date)
            if not result.get("success"):
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        

    @mcp.tool()
    def netsuite_delete_invoice(
        invoice_id: str,
        account: str = ""
    ) -> dict:
        """Delete NetSuite invoice record.

        Args:
            invoice_id: ID of the invoice to be deleted
            account: Optional account alias

        Returns:
            Dictionary indicating success or containing error details
        """
        if not invoice_id:
            return {"error": "invoice_id cannot be empty"}
        invoice_id = invoice_id.strip()
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.delete_invoice(invoice_id = invoice_id)
            if not result.get("success"):
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        
        
    #-----Sales Tools-----
    @mcp.tool()
    def netsuite_list_sales(
        limit: int = 20,
        offset: int = 0,
        account: str = ""
        ) -> dict:
        """"List NetSuite sales order

        Args:
            limit: Number of sales order per page
            offset: Pagination offset
            account: Optional account alias

        Returns:
            Dictionary containing sales order or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_sales_order(
                limit = limit,
                offset = offset
            )
            if not result.get("success"):
                return result
            return {
                "success": True,
                "sales": result.get("data", [])}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        
    @mcp.tool()
    def netsuite_get_sales(
        sales_id: str,
        account: str = ""
    ) -> dict:
        """Get sales details

        Args:
            sales_id: Sale ID
            account: Optional account alias

        Returns:
            Dictionary containing sales details or error
        """
        if not sales_id:
            return {"error": "sale_id cannot be empty"}
        sales_id = sales_id.strip()
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.get_sales_order(sales_id = sales_id)
            if not result.get("success"):
                return result
            return {
                "success": True,
                "sales": result.get("data", [])
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        

    @mcp.tool()
    def netsuite_creat_sales_order(
        customer_id: str,
        items: list[dict],
        account: str = ""

    ) -> dict:
        """Create NetSuite sales order.

        Args:
            customer_id: Customer ID to create sales order for.
            items: Sales items to create sales order
            account: Optional account alias

        Returns:
            Dictionary containing sales order details
        """
        if not customer_id:
            return {"error": "customer_id cannot be empty"}
        customer_id = customer_id.strip()
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        return {"success": True}
    
    @mcp.tool()
    def netsuite_delete_sale_order(
        sales_id: str,
        account: str = ""
    ) -> dict:
        """Delete sales order

        Args:
            sales_id: Sales ID
            account: Optional account alias

        Returns:
            Dictionary indicating success or containing error details
        """
        if not sales_id:
            return {"error": "sales_id cannot be empty"}
        sales_id = sales_id.strip()
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.delete_sales_order(sales_id = sales_id)
            if not result.get("success"):
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        
    #-------vendor------------
    @mcp.tool()
    def netsuite_list_vendors(
        limit: int = 20,
        offset: int = 0,
        account: str = ""
    ) ->dict:
        """List vendors

        Args:
            limit: Number of vendors per page
            offset: Pagination offset
            account: Optional account alias

        Returns:
            Dictionary containing vendors details or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_vendors(
                limit = limit,
                offset = offset
            )
            if not result.get("success"):
                return result
            return {
                "success": True,
                "vendors": result.get("vendors", [])
                }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        
    @mcp.tool()
    def netsuite_get_vendor(
        vendor_id: str,
        account: str = ""
    ) -> dict:
        """Get vendor

        Args:
            vendor_id: Vendor ID
            account: Optional account alias

        Returns:
            Dictionary containing vendor's details
        """
        if not vendor_id:
            return {"error": "vendor_id cannot be empty"}
        vendor_id = vendor_id.strip()
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.get_vendor(vendor_id = vendor_id)
            if not result.get("success"):
                return result
            return {
                "success": True,
                "vendor": result.get("data", [])}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        
    @mcp.tool()
    def netsuite_create_vendor(
        company_name: str,
        email: str | None = None,
        phone: str | None = None,
        account: str = ""
    ) -> dict:
        """Create NetSuite vendor

        Args:
            company_name: Company name
            email: Optional email address
            phone: Optional phone number
            account: Optional account alias

        Returns:
            Dictionary indicating success or containing error details
        """
        if not company_name:
            return {"error": "company_name cannot be empty"}
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.create_vendor(
                company_name = company_name,
                email = email,
                phone = phone
            )
            if not result.get("success"):
                return result
            return {
                "success": True,
                "vendor": result.get("data")}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        

    @mcp.tool()
    def netsuite_delete_vendor(
        vendor_id: str,
        account: str = ""
    ) -> dict:
        """Delete NetSuite vendor

        Args:
            vendor_id: Vendor ID
            account: Optional account alias

        Returns:
            Dictionary indicating success or containing error details
        """
        if not vendor_id:
            return {"error": "vendor_id cannot be empty"}
        vendor_id = vendor_id.strip()
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.delete_vendor(vendor_id = vendor_id)
            if not result.get("success"):
                return result
            return {"Success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        

    #------transaction tool----------    
    @mcp.tool()
    def netsuite_list_transactions(
        limit: int = 20,
        offset: int = 0,
        account: str = ""
    ) -> dict:
        """List transfer order transactions.

        Args:
            limit: Number of transfer order per page.
            offset: Pagination offset
            account: Optional account alias

        Returns:
            Dictionary containing transfer order transaction or error.
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_transactions(
                limit = limit,
                offset = offset,   
            )
            if not result.get("success"):
                return result
            return {
                "success": True,
                "transactions": result.get("transactions", [])
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        
    @mcp.tool()
    def netsuite_get_transaction(
        transaction_id: str,
        account: str = ""
    ) -> dict:
        """Get transfer order transaction ID

        Args:
            transaction_id: Transfer order transaction ID
            account: Optional account alias

        Returns:
            Dictionary containing transfer order transaction details or error
        """
        if not transaction_id:
            return {"error": "transaction_id cannot be empty"}
        transaction_id = transaction_id.strip()
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.get_transaction(transaction_id = transaction_id)
            if not result.get("success"):
                return result
            return {
                "success": True,
                "transaction": result.get("data")
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
    
    @mcp.tool()
    def create_transaction(
        locations_id: str,
        items: list[dict],
        memo: str,
        account: str = ""
    ) -> dict:
        """Create transaction

        Args:
            locations_id: Location for transfer order
            items: 
            memo

        Returns:
            Dictionary indicating success or error details.
        """
        if not locations_id:
            return {"error": "location_id cannot be empty"}
        if not items:
            return {"error": "items cannot be empty"}
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.create_transaction(
                location_id = locations_id,
                items = items,
                memo = memo 
            )
            if not result.get("success"):
                return result
            return {
                "success": True,
                "transaction": result.get("data")
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        
    @mcp.tool()
    def netsuite_delete_transaction(
        transaction_id,
        account: str = ""
    ) -> dict:
        """Delete transaction order

        Args:
            transaction_id: Transfer order transaction ID
            account: Optional account alias

        Returns:
            Dictionary indicating success or containing error details
        """
        if not transaction_id:
            return {"error": "transaction_id cannot be empty"}
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.delete_transaction(transaction_id = transaction_id)
            if not result.get("success"):
                return result
            return {
                "success": True,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
        




        

        
        
    






    

        




        
            
    


    


    

        
        
   
        
    
        



        



  
    



    


        
