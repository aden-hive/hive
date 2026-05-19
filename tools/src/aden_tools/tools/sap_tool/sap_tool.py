"""SAP S/4HANA Cloud API integration (read-only).

Provides read-only access to procurement and business data via OData V2.
Requires SAP_BASE_URL, SAP_USERNAME, and SAP_PASSWORD.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx
from fastmcp import FastMCP


def _get_config() -> tuple[str, dict] | dict:
    """Return (base_url, headers) or error dict."""
    base_url = os.getenv("SAP_BASE_URL", "").rstrip("/")
    username = os.getenv("SAP_USERNAME", "")
    password = os.getenv("SAP_PASSWORD", "")
    if not base_url or not username or not password:
        return {
            "error": "SAP_BASE_URL, SAP_USERNAME, and SAP_PASSWORD are required",
            "help": "Set SAP_BASE_URL, SAP_USERNAME, and SAP_PASSWORD environment variables",
        }
    creds = base64.b64encode(f"{username}:{password}".encode()).decode()
    headers = {"Authorization": f"Basic {creds}", "Accept": "application/json"}
    return base_url, headers


def _get(url: str, headers: dict, params: dict | None = None) -> dict:
    """Send a GET request."""
    resp = httpx.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _odata_list(data: dict) -> tuple[list, int | None]:
    """Extract results and count from OData V2 response."""
    d = data.get("d", {})
    results = d.get("results", [])
    count = int(d["__count"]) if "__count" in d else None
    return results, count


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register SAP S/4HANA tools."""

    @mcp.tool()
    def sap_list_purchase_orders(
        top: int = 50,
        skip: int = 0,
        filter_expr: str = "",
    ) -> dict:
        """List SAP S/4HANA purchase orders.

        Args:
            top: Max results to return (default 50).
            skip: Number of results to skip for pagination.
            filter_expr: OData $filter expression (e.g. "CompanyCode eq '1010'").
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg

        params: dict[str, Any] = {
            "$top": top,
            "$skip": skip,
            "$inlinecount": "allpages",
            "$format": "json",
        }
        if filter_expr:
            params["$filter"] = filter_expr

        data = _get(
            f"{base_url}/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder",
            headers,
            params,
        )
        if "error" in data:
            return data

        results, total = _odata_list(data)
        return {
            "count": len(results),
            "total": total,
            "purchase_orders": [
                {
                    "purchase_order": r.get("PurchaseOrder"),
                    "type": r.get("PurchaseOrderType"),
                    "company_code": r.get("CompanyCode"),
                    "supplier": r.get("Supplier"),
                    "creation_date": r.get("CreationDate"),
                    "net_amount": r.get("PurchaseOrderNetAmount"),
                    "currency": r.get("DocumentCurrency"),
                }
                for r in results
            ],
        }

    @mcp.tool()
    def sap_get_purchase_order(purchase_order: str) -> dict:
        """Get details of a specific SAP purchase order.

        Args:
            purchase_order: Purchase order number (e.g. '4500000001').
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg
        if not purchase_order:
            return {"error": "purchase_order is required"}

        data = _get(
            f"{base_url}/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder('{purchase_order}')",
            headers,
            {"$format": "json"},
        )
        if "error" in data:
            return data

        r = data.get("d", {})
        return {
            "purchase_order": r.get("PurchaseOrder"),
            "type": r.get("PurchaseOrderType"),
            "company_code": r.get("CompanyCode"),
            "supplier": r.get("Supplier"),
            "purchasing_org": r.get("PurchasingOrganization"),
            "creation_date": r.get("CreationDate"),
            "net_amount": r.get("PurchaseOrderNetAmount"),
            "currency": r.get("DocumentCurrency"),
        }

    @mcp.tool()
    def sap_list_business_partners(
        top: int = 50,
        skip: int = 0,
        filter_expr: str = "",
    ) -> dict:
        """List SAP S/4HANA business partners.

        Args:
            top: Max results to return (default 50).
            skip: Number of results to skip for pagination.
            filter_expr: OData $filter expression (e.g. "BusinessPartnerCategory eq '1'").
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg

        params: dict[str, Any] = {
            "$top": top,
            "$skip": skip,
            "$inlinecount": "allpages",
            "$format": "json",
        }
        if filter_expr:
            params["$filter"] = filter_expr

        data = _get(
            f"{base_url}/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner",
            headers,
            params,
        )
        if "error" in data:
            return data

        results, total = _odata_list(data)
        return {
            "count": len(results),
            "total": total,
            "business_partners": [
                {
                    "business_partner": r.get("BusinessPartner"),
                    "category": r.get("BusinessPartnerCategory"),
                    "name": r.get("BusinessPartnerFullName") or r.get("BusinessPartnerName"),
                    "is_customer": r.get("Customer", "") != "",
                    "is_supplier": r.get("Supplier", "") != "",
                    "creation_date": r.get("CreationDate"),
                }
                for r in results
            ],
        }

    @mcp.tool()
    def sap_list_products(
        top: int = 50,
        skip: int = 0,
        filter_expr: str = "",
    ) -> dict:
        """List SAP S/4HANA products/materials.

        Args:
            top: Max results to return (default 50).
            skip: Number of results to skip for pagination.
            filter_expr: OData $filter expression (e.g. "ProductType eq 'FERT'").
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg

        params: dict[str, Any] = {
            "$top": top,
            "$skip": skip,
            "$inlinecount": "allpages",
            "$format": "json",
        }
        if filter_expr:
            params["$filter"] = filter_expr

        data = _get(
            f"{base_url}/sap/opu/odata/sap/API_PRODUCT_SRV/A_Product",
            headers,
            params,
        )
        if "error" in data:
            return data

        results, total = _odata_list(data)
        return {
            "count": len(results),
            "total": total,
            "products": [
                {
                    "product": r.get("Product"),
                    "product_type": r.get("ProductType"),
                    "base_unit": r.get("BaseUnit"),
                    "product_group": r.get("ProductGroup"),
                    "creation_date": r.get("CreationDate"),
                }
                for r in results
            ],
        }

    @mcp.tool()
    def sap_list_sales_orders(
        top: int = 50,
        skip: int = 0,
        filter_expr: str = "",
    ) -> dict:
        """List SAP S/4HANA sales orders.

        Args:
            top: Max results to return (default 50).
            skip: Number of results to skip for pagination.
            filter_expr: OData $filter expression (e.g. "SalesOrganization eq '1010'").
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, headers = cfg

        params: dict[str, Any] = {
            "$top": top,
            "$skip": skip,
            "$inlinecount": "allpages",
            "$format": "json",
        }
        if filter_expr:
            params["$filter"] = filter_expr

        data = _get(
            f"{base_url}/sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrder",
            headers,
            params,
        )
        if "error" in data:
            return data

        results, total = _odata_list(data)
        return {
            "count": len(results),
            "total": total,
            "sales_orders": [
                {
                    "sales_order": r.get("SalesOrder"),
                    "sales_order_type": r.get("SalesOrderType"),
                    "sales_organization": r.get("SalesOrganization"),
                    "sold_to_party": r.get("SoldToParty"),
                    "creation_date": r.get("CreationDate"),
                    "net_amount": r.get("TotalNetAmount"),
                    "currency": r.get("TransactionCurrency"),
                }
                for r in results
            ],
        }
