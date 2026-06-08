"""
Weights & Biases ML experiment tracking tool.

Uses the W&B GraphQL API via httpx — no SDK dependency.

Authentication: Bearer token (WANDB_API_KEY)
GraphQL endpoint: https://api.wandb.ai/graphql

API Reference: https://github.com/wandb/wandb/blob/main/wandb/proto/wandb_internal.proto
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

GRAPHQL_URL = "https://api.wandb.ai/graphql"


def _get_creds(
    credentials: CredentialStoreAdapter | None,
) -> tuple[str] | dict[str, Any]:
    """Return (api_key,) or an error dict."""
    if credentials is not None:
        api_key = credentials.get("wandb_api_key")
    else:
        api_key = os.getenv("WANDB_API_KEY")

    if not api_key:
        return {
            "error": "Weights & Biases credentials not configured",
            "help": (
                "Set WANDB_API_KEY environment variable or configure via credential store. "
                "Get your API key at https://wandb.ai/authorize"
            ),
        }
    return (api_key,)


def _graphql(
    api_key: str,
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a GraphQL query and return the parsed response."""
    try:
        resp = httpx.post(
            GRAPHQL_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"query": query, "variables": variables or {}},
            timeout=30.0,
        )
    except httpx.TimeoutException:
        return {"error": "Request timed out"}
    except httpx.RequestError as e:
        return {"error": f"Network error: {e}"}

    if resp.status_code == 401:
        return {"error": "Invalid Weights & Biases API key"}
    if resp.status_code == 403:
        return {"error": "Insufficient permissions for this Weights & Biases resource"}
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("errors", [{}])[0].get("message", resp.text)
        except Exception:
            detail = resp.text
        return {"error": f"Weights & Biases API error (HTTP {resp.status_code}): {detail}"}

    payload = resp.json()
    if "errors" in payload:
        msg = payload["errors"][0].get("message", str(payload["errors"]))
        return {"error": f"Weights & Biases GraphQL error: {msg}"}

    return payload.get("data", {})


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Weights & Biases experiment tracking tools with the MCP server."""

    @mcp.tool()
    def wandb_list_projects(entity: str) -> dict:
        """
        List all projects for a Weights & Biases entity (user or organization).

        Args:
            entity: The W&B entity name (username or organization).

        Returns:
            Dict containing the list of projects for the entity.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        (api_key,) = creds

        query = """
        query ListProjects($entity: String!) {
          projects(entityName: $entity) {
            edges {
              node {
                name
                description
                createdAt
              }
            }
          }
        }
        """
        data = _graphql(api_key, query, {"entity": entity})
        if "error" in data:
            return data

        edges = data.get("projects", {}).get("edges", [])
        return {
            "entity": entity,
            "projects": [
                {
                    "name": e["node"]["name"],
                    "description": e["node"].get("description", ""),
                    "created_at": e["node"].get("createdAt", ""),
                }
                for e in edges
            ],
        }

    @mcp.tool()
    def wandb_list_runs(
        entity: str,
        project: str,
        filters: str = "",
        per_page: int = 50,
    ) -> dict:
        """
        List runs in a Weights & Biases project.

        Args:
            entity: The W&B entity name (username or organization).
            project: The project name.
            filters: Optional JSON filter string to narrow results.
            per_page: Number of runs to return (default 50).

        Returns:
            Dict containing the list of runs in the project.
        """
        parsed_filters = None
        if filters:
            try:
                parsed_filters = json.loads(filters)
            except json.JSONDecodeError:
                return {"error": "filters must be a valid JSON string"}

        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        (api_key,) = creds

        query = """
        query ListRuns($project: String!, $entity: String!, $perPage: Int!, $filters: JSONString) {
          project(name: $project, entityName: $entity) {
            runs(first: $perPage, filters: $filters) {
              edges {
                node {
                  name
                  id
                  state
                  createdAt
                  config
                  summaryMetrics
                }
              }
            }
          }
        }
        """
        variables: dict[str, Any] = {"project": project, "entity": entity, "perPage": per_page}
        if parsed_filters is not None:
            variables["filters"] = parsed_filters
        data = _graphql(api_key, query, variables)
        if "error" in data:
            return data

        edges = data.get("project", {}).get("runs", {}).get("edges", [])
        runs = []
        for e in edges:
            node = e["node"]
            try:
                config = json.loads(node.get("config") or "{}")
            except (json.JSONDecodeError, TypeError):
                config = {}
            runs.append(
                {
                    "id": node.get("name"),
                    "display_name": node.get("id"),
                    "state": node.get("state"),
                    "created_at": node.get("createdAt"),
                    "config": config,
                }
            )
        return {"entity": entity, "project": project, "runs": runs}

    @mcp.tool()
    def wandb_get_run(entity: str, project: str, run_id: str) -> dict:
        """
        Get details of a specific Weights & Biases run.

        Args:
            entity: The W&B entity name (username or organization).
            project: The project name.
            run_id: The run ID.

        Returns:
            Dict containing full run details including config and metadata.
        """
        if not run_id:
            return {"error": "run_id is required"}

        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        (api_key,) = creds

        query = """
        query GetRun($project: String!, $entity: String!, $run: String!) {
          project(name: $project, entityName: $entity) {
            run(name: $run) {
              name
              id
              state
              createdAt
              config
              summaryMetrics
              tags
              notes
            }
          }
        }
        """
        data = _graphql(api_key, query, {"project": project, "entity": entity, "run": run_id})
        if "error" in data:
            return data

        node = data.get("project", {}).get("run")
        if not node:
            return {"error": "Weights & Biases resource not found"}

        try:
            config = json.loads(node.get("config") or "{}")
        except (json.JSONDecodeError, TypeError):
            config = {}
        try:
            summary = json.loads(node.get("summaryMetrics") or "{}")
        except (json.JSONDecodeError, TypeError):
            summary = {}

        return {
            "id": node.get("name"),
            "display_name": node.get("id"),
            "state": node.get("state"),
            "created_at": node.get("createdAt"),
            "config": config,
            "summary": summary,
            "tags": node.get("tags") or [],
            "notes": node.get("notes") or "",
        }

    @mcp.tool()
    def wandb_get_run_metrics(
        entity: str,
        project: str,
        run_id: str,
        metric_keys: str = "",
    ) -> dict:
        """
        Get sampled metrics history for a specific Weights & Biases run.

        Args:
            entity: The W&B entity name (username or organization).
            project: The project name.
            run_id: The run ID.
            metric_keys: Comma-separated metric keys to sample (e.g. "loss,accuracy").
                         At least one key is required.

        Returns:
            Dict containing sampled metric history per key.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        (api_key,) = creds

        if not run_id:
            return {"error": "run_id is required"}
        if not metric_keys:
            return {"error": "metric_keys is required (comma-separated, e.g. 'loss,accuracy')"}

        keys = [k.strip() for k in metric_keys.split(",") if k.strip()]
        if not keys:
            return {"error": "metric_keys must include at least one non-empty key"}
        specs = json.dumps([{"key": k} for k in keys])

        query = f"""
        query GetRunMetrics($project: String!, $entity: String!, $run: String!) {{
          project(name: $project, entityName: $entity) {{
            run(name: $run) {{
              sampledHistory(specs: {specs})
            }}
          }}
        }}
        """
        data = _graphql(api_key, query, {"project": project, "entity": entity, "run": run_id})
        if "error" in data:
            return data

        node = data.get("project", {}).get("run")
        if not node:
            return {"error": "Weights & Biases resource not found"}

        return {
            "run_id": run_id,
            "metric_keys": keys,
            "history": node.get("sampledHistory", []),
        }

    @mcp.tool()
    def wandb_list_artifacts(entity: str, project: str, run_id: str) -> dict:
        """
        List artifacts logged by a specific Weights & Biases run.

        Args:
            entity: The W&B entity name (username or organization).
            project: The project name.
            run_id: The run ID.

        Returns:
            Dict containing the list of output artifacts for the run.
        """
        if not run_id:
            return {"error": "run_id is required"}

        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        (api_key,) = creds

        query = """
        query ListArtifacts($project: String!, $entity: String!, $run: String!) {
          project(name: $project, entityName: $entity) {
            run(name: $run) {
              outputArtifacts {
                edges {
                  node {
                    name
                    type
                    description
                    createdAt
                  }
                }
              }
            }
          }
        }
        """
        data = _graphql(api_key, query, {"project": project, "entity": entity, "run": run_id})
        if "error" in data:
            return data

        node = data.get("project", {}).get("run")
        if not node:
            return {"error": "Weights & Biases resource not found"}

        edges = node.get("outputArtifacts", {}).get("edges", [])
        return {
            "run_id": run_id,
            "artifacts": [
                {
                    "name": e["node"]["name"],
                    "type": e["node"]["type"],
                    "description": e["node"].get("description", ""),
                    "created_at": e["node"].get("createdAt", ""),
                }
                for e in edges
            ],
        }

    @mcp.tool()
    def wandb_get_summary(entity: str, project: str, run_id: str) -> dict:
        """
        Get summary metrics for a specific Weights & Biases run.

        Args:
            entity: The W&B entity name (username or organization).
            project: The project name.
            run_id: The run ID.

        Returns:
            Dict containing the run's final summary metrics.
        """
        if not run_id:
            return {"error": "run_id is required"}

        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        (api_key,) = creds

        query = """
        query GetSummary($project: String!, $entity: String!, $run: String!) {
          project(name: $project, entityName: $entity) {
            run(name: $run) {
              summaryMetrics
            }
          }
        }
        """
        data = _graphql(api_key, query, {"project": project, "entity": entity, "run": run_id})
        if "error" in data:
            return data

        node = data.get("project", {}).get("run")
        if not node:
            return {"error": "Weights & Biases resource not found"}

        try:
            summary = json.loads(node.get("summaryMetrics") or "{}")
        except (json.JSONDecodeError, TypeError):
            summary = {}

        # Filter out internal W&B keys
        summary = {k: v for k, v in summary.items() if not k.startswith("_")}
        return {"run_id": run_id, "summary": summary}
