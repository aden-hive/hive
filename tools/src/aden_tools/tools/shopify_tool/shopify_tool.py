"""
Shopify Admin REST API Tool - Orders, products, and customers.

Supports:
- Custom app access tokens (SHOPIFY_ACCESS_TOKEN)
- Store name (SHOPIFY_STORE_NAME)

API Reference: https://shopify.dev/docs/api/admin-rest
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

API_VERSION = "2025-01"


def _get_creds(
    credentials: CredentialStoreAdapter | None,
) -> tuple[str, str] | dict[str, str]:
    """Return (access_token, store_name) or an error dict."""
    if credentials is not None:
        token = credentials.get("shopify")
        store = credentials.get("shopify_store_name")
    else:
        token = os.getenv("SHOPIFY_ACCESS_TOKEN")
        store = os.getenv("SHOPIFY_STORE_NAME")

    if not token or not store:
        return {
            "error": "Shopify credentials not configured",
            "help": (
                "Set SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_NAME "
                "environment variables or configure via credential store"
            ),
        }
    return token, store


def _base_url(store: str) -> str:
    return f"https://{store}.myshopify.com/admin/api/{API_VERSION}"


def _headers(token: str) -> dict[str, str]:
    return {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _handle_response(resp: httpx.Response) -> dict[str, Any]:
    if resp.status_code == 401:
        return {"error": "Invalid Shopify access token"}
    if resp.status_code == 402:
        return {"error": "Shopify store is frozen or payment required"}
    if resp.status_code == 403:
        return {"error": "Insufficient API scopes for this Shopify resource"}
    if resp.status_code == 404:
        return {"error": "Shopify resource not found"}
    if resp.status_code == 429:
        return {"error": "Shopify rate limit exceeded. Try again later."}
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("errors", resp.text)
        except Exception:
            detail = resp.text
        return {"error": f"Shopify API error (HTTP {resp.status_code}): {detail}"}
    return resp.json()


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Shopify Admin tools with the MCP server."""

    @mcp.tool()
    def shopify_list_orders(
        status: str = "any",
        financial_status: str = "",
        fulfillment_status: str = "",
        limit: int = 50,
    ) -> dict:
        """
        List orders from a Shopify store.

        Args:
            status: Filter by order status - "open", "closed", "cancelled", or "any".
            financial_status: Filter by financial status (e.g. "paid", "pending", "refunded").
            fulfillment_status: Filter by fulfillment status (e.g. "shipped", "unshipped").
            limit: Max orders to return (1-250, default 50).

        Returns:
            Dict with count and list of orders.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, store = creds

        try:
            params: dict[str, Any] = {
                "status": status,
                "limit": min(limit, 250),
            }
            if financial_status:
                params["financial_status"] = financial_status
            if fulfillment_status:
                params["fulfillment_status"] = fulfillment_status

            resp = httpx.get(
                f"{_base_url(store)}/orders.json",
                headers=_headers(token),
                params=params,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            orders = []
            for o in result.get("orders", []):
                orders.append(
                    {
                        "id": o.get("id"),
                        "name": o.get("name"),
                        "email": o.get("email"),
                        "created_at": o.get("created_at"),
                        "financial_status": o.get("financial_status"),
                        "fulfillment_status": o.get("fulfillment_status"),
                        "total_price": o.get("total_price"),
                        "currency": o.get("currency"),
                        "line_item_count": len(o.get("line_items", [])),
                    }
                )
            return {"count": len(orders), "orders": orders}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def shopify_get_order(order_id: str) -> dict:
        """
        Get a single Shopify order by ID.

        Args:
            order_id: The numeric Shopify order ID.

        Returns:
            Dict with full order details including line items and addresses.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, store = creds

        if not order_id:
            return {"error": "order_id is required"}

        try:
            resp = httpx.get(
                f"{_base_url(store)}/orders/{order_id}.json",
                headers=_headers(token),
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            o = result.get("order", {})
            line_items = []
            for li in o.get("line_items", []):
                line_items.append(
                    {
                        "title": li.get("title"),
                        "quantity": li.get("quantity"),
                        "price": li.get("price"),
                        "sku": li.get("sku"),
                        "variant_id": li.get("variant_id"),
                        "product_id": li.get("product_id"),
                    }
                )

            return {
                "id": o.get("id"),
                "name": o.get("name"),
                "email": o.get("email"),
                "created_at": o.get("created_at"),
                "updated_at": o.get("updated_at"),
                "financial_status": o.get("financial_status"),
                "fulfillment_status": o.get("fulfillment_status"),
                "total_price": o.get("total_price"),
                "subtotal_price": o.get("subtotal_price"),
                "total_tax": o.get("total_tax"),
                "currency": o.get("currency"),
                "line_items": line_items,
                "shipping_address": o.get("shipping_address"),
                "billing_address": o.get("billing_address"),
                "customer": {
                    "id": (o.get("customer") or {}).get("id"),
                    "email": (o.get("customer") or {}).get("email"),
                    "first_name": (o.get("customer") or {}).get("first_name"),
                    "last_name": (o.get("customer") or {}).get("last_name"),
                },
                "note": o.get("note"),
                "tags": o.get("tags"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def shopify_list_products(
        status: str = "",
        product_type: str = "",
        vendor: str = "",
        limit: int = 50,
    ) -> dict:
        """
        List products from a Shopify store.

        Args:
            status: Filter by status - "active", "archived", or "draft".
            product_type: Filter by product type.
            vendor: Filter by vendor name.
            limit: Max products to return (1-250, default 50).

        Returns:
            Dict with count and list of products.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, store = creds

        try:
            params: dict[str, Any] = {"limit": min(limit, 250)}
            if status:
                params["status"] = status
            if product_type:
                params["product_type"] = product_type
            if vendor:
                params["vendor"] = vendor

            resp = httpx.get(
                f"{_base_url(store)}/products.json",
                headers=_headers(token),
                params=params,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            products = []
            for p in result.get("products", []):
                variants = p.get("variants", [])
                products.append(
                    {
                        "id": p.get("id"),
                        "title": p.get("title"),
                        "vendor": p.get("vendor"),
                        "product_type": p.get("product_type"),
                        "status": p.get("status"),
                        "handle": p.get("handle"),
                        "created_at": p.get("created_at"),
                        "variant_count": len(variants),
                        "tags": p.get("tags"),
                    }
                )
            return {"count": len(products), "products": products}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def shopify_get_product(product_id: str) -> dict:
        """
        Get a single Shopify product by ID.

        Args:
            product_id: The numeric Shopify product ID.

        Returns:
            Dict with full product details including variants and images.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, store = creds

        if not product_id:
            return {"error": "product_id is required"}

        try:
            resp = httpx.get(
                f"{_base_url(store)}/products/{product_id}.json",
                headers=_headers(token),
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            p = result.get("product", {})
            variants = []
            for v in p.get("variants", []):
                variants.append(
                    {
                        "id": v.get("id"),
                        "title": v.get("title"),
                        "price": v.get("price"),
                        "sku": v.get("sku"),
                        "inventory_quantity": v.get("inventory_quantity"),
                        "option1": v.get("option1"),
                        "option2": v.get("option2"),
                        "option3": v.get("option3"),
                    }
                )

            images = [
                {"id": img.get("id"), "src": img.get("src"), "position": img.get("position")}
                for img in p.get("images", [])
            ]

            return {
                "id": p.get("id"),
                "title": p.get("title"),
                "body_html": p.get("body_html"),
                "vendor": p.get("vendor"),
                "product_type": p.get("product_type"),
                "handle": p.get("handle"),
                "status": p.get("status"),
                "created_at": p.get("created_at"),
                "updated_at": p.get("updated_at"),
                "tags": p.get("tags"),
                "variants": variants,
                "options": p.get("options", []),
                "images": images,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def shopify_list_customers(
        limit: int = 50,
    ) -> dict:
        """
        List customers from a Shopify store.

        Args:
            limit: Max customers to return (1-250, default 50).

        Returns:
            Dict with count and list of customers.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, store = creds

        try:
            resp = httpx.get(
                f"{_base_url(store)}/customers.json",
                headers=_headers(token),
                params={"limit": min(limit, 250)},
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            customers = []
            for c in result.get("customers", []):
                customers.append(
                    {
                        "id": c.get("id"),
                        "first_name": c.get("first_name"),
                        "last_name": c.get("last_name"),
                        "email": c.get("email"),
                        "phone": c.get("phone"),
                        "orders_count": c.get("orders_count"),
                        "total_spent": c.get("total_spent"),
                        "state": c.get("state"),
                        "tags": c.get("tags"),
                        "created_at": c.get("created_at"),
                    }
                )
            return {"count": len(customers), "customers": customers}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def shopify_search_customers(
        query: str,
        limit: int = 50,
    ) -> dict:
        """
        Search Shopify customers by email, name, or other fields.

        Args:
            query: Search query (e.g. "email:bob@example.com" or "first_name:Bob").
            limit: Max customers to return (1-250, default 50).

        Returns:
            Dict with count and list of matching customers.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, store = creds

        if not query:
            return {"error": "query is required"}

        try:
            resp = httpx.get(
                f"{_base_url(store)}/customers/search.json",
                headers=_headers(token),
                params={"query": query, "limit": min(limit, 250)},
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            customers = []
            for c in result.get("customers", []):
                customers.append(
                    {
                        "id": c.get("id"),
                        "first_name": c.get("first_name"),
                        "last_name": c.get("last_name"),
                        "email": c.get("email"),
                        "phone": c.get("phone"),
                        "orders_count": c.get("orders_count"),
                        "total_spent": c.get("total_spent"),
                        "state": c.get("state"),
                        "tags": c.get("tags"),
                    }
                )
            return {"count": len(customers), "customers": customers}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
