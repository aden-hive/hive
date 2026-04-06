"""
Weights & Biases ML experiment tracking tool.

Uses the official W&B Python SDK (wandb.Api) — no undocumented REST endpoints.

Supports:
- Credential store via wandb_api_key
- Environment variable WANDB_API_KEY

SDK reference: https://docs.wandb.ai/guides/track/public-api-guide
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _get_creds(
    credentials: CredentialStoreAdapter | None,
) -> tuple[str] | dict[str, Any]:
    """Return (api_key,) or an error dict."""
    if credentials is not None:
        api_key = credentials.get("wandb_api_key")
        try:
            # wandb_host is optional; SDK doesn't need it for cloud
            _ = credentials.get("wandb_host")
        except KeyError:
            pass
    else:
        api_key = os.getenv("WANDB_API_KEY")

    if not api_key:
        return {
            "error": "Weights & Biases credentials not configured",
            "help": ("Set WANDB_API_KEY environment variable or configure via credential store"),
        }
    return (api_key,)


def _make_api(api_key: str) -> Any:
    """Create a wandb.Api instance with the given key."""
    import wandb

    return wandb.Api(api_key=api_key)


def register_tools(
    mcp: Any,
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

        try:
            api = _make_api(api_key)
            projects = api.projects(entity=entity)
            return {
                "entity": entity,
                "projects": [
                    {
                        "name": p.name,
                        "id": p.id,
                        "description": getattr(p, "description", ""),
                        "url": getattr(p, "url", ""),
                    }
                    for p in projects
                ],
            }
        except Exception as e:
            return {"error": f"Weights & Biases error: {e}"}

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
            per_page: Number of runs per page (default 50).

        Returns:
            Dict containing the list of runs in the project.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        (api_key,) = creds

        try:
            import json as _json

            # Validate filters JSON before touching the API
            parsed_filters: dict[str, Any] | None = None
            if filters:
                try:
                    parsed_filters = _json.loads(filters)
                except _json.JSONDecodeError:
                    return {"error": "filters must be a valid JSON string"}

            api = _make_api(api_key)
            kwargs: dict[str, Any] = {"per_page": per_page}
            if parsed_filters is not None:
                kwargs["filters"] = parsed_filters

            runs = api.runs(path=f"{entity}/{project}", **kwargs)
            return {
                "entity": entity,
                "project": project,
                "runs": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "state": r.state,
                        "url": r.url,
                        "created_at": str(r.created_at),
                        "config": dict(r.config),
                    }
                    for r in runs
                ],
            }
        except Exception as e:
            return {"error": f"Weights & Biases error: {e}"}

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

        try:
            api = _make_api(api_key)
            run = api.run(f"{entity}/{project}/{run_id}")
            return {
                "id": run.id,
                "name": run.name,
                "state": run.state,
                "url": run.url,
                "created_at": str(run.created_at),
                "config": dict(run.config),
                "tags": list(run.tags),
                "notes": run.notes or "",
            }
        except Exception as e:
            return {"error": f"Weights & Biases error: {e}"}

    @mcp.tool()
    def wandb_get_run_metrics(
        entity: str,
        project: str,
        run_id: str,
        metric_keys: str = "",
    ) -> dict:
        """
        Get metrics history for a specific Weights & Biases run.

        Args:
            entity: The W&B entity name (username or organization).
            project: The project name.
            run_id: The run ID.
            metric_keys: Optional comma-separated list of metric keys to filter.

        Returns:
            Dict containing the run's metric history as a list of step dicts.
        """
        if not run_id:
            return {"error": "run_id is required"}

        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        (api_key,) = creds

        try:
            api = _make_api(api_key)
            run = api.run(f"{entity}/{project}/{run_id}")

            keys = [k.strip() for k in metric_keys.split(",") if k.strip()] if metric_keys else None
            history = run.history(samples=500, keys=keys)

            return {
                "run_id": run_id,
                "steps": history.to_dict(orient="records"),
            }
        except Exception as e:
            return {"error": f"Weights & Biases error: {e}"}

    @mcp.tool()
    def wandb_list_artifacts(entity: str, project: str, run_id: str) -> dict:
        """
        List artifacts logged by a specific Weights & Biases run.

        Args:
            entity: The W&B entity name (username or organization).
            project: The project name.
            run_id: The run ID.

        Returns:
            Dict containing the list of artifacts logged by the run.
        """
        if not run_id:
            return {"error": "run_id is required"}

        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        (api_key,) = creds

        try:
            api = _make_api(api_key)
            run = api.run(f"{entity}/{project}/{run_id}")
            artifacts = run.logged_artifacts()
            return {
                "run_id": run_id,
                "artifacts": [
                    {
                        "name": a.name,
                        "type": a.type,
                        "version": getattr(a, "version", ""),
                        "size": getattr(a, "size", 0),
                    }
                    for a in artifacts
                ],
            }
        except Exception as e:
            return {"error": f"Weights & Biases error: {e}"}

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

        try:
            api = _make_api(api_key)
            run = api.run(f"{entity}/{project}/{run_id}")
            # Filter out internal W&B keys (prefixed with _)
            summary = {k: v for k, v in run.summary.items() if not k.startswith("_")}
            return {
                "run_id": run_id,
                "summary": summary,
            }
        except Exception as e:
            return {"error": f"Weights & Biases error: {e}"}
