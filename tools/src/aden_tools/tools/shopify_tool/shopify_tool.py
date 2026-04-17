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
    def shopify_update_order(
        order_id: str,
        tags: str = "",
        note: str = "",
    ) -> dict:
        """
        Update an existing Shopify order (tags / note).

        Args:
            order_id: The numeric Shopify order ID (required).
            tags: Comma-separated tags to replace existing tags (optional).
            note: Internal order note (optional).

        Returns:
            Dict with updated order fields.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, store = creds

        if not order_id:
            return {"error": "order_id is required"}

        try:
            order_id_int = int(order_id)
        except ValueError:
            return {"error": "order_id must be a numeric Shopify order ID"}

        order: dict[str, Any] = {"id": order_id_int}
        if tags:
            order["tags"] = tags
        if note:
            order["note"] = note

        if set(order.keys()) == {"id"}:
            return {"error": "At least one field to update is required"}

        try:
            resp = httpx.put(
                f"{_base_url(store)}/orders/{order_id}.json",
                headers=_headers(token),
                json={"order": order},
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            o = result.get("order", {})
            return {
                "id": o.get("id"),
                "name": o.get("name"),
                "updated_at": o.get("updated_at"),
                "tags": o.get("tags"),
                "note": o.get("note"),
                "result": "updated",
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def shopify_cancel_order(
        order_id: str,
        reason: str = "",
        restock: bool = True,
        email: bool = True,
        refund: bool = False,
    ) -> dict:
        """
        Cancel an existing Shopify order.

        Args:
            order_id: The numeric Shopify order ID (required).
            reason: Optional reason (Shopify-defined values include: "customer", "inventory", "fraud", "declined", "other").
            restock: Whether to restock inventory for the cancelled order (default True).
            email: Whether Shopify should email the customer (default True).
            refund: Whether Shopify should attempt to refund the order (default False).

        Returns:
            Dict with cancellation status.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, store = creds

        if not order_id:
            return {"error": "order_id is required"}
        try:
            int(order_id)
        except ValueError:
            return {"error": "order_id must be a numeric Shopify order ID"}

        params: dict[str, Any] = {
            "restock": str(restock).lower(),
            "email": str(email).lower(),
            "refund": str(refund).lower(),
        }
        if reason:
            params["reason"] = reason

        try:
            resp = httpx.post(
                f"{_base_url(store)}/orders/{order_id}/cancel.json",
                headers=_headers(token),
                params=params,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            o = result.get("order", {})
            return {
                "id": o.get("id"),
                "name": o.get("name"),
                "cancelled_at": o.get("cancelled_at"),
                "cancel_reason": o.get("cancel_reason"),
                "financial_status": o.get("financial_status"),
                "fulfillment_status": o.get("fulfillment_status"),
                "result": "cancelled",
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def shopify_refund_order(
        order_id: str,
        amount: str = "",
        note: str = "",
        notify: bool = False,
    ) -> dict:
        """
        Refund an order via the Shopify Admin REST API.

        This uses the store's configured payment gateway by creating a refund transaction
        against an existing "capture"/"sale" transaction for the order.

        Args:
            order_id: The numeric Shopify order ID (required).
            amount: Refund amount as a string (optional). If empty, refunds the order's total_price.
            note: Optional internal note on the refund.
            notify: Whether to notify the customer (default False).

        Returns:
            Dict with refund ID and status.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, store = creds

        if not order_id:
            return {"error": "order_id is required"}
        try:
            int(order_id)
        except ValueError:
            return {"error": "order_id must be a numeric Shopify order ID"}

        try:
            order_resp = httpx.get(
                f"{_base_url(store)}/orders/{order_id}.json",
                headers=_headers(token),
                timeout=30.0,
            )
            order_result = _handle_response(order_resp)
            if "error" in order_result:
                return order_result

            order = order_result.get("order", {})
            refund_amount = amount or str(order.get("total_price") or "")
            currency = order.get("currency") or ""
            if not refund_amount:
                return {"error": "amount is required (could not infer from order total_price)"}
            if not currency:
                return {"error": "Could not infer currency from order"}

            tx_resp = httpx.get(
                f"{_base_url(store)}/orders/{order_id}/transactions.json",
                headers=_headers(token),
                timeout=30.0,
            )
            tx_result = _handle_response(tx_resp)
            if "error" in tx_result:
                return tx_result

            transactions = tx_result.get("transactions", []) or []
            parent = None
            for t in transactions:
                if t.get("kind") in ("capture", "sale"):
                    parent = t
                    break
            if not parent:
                return {"error": "No refundable transaction found for this order"}

            parent_id = parent.get("id")
            gateway = parent.get("gateway")
            if not parent_id or not gateway:
                return {"error": "Refund transaction metadata missing (parent_id/gateway)"}

            payload: dict[str, Any] = {
                "refund": {
                    "currency": currency,
                    "notify": bool(notify),
                    "transactions": [
                        {
                            "parent_id": parent_id,
                            "amount": refund_amount,
                            "kind": "refund",
                            "gateway": gateway,
                        }
                    ],
                }
            }
            if note:
                payload["refund"]["note"] = note

            refund_resp = httpx.post(
                f"{_base_url(store)}/orders/{order_id}/refunds.json",
                headers=_headers(token),
                json=payload,
                timeout=30.0,
            )
            refund_result = _handle_response(refund_resp)
            if "error" in refund_result:
                return refund_result

            r = refund_result.get("refund", {})
            return {
                "id": r.get("id"),
                "order_id": r.get("order_id"),
                "created_at": r.get("created_at"),
                "note": r.get("note"),
                "transactions": r.get("transactions"),
                "result": "refunded",
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

    @mcp.tool()
    def shopify_update_product(
        product_id: str,
        title: str = "",
        body_html: str = "",
        vendor: str = "",
        product_type: str = "",
        tags: str = "",
        status: str = "",
    ) -> dict:
        """
        Update an existing Shopify product.

        Args:
            product_id: The numeric Shopify product ID (required).
            title: New product title (optional).
            body_html: New product description HTML (optional).
            vendor: New vendor name (optional).
            product_type: New product type (optional).
            tags: Comma-separated tags to replace existing tags (optional).
            status: New status - "active", "archived", or "draft" (optional).

        Returns:
            Dict with updated product details.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, store = creds

        if not product_id:
            return {"error": "product_id is required"}

        product: dict[str, Any] = {}
        if title:
            product["title"] = title
        if body_html:
            product["body_html"] = body_html
        if vendor:
            product["vendor"] = vendor
        if product_type:
            product["product_type"] = product_type
        if tags:
            product["tags"] = tags
        if status:
            product["status"] = status

        if not product:
            return {"error": "At least one field to update is required"}

        try:
            resp = httpx.put(
                f"{_base_url(store)}/products/{product_id}.json",
                headers=_headers(token),
                json={"product": product},
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            p = result.get("product", {})
            return {
                "id": p.get("id"),
                "title": p.get("title"),
                "vendor": p.get("vendor"),
                "product_type": p.get("product_type"),
                "status": p.get("status"),
                "tags": p.get("tags"),
                "updated_at": p.get("updated_at"),
                "result": "updated",
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def shopify_get_customer(customer_id: str) -> dict:
        """
        Get a single Shopify customer by ID.

        Args:
            customer_id: The numeric Shopify customer ID.

        Returns:
            Dict with full customer details including addresses and order stats.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, store = creds

        if not customer_id:
            return {"error": "customer_id is required"}

        try:
            resp = httpx.get(
                f"{_base_url(store)}/customers/{customer_id}.json",
                headers=_headers(token),
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            c = result.get("customer", {})
            addresses = []
            for a in c.get("addresses", []):
                addresses.append(
                    {
                        "id": a.get("id"),
                        "address1": a.get("address1"),
                        "city": a.get("city"),
                        "province": a.get("province"),
                        "country": a.get("country"),
                        "zip": a.get("zip"),
                        "default": a.get("default", False),
                    }
                )

            return {
                "id": c.get("id"),
                "first_name": c.get("first_name"),
                "last_name": c.get("last_name"),
                "email": c.get("email"),
                "phone": c.get("phone"),
                "orders_count": c.get("orders_count"),
                "total_spent": c.get("total_spent"),
                "state": c.get("state"),
                "tags": c.get("tags"),
                "note": c.get("note"),
                "verified_email": c.get("verified_email"),
                "tax_exempt": c.get("tax_exempt"),
                "created_at": c.get("created_at"),
                "updated_at": c.get("updated_at"),
                "addresses": addresses,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def shopify_create_draft_order(
        line_items_json: str,
        customer_id: str = "",
        note: str = "",
        tags: str = "",
    ) -> dict:
        """
        Create a draft order in Shopify.

        Args:
            line_items_json: JSON array of line items. Each item needs either
                "variant_id" and "quantity", or "title", "price", and "quantity".
                Example: '[{"variant_id": 123, "quantity": 2}]'
            customer_id: Existing customer ID to associate (optional).
            note: Order note (optional).
            tags: Comma-separated tags (optional).

        Returns:
            Dict with created draft order details including invoice URL.
        """
        import json as json_mod

        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, store = creds

        if not line_items_json:
            return {"error": "line_items_json is required"}

        try:
            line_items = json_mod.loads(line_items_json)
        except json_mod.JSONDecodeError:
            return {"error": "line_items_json must be valid JSON"}

        if not isinstance(line_items, list) or not line_items:
            return {"error": "line_items_json must be a non-empty JSON array"}

        draft_order: dict[str, Any] = {"line_items": line_items}
        if customer_id:
            draft_order["customer"] = {"id": int(customer_id)}
        if note:
            draft_order["note"] = note
        if tags:
            draft_order["tags"] = tags

        try:
            resp = httpx.post(
                f"{_base_url(store)}/draft_orders.json",
                headers=_headers(token),
                json={"draft_order": draft_order},
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            d = result.get("draft_order", {})
            return {
                "id": d.get("id"),
                "name": d.get("name"),
                "status": d.get("status"),
                "total_price": d.get("total_price"),
                "subtotal_price": d.get("subtotal_price"),
                "total_tax": d.get("total_tax"),
                "currency": d.get("currency"),
                "invoice_url": d.get("invoice_url"),
                "created_at": d.get("created_at"),
                "line_item_count": len(d.get("line_items", [])),
                "result": "created",
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def shopify_send_draft_order_invoice(
        draft_order_id: str,
        to: str = "",
        subject: str = "",
        custom_message: str = "",
        bcc: str = "",
        from_email: str = "",
    ) -> dict:
        """
        Send a Shopify draft order invoice email to collect payment.

        Args:
            draft_order_id: The numeric Shopify draft order ID (required).
            to: Recipient email override (optional). Defaults to Shopify's customer email on the draft order.
            subject: Email subject override (optional).
            custom_message: Custom message to include in the invoice email (optional).
            bcc: BCC email address (optional).
            from_email: From email override (optional). Must be configured/allowed in Shopify.

        Returns:
            Dict with result status.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        token, store = creds

        if not draft_order_id:
            return {"error": "draft_order_id is required"}
        try:
            int(draft_order_id)
        except ValueError:
            return {"error": "draft_order_id must be a numeric Shopify draft order ID"}

        invoice: dict[str, Any] = {}
        if to:
            invoice["to"] = to
        if subject:
            invoice["subject"] = subject
        if custom_message:
            invoice["custom_message"] = custom_message
        if bcc:
            invoice["bcc"] = bcc
        if from_email:
            invoice["from"] = from_email

        try:
            resp = httpx.post(
                f"{_base_url(store)}/draft_orders/{draft_order_id}/send_invoice.json",
                headers=_headers(token),
                json={"draft_order_invoice": invoice},
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result
            return {"draft_order_id": int(draft_order_id), "result": "invoice_sent"}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
