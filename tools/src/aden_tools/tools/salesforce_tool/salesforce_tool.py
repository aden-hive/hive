from typing import Any
import httpx
import os
from mcp.server.fastmcp import FastMCP
from ...credentials.store_adapter import CredentialStoreAdapter

class _SalesforceClient:
    def __init__(self, access_token: str, instance_url: str):
        self._token = access_token
        self._instance_url = instance_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
            if response.status_code == 204:
                return {"status": "success"}
            return response.json()
        except httpx.HTTPStatusError as e:
            try:
                error_detail = response.json()
            except Exception:
                error_detail = response.text
            return {"error": str(e), "detail": error_detail}

    def search_objects(self, query: str) -> dict[str, Any]:
        """Execute a SOQL query."""
        url = f"{self._instance_url}/services/data/v60.0/query"
        response = httpx.get(url, headers=self._headers, params={"q": query})
        return self._handle_response(response)

    def get_object(self, object_type: str, object_id: str) -> dict[str, Any]:
        """Retrieve a specific object by ID."""
        url = f"{self._instance_url}/services/data/v60.0/sobjects/{object_type}/{object_id}"
        response = httpx.get(url, headers=self._headers)
        return self._handle_response(response)

    def create_object(self, object_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new object."""
        url = f"{self._instance_url}/services/data/v60.0/sobjects/{object_type}"
        response = httpx.post(url, headers=self._headers, json=data)
        return self._handle_response(response)

    def update_object(self, object_type: str, object_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing object."""
        url = f"{self._instance_url}/services/data/v60.0/sobjects/{object_type}/{object_id}"
        response = httpx.patch(url, headers=self._headers, json=data)
        return self._handle_response(response)

def register_tools(mcp: FastMCP, credentials: CredentialStoreAdapter | None = None) -> None:
    def get_client() -> _SalesforceClient:
        token = os.getenv("SALESFORCE_ACCESS_TOKEN")
        instance_url = os.getenv("SALESFORCE_INSTANCE_URL")
        
        if credentials:
            creds = credentials.get_credentials("salesforce")
            if creds:
                token = creds.get("access_token") or token
                instance_url = creds.get("instance_url") or instance_url

        if not token or not instance_url:
            raise ValueError("Salesforce access token and instance URL are required.")
        
        return _SalesforceClient(token, instance_url)

    @mcp.tool()
    def salesforce_search_objects(query: str) -> dict[str, Any]:
        """
        Execute a SOQL (Salesforce Object Query Language) query.
        Example: SELECT Name, Id FROM Contact WHERE Email = 'test@example.com'
        """
        return get_client().search_objects(query)

    @mcp.tool()
    def salesforce_get_object(object_type: str, object_id: str) -> dict[str, Any]:
        """
        Retrieve a specific Salesforce record by its type and ID.
        Examples of object_type: 'Lead', 'Account', 'Contact', 'Opportunity'
        """
        return get_client().get_object(object_type, object_id)

    @mcp.tool()
    def salesforce_create_object(object_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        Create a new record in Salesforce.
        Example: object_type='Lead', data={'LastName': 'Smith', 'Company': 'Acme Corp'}
        """
        return get_client().create_object(object_type, data)

    @mcp.tool()
    def salesforce_update_object(object_type: str, object_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        Update an existing Salesforce record.
        """
        return get_client().update_object(object_type, object_id, data)
