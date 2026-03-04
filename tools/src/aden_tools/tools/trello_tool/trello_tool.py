"""Trello MCP tools."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from fastmcp import FastMCP

from .trello_client import TrelloClient

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Trello tools with the MCP server."""

    limit_min = 1
    limit_max = 1000
    card_desc_max = 16384

    def _get_credentials() -> tuple[str | None, str | None]:
        if credentials is not None:
            api_key = credentials.get("trello_api_key")
            api_token = credentials.get("trello_api_token")
        else:
            api_key = None
            api_token = None

        api_key = api_key or os.getenv("TRELLO_API_KEY")
        api_token = api_token or os.getenv("TRELLO_API_TOKEN")
        return api_key, api_token

    def _get_client() -> TrelloClient | dict[str, str]:
        api_key, api_token = _get_credentials()
        if not api_key or not api_token:
            return {
                "error": "Trello credentials not configured",
                "help": (
                    "Set TRELLO_API_KEY and TRELLO_API_TOKEN environment variables "
                    "or configure via credential store"
                ),
            }
        return TrelloClient(api_key, api_token)

    def _validate_limit(limit: int | None) -> dict[str, str] | None:
        if limit is None:
            return None
        if limit < limit_min or limit > limit_max:
            return {
                "error": f"limit must be between {limit_min} and {limit_max}",
                "field": "limit",
                "help": (
                    "Reduce the limit or paginate by calling again with a smaller "
                    "limit to fetch additional results."
                ),
            }
        return None

    def _validate_card_desc(desc: str | None) -> dict[str, str] | None:
        if desc is None:
            return None
        if len(desc) > card_desc_max:
            return {
                "error": f"desc exceeds the {card_desc_max}-character limit",
                "field": "desc",
                "help": "Trim the description and retry.",
            }
        return None

    @mcp.tool()
    def trello_list_boards(
        member_id: str = "me",
        fields: list[str] | None = None,
        limit: int | None = None,
    ) -> dict:
        """
        List Trello boards for a member.

        Args:
            member_id: Trello member id or "me" (default)
            fields: Optional list of board fields (e.g., ["id", "name", "url",
                "closed"] or ["all"]). Uses Trello board object field names.
            limit: Optional max number of boards (1-1000).
        """
        limit_error = _validate_limit(limit)
        if limit_error:
            return limit_error
        client = _get_client()
        if isinstance(client, dict):
            return client
        result = client.list_boards(member_id=member_id, fields=fields, limit=limit)
        if isinstance(result, list):
            return {"boards": result}
        return result

    @mcp.tool()
    def trello_get_member(
        member_id: str = "me",
        fields: list[str] | None = None,
    ) -> dict:
        """
        Get Trello member info.

        Args:
            member_id: Trello member id, username or "me" (default)
            fields: Optional list of member fields (e.g., ["fullName", "username",
                "url"] or ["all"]). Uses Trello member object field names.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.get_member(member_id=member_id, fields=fields)

    @mcp.tool()
    def trello_list_lists(
        board_id: str,
        fields: list[str] | None = None,
    ) -> dict:
        """
        List lists in a Trello board.

        Args:
            board_id: Trello board id
            fields: Optional list of list fields (e.g., ["id", "name", "closed"] or
                ["all"]). Uses Trello list object field names.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        result = client.list_lists(board_id=board_id, fields=fields)
        if isinstance(result, list):
            return {"lists": result}
        return result

    @mcp.tool()
    def trello_list_cards(
        list_id: str,
        fields: list[str] | None = None,
        limit: int | None = None,
    ) -> dict:
        """
        List cards in a Trello list.

        Args:
            list_id: Trello list id
            fields: Optional list of card fields (e.g., ["name", "desc", "url",
                "idList", "idMembers", "labels", "due"] or ["all"]). Uses
                Trello card object field names.
            limit: Optional max number of cards (1-1000).
        """
        limit_error = _validate_limit(limit)
        if limit_error:
            return limit_error
        client = _get_client()
        if isinstance(client, dict):
            return client
        result = client.list_cards(list_id=list_id, fields=fields, limit=limit)
        if isinstance(result, list):
            return {"cards": result}
        return result

    @mcp.tool()
    def trello_create_card(
        list_id: str,
        name: str,
        desc: str | None = None,
        due: str | None = None,
        id_members: list[str] | None = None,
        id_labels: list[str] | None = None,
        pos: str | None = None,
    ) -> dict:
        """
        Create a Trello card.

        Args:
            list_id: Trello list id to create the card in
            name: Card name
            desc: Optional card description (max 16384 characters)
            due: Optional due date (ISO-8601 string)
            id_members: Optional list of member ids
            id_labels: Optional list of label ids
            pos: Optional position ("top", "bottom", or numeric string)
        """
        if not name:
            return {"error": "Card name is required"}
        desc_error = _validate_card_desc(desc)
        if desc_error:
            return desc_error
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.create_card(
            list_id=list_id,
            name=name,
            desc=desc,
            due=due,
            id_members=id_members,
            id_labels=id_labels,
            pos=pos,
        )

    @mcp.tool()
    def trello_move_card(
        card_id: str,
        list_id: str,
        pos: str | None = None,
    ) -> dict:
        """
        Move a card to another list.

        Args:
            card_id: Trello card id
            list_id: Target Trello list id
            pos: Optional position ("top", "bottom", or numeric string)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.move_card(card_id=card_id, list_id=list_id, pos=pos)

    @mcp.tool()
    def trello_update_card(
        card_id: str,
        name: str | None = None,
        desc: str | None = None,
        due: str | None = None,
        closed: bool | None = None,
        list_id: str | None = None,
        pos: str | None = None,
    ) -> dict:
        """
        Update a Trello card.

        Args:
            card_id: Trello card id
            name: Optional new card name
            desc: Optional new description (max 16384 characters)
            due: Optional due date (ISO-8601 string)
            closed: Optional archive flag
            list_id: Optional new list id
            pos: Optional position ("top", "bottom", or numeric string)
        """
        desc_error = _validate_card_desc(desc)
        if desc_error:
            return desc_error
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.update_card(
            card_id=card_id,
            name=name,
            desc=desc,
            due=due,
            closed=closed,
            list_id=list_id,
            pos=pos,
        )

    @mcp.tool()
    def trello_add_comment(
        card_id: str,
        text: str,
    ) -> dict:
        """
        Add a comment to a Trello card.

        Args:
            card_id: Trello card id
            text: Comment text
        """
        if not text:
            return {"error": "Comment text is required"}
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.add_comment(card_id=card_id, text=text)

    @mcp.tool()
    def trello_add_attachment(
        card_id: str,
        attachment_url: str,
        name: str | None = None,
    ) -> dict:
        """
        Add an attachment to a Trello card (URL attachment).

        Args:
            card_id: Trello card id
            attachment_url: URL to attach
            name: Optional attachment name
        """
        if not attachment_url:
            return {"error": "attachment_url is required"}
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.add_attachment(
            card_id=card_id,
            attachment_url=attachment_url,
            name=name,
        )
