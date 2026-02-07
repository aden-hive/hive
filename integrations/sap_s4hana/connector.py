"""
SAP S/4HANA Integration Connector

Read-only integration for procurement data from SAP S/4HANA.
Uses OData APIs for secure, standardized access.
"""

import os
from typing import Any, Optional
from dataclasses import dataclass

import requests
from requests.auth import HTTPBasicAuth


@dataclass
class SAPConnectionConfig:
    """Configuration for SAP S/4HANA connection."""
    base_url: str  # e.g., "https://sap-server:port/sap/opu/odata/sap"
    username: str
    password: str
    client: str = "100"  # SAP client number
    verify_ssl: bool = True


class SAPS4HANAConnector:
    """
    Connector for SAP S/4HANA read-only operations.
    
    Supports:
    - Purchase Order queries
    - Vendor/Supplier lookups
    - Procurement document retrieval
    """
    
    def __init__(self, config: SAPConnectionConfig):
        self.config = config
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(config.username, config.password)
        self.session.headers.update({
            "Content-Type": "application/json",
            "x-csrf-token": "fetch"  # Required for OData
        })
    
    def fetch_purchase_orders(
        self,
        filters: Optional[dict] = None,
        top: int = 100,
        skip: int = 0
    ) -> list[dict]:
        """
        Fetch purchase orders from SAP S/4HANA.
        
        Args:
            filters: Optional filters (e.g., {"Supplier": "12345"})
            top: Max records to return (default 100)
            skip: Records to skip for pagination
            
        Returns:
            List of purchase order dictionaries
        """
        endpoint = f"{self.config.base_url}/API_PURCHASEORDER_SRV/A_PurchaseOrder"
        
        params = {
            "$top": top,
            "$skip": skip,
            "$format": "json"
        }
        
        # Build OData filter
        if filters:
            filter_str = " and ".join([f"{k} eq '{v}'" for k, v in filters.items()])
            params["$filter"] = filter_str
        
        try:
            response = self.session.get(endpoint, params=params, verify=self.config.verify_ssl)
            response.raise_for_status()
            
            data = response.json()
            return data.get("d", {}).get("results", [])
            
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to fetch purchase orders: {e}")
    
    def fetch_vendors(
        self,
        filters: Optional[dict] = None,
        top: int = 100
    ) -> list[dict]:
        """
        Fetch vendor/supplier master data.
        
        Args:
            filters: Optional filters (e.g., {"Vendor": "V001"})
            top: Max records to return
            
        Returns:
            List of vendor dictionaries
        """
        endpoint = f"{self.config.base_url}/API_BUSINESS_PARTNER/A_BusinessPartner"
        
        params = {
            "$top": top,
            "$format": "json",
            "$filter": "BusinessPartnerType eq '2'"  # Type 2 = Vendor
        }
        
        if filters:
            additional = " and ".join([f"{k} eq '{v}'" for k, v in filters.items()])
            params["$filter"] += f" and {additional}"
        
        try:
            response = self.session.get(endpoint, params=params, verify=self.config.verify_ssl)
            response.raise_for_status()
            
            data = response.json()
            return data.get("d", {}).get("results", [])
            
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to fetch vendors: {e}")
    
    def get_purchase_order_by_id(self, po_id: str) -> dict:
        """
        Get specific purchase order by ID.
        
        Args:
            po_id: Purchase order number
            
        Returns:
            Purchase order details
        """
        endpoint = f"{self.config.base_url}/API_PURCHASEORDER_SRV/A_PurchaseOrder('{po_id}')"
        
        try:
            response = self.session.get(endpoint, params={"$format": "json"}, verify=self.config.verify_ssl)
            response.raise_for_status()
            
            return response.json().get("d", {})
            
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to fetch PO {po_id}: {e}")
    
    def health_check(self) -> bool:
        """Verify connection to SAP S/4HANA."""
        try:
            # Try to fetch metadata
            endpoint = f"{self.config.base_url}/API_PURCHASEORDER_SRV/$metadata"
            response = self.session.get(endpoint, verify=self.config.verify_ssl, timeout=10)
            return response.status_code == 200
        except Exception:
            return False


# Factory function for Hive integration
def create_sap_connector_from_env() -> SAPS4HANAConnector:
    """Create connector from environment variables."""
    config = SAPConnectionConfig(
        base_url=os.environ.get("SAP_BASE_URL", ""),
        username=os.environ.get("SAP_USERNAME", ""),
        password=os.environ.get("SAP_PASSWORD", ""),
        client=os.environ.get("SAP_CLIENT", "100"),
        verify_ssl=os.environ.get("SAP_VERIFY_SSL", "true").lower() == "true"
    )
    return SAPS4HANAConnector(config)