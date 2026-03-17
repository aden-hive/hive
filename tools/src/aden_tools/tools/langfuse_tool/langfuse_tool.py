"""
Langfuse LLM Observability Tool - Traces, scores, and prompt management.

Supports:
- HTTP Basic Auth with public/secret key pair
- Cloud (EU/US) and self-hosted instances

API Reference: https://api.reference.langfuse.com/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

DEFAULT_HOST = "https://cloud.langfuse.com"


def _get_creds(
    credentials: CredentialStoreAdapter | None,
) -> tuple[str, str, str] | dict[str, str]:
    """Return (public_key, secret_key, host) or an error dict."""
    if credentials is not None:
        public_key = credentials.get("langfuse_public_key")
        secret_key = credentials.get("langfuse_secret_key")
        host = credentials.get("langfuse_host") or DEFAULT_HOST
    else:
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        host = os.getenv("LANGFUSE_HOST", DEFAULT_HOST)

    if not public_key or not secret_key:
        return {
            "error": "Langfuse credentials not configured",
            "help": (
                "Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY environment "
                "variables or configure via credential store"
            ),
        }
    host = host.rstrip("/")
    return public_key, secret_key, host


def _auth(public_key: str, secret_key: str) -> httpx.BasicAuth:
    return httpx.BasicAuth(username=public_key, password=secret_key)


def _handle_response(resp: httpx.Response) -> dict[str, Any]:
    if resp.status_code == 401:
        return {"error": "Invalid Langfuse API keys"}
    if resp.status_code == 403:
        return {"error": "Insufficient permissions for this Langfuse resource"}
    if resp.status_code == 404:
        return {"error": "Langfuse resource not found"}
    if resp.status_code == 429:
        return {"error": "Langfuse rate limit exceeded. Try again later."}
    if resp.status_code >= 400:
        try:
            body = resp.json()
            detail = body.get("message", body.get("error", resp.text))
        except Exception:
            detail = resp.text
        return {"error": f"Langfuse API error (HTTP {resp.status_code}): {detail}"}
    return resp.json()


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Langfuse observability tools with the MCP server."""

    @mcp.tool()
    def langfuse_list_traces(
        name: str = "",
        user_id: str = "",
        session_id: str = "",
        tags: str = "",
        page: int = 1,
        limit: int = 50,
    ) -> dict:
        """
        List traces from Langfuse with optional filters.

        Args:
            name: Filter by trace name.
            user_id: Filter by user ID.
            session_id: Filter by session ID.
            tags: Comma-separated tags to filter by (all must match).
            page: Page number (starts at 1).
            limit: Items per page (default 50).

        Returns:
            Dict with traces list and pagination metadata.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        public_key, secret_key, host = creds

        try:
            params: dict[str, Any] = {"page": page, "limit": limit}
            if name:
                params["name"] = name
            if user_id:
                params["userId"] = user_id
            if session_id:
                params["sessionId"] = session_id
            if tags:
                for tag in tags.split(","):
                    tag = tag.strip()
                    if tag:
                        params.setdefault("tags", []).append(tag)

            resp = httpx.get(
                f"{host}/api/public/traces",
                auth=_auth(public_key, secret_key),
                params=params,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            traces = []
            for t in result.get("data", []):
                traces.append(
                    {
                        "id": t.get("id"),
                        "name": t.get("name"),
                        "timestamp": t.get("timestamp"),
                        "user_id": t.get("userId"),
                        "session_id": t.get("sessionId"),
                        "tags": t.get("tags", []),
                        "latency": t.get("latency"),
                        "total_cost": t.get("totalCost"),
                        "observation_count": len(t.get("observations", [])),
                    }
                )

            meta = result.get("meta", {})
            return {
                "count": len(traces),
                "total_items": meta.get("totalItems", 0),
                "page": meta.get("page", page),
                "total_pages": meta.get("totalPages", 0),
                "traces": traces,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def langfuse_get_trace(trace_id: str) -> dict:
        """
        Get full details of a specific Langfuse trace.

        Args:
            trace_id: The trace ID.

        Returns:
            Dict with trace details including observations and scores.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        public_key, secret_key, host = creds

        if not trace_id:
            return {"error": "trace_id is required"}

        try:
            resp = httpx.get(
                f"{host}/api/public/traces/{trace_id}",
                auth=_auth(public_key, secret_key),
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            observations = []
            for obs in result.get("observations", []):
                observations.append(
                    {
                        "id": obs.get("id"),
                        "type": obs.get("type"),
                        "name": obs.get("name"),
                        "model": obs.get("model"),
                        "start_time": obs.get("startTime"),
                        "end_time": obs.get("endTime"),
                        "usage": obs.get("usage"),
                    }
                )

            scores = []
            for s in result.get("scores", []):
                scores.append(
                    {
                        "id": s.get("id"),
                        "name": s.get("name"),
                        "value": s.get("value"),
                        "data_type": s.get("dataType"),
                        "source": s.get("source"),
                        "comment": s.get("comment"),
                    }
                )

            return {
                "id": result.get("id"),
                "name": result.get("name"),
                "timestamp": result.get("timestamp"),
                "user_id": result.get("userId"),
                "session_id": result.get("sessionId"),
                "tags": result.get("tags", []),
                "latency": result.get("latency"),
                "total_cost": result.get("totalCost"),
                "input": result.get("input"),
                "output": result.get("output"),
                "observations": observations,
                "scores": scores,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def langfuse_list_scores(
        trace_id: str = "",
        name: str = "",
        source: str = "",
        data_type: str = "",
        page: int = 1,
        limit: int = 50,
    ) -> dict:
        """
        List scores from Langfuse with optional filters.

        Args:
            trace_id: Filter by trace ID.
            name: Filter by score name.
            source: Filter by source - "API", "ANNOTATION", or "EVAL".
            data_type: Filter by data type - "NUMERIC", "CATEGORICAL", or "BOOLEAN".
            page: Page number (starts at 1).
            limit: Items per page (default 50).

        Returns:
            Dict with scores list and pagination metadata.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        public_key, secret_key, host = creds

        try:
            params: dict[str, Any] = {"page": page, "limit": limit}
            if trace_id:
                params["traceId"] = trace_id
            if name:
                params["name"] = name
            if source:
                params["source"] = source
            if data_type:
                params["dataType"] = data_type

            resp = httpx.get(
                f"{host}/api/public/v2/scores",
                auth=_auth(public_key, secret_key),
                params=params,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            scores = []
            for s in result.get("data", []):
                scores.append(
                    {
                        "id": s.get("id"),
                        "trace_id": s.get("traceId"),
                        "observation_id": s.get("observationId"),
                        "name": s.get("name"),
                        "value": s.get("value"),
                        "data_type": s.get("dataType"),
                        "source": s.get("source"),
                        "comment": s.get("comment"),
                        "timestamp": s.get("timestamp"),
                    }
                )

            meta = result.get("meta", {})
            return {
                "count": len(scores),
                "total_items": meta.get("totalItems", 0),
                "page": meta.get("page", page),
                "total_pages": meta.get("totalPages", 0),
                "scores": scores,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def langfuse_create_score(
        trace_id: str,
        name: str,
        value: float,
        data_type: str = "NUMERIC",
        comment: str = "",
        observation_id: str = "",
    ) -> dict:
        """
        Create a score for a Langfuse trace or observation.

        Args:
            trace_id: The trace ID to score.
            name: Score name (e.g. "correctness", "helpfulness").
            value: Score value (number for NUMERIC, 0/1 for BOOLEAN).
            data_type: Score data type - "NUMERIC", "CATEGORICAL", or "BOOLEAN".
            comment: Optional annotation/explanation.
            observation_id: Optional observation ID within the trace.

        Returns:
            Dict with created score ID.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        public_key, secret_key, host = creds

        if not trace_id or not name:
            return {"error": "trace_id and name are required"}

        try:
            body: dict[str, Any] = {
                "traceId": trace_id,
                "name": name,
                "value": value,
                "dataType": data_type,
            }
            if comment:
                body["comment"] = comment
            if observation_id:
                body["observationId"] = observation_id

            resp = httpx.post(
                f"{host}/api/public/scores",
                auth=_auth(public_key, secret_key),
                json=body,
                timeout=30.0,
            )
            result = _handle_response(resp)
            return result
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def langfuse_list_prompts(
        name: str = "",
        label: str = "",
        tag: str = "",
        page: int = 1,
        limit: int = 50,
    ) -> dict:
        """
        List prompts from Langfuse prompt management.

        Args:
            name: Filter by prompt name.
            label: Filter by label (e.g. "production").
            tag: Filter by tag.
            page: Page number (starts at 1).
            limit: Items per page (default 50).

        Returns:
            Dict with prompts list and pagination metadata.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        public_key, secret_key, host = creds

        try:
            params: dict[str, Any] = {"page": page, "limit": limit}
            if name:
                params["name"] = name
            if label:
                params["label"] = label
            if tag:
                params["tag"] = tag

            resp = httpx.get(
                f"{host}/api/public/v2/prompts",
                auth=_auth(public_key, secret_key),
                params=params,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            prompts = []
            for p in result.get("data", []):
                prompts.append(
                    {
                        "name": p.get("name"),
                        "versions": p.get("versions", []),
                        "labels": p.get("labels", []),
                        "tags": p.get("tags", []),
                        "last_updated_at": p.get("lastUpdatedAt"),
                    }
                )

            meta = result.get("meta", {})
            return {
                "count": len(prompts),
                "total_items": meta.get("totalItems", 0),
                "page": meta.get("page", page),
                "total_pages": meta.get("totalPages", 0),
                "prompts": prompts,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def langfuse_get_prompt(
        prompt_name: str,
        version: int = 0,
        label: str = "",
    ) -> dict:
        """
        Get a specific Langfuse prompt by name.

        Args:
            prompt_name: The prompt name.
            version: Specific version number (0 for latest production).
            label: Label to fetch (e.g. "production", "staging").

        Returns:
            Dict with prompt content, version, and metadata.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        public_key, secret_key, host = creds

        if not prompt_name:
            return {"error": "prompt_name is required"}

        try:
            params: dict[str, Any] = {}
            if version > 0:
                params["version"] = version
            if label:
                params["label"] = label

            resp = httpx.get(
                f"{host}/api/public/v2/prompts/{prompt_name}",
                auth=_auth(public_key, secret_key),
                params=params,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if "error" in result:
                return result

            return {
                "name": result.get("name"),
                "version": result.get("version"),
                "type": result.get("type"),
                "prompt": result.get("prompt"),
                "config": result.get("config"),
                "labels": result.get("labels", []),
                "tags": result.get("tags", []),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
