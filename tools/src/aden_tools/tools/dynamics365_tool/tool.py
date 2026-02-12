"""Microsoft Dynamics 365 tools for managing CRM and ERP entities."""

from typing import Any, TYPE_CHECKING

from fastmcp import FastMCP

from .client import Dynamics365Client

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialManager


def register_tools(
    mcp: FastMCP,
    credentials: "CredentialManager | None" = None,
) -> None:
    """Register Dynamics 365 tools with the MCP server."""

    def get_client() -> Dynamics365Client:
        """Helper to get a configured Dynamics 365 client."""
        if credentials:
            cred_string = credentials.get("dynamics365")
        else:
            import os
            cred_string = os.getenv("DYNAMICS365_CREDENTIALS")
            
        if not cred_string:
            raise ValueError(
                "Missing DYNAMICS365_CREDENTIALS. "
                "Format: tenant_id:client_id:client_secret:environment"
            )
        return Dynamics365Client(cred_string)

    @mcp.tool()
    async def dynamics365_search_accounts(filter: str = "") -> dict[str, Any]:
        """
        Search for accounts in Dynamics 365.

        Args:
            filter: OData filter string (e.g., "name eq 'Microsoft'").
                   If empty, returns the first 10 accounts.
        """
        client = get_client()
        params = {"$top": 10}
        if filter:
            params["$filter"] = filter
        return await client.request("GET", "accounts", params=params)

    @mcp.tool()
    async def dynamics365_get_account(account_id: str) -> dict[str, Any]:
        """
        Get a specific account by its GUID.

        Args:
            account_id: The GUID of the account.
        """
        client = get_client()
        return await client.request("GET", f"accounts({account_id})")

    @mcp.tool()
    async def dynamics365_create_account(data: dict[str, Any]) -> dict[str, Any]:
        """
        Create a new account in Dynamics 365.

        Args:
            data: Dictionary of account fields (e.g., {"name": "New Corp"}).
        """
        client = get_client()
        return await client.request("POST", "accounts", json=data)

    @mcp.tool()
    async def dynamics365_update_account(account_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        Update an existing account.

        Args:
            account_id: The GUID of the account to update.
            data: Dictionary of fields to update.
        """
        client = get_client()
        return await client.request("PATCH", f"accounts({account_id})", json=data)

    @mcp.tool()
    async def dynamics365_delete_account(account_id: str) -> str:
        """
        Delete an account from Dynamics 365.

        Args:
            account_id: The GUID of the account to delete.
        """
        client = get_client()
        await client.request("DELETE", f"accounts({account_id})")
        return f"Account {account_id} deleted successfully."

    @mcp.tool()
    async def dynamics365_search_contacts(filter: str = "") -> dict[str, Any]:
        """
        Search for contacts in Dynamics 365.

        Args:
            filter: OData filter string (e.g., "lastname eq 'Smith'").
        """
        client = get_client()
        params = {"$top": 10}
        if filter:
            params["$filter"] = filter
        return await client.request("GET", "contacts", params=params)

    @mcp.tool()
    async def dynamics365_create_contact(data: dict[str, Any]) -> dict[str, Any]:
        """
        Create a new contact in Dynamics 365.

        Args:
            data: Dictionary of contact fields (e.g., {"firstname": "John", "lastname": "Doe"}).
        """
        client = get_client()
        return await client.request("POST", "contacts", json=data)

    @mcp.tool()
    async def dynamics365_search_opportunities(filter: str = "") -> dict[str, Any]:
        """
        Search for opportunities in Dynamics 365.

        Args:
            filter: OData filter string.
        """
        client = get_client()
        params = {"$top": 10}
        if filter:
            params["$filter"] = filter
        return await client.request("GET", "opportunities", params=params)

    @mcp.tool()
    async def dynamics365_create_opportunity(data: dict[str, Any]) -> dict[str, Any]:
        """
        Create a new opportunity in Dynamics 365.

        Args:
            data: Dictionary of opportunity fields.
        """
        client = get_client()
        return await client.request("POST", "opportunities", json=data)

    @mcp.tool()
    async def dynamics365_check_inventory(product_id: str) -> dict[str, Any]:
        """
        Check inventory/details for a specific product.

        Args:
            product_id: The GUID of the product.
        """
        client = get_client()
        # Assuming 'products' entity for basic details
        return await client.request("GET", f"products({product_id})")

    @mcp.tool()
    async def dynamics365_search_invoices(filter: str = "") -> dict[str, Any]:
        """
        Search for invoices in Dynamics 365.

        Args:
            filter: OData filter string.
        """
        client = get_client()
        params = {"$top": 10}
        if filter:
            params["$filter"] = filter
        return await client.request("GET", "invoices", params=params)
