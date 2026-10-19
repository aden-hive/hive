"""HTTP client for the cloud team global DB (hive-backend ``/v1/global-db/*``).

Mirrors the auth convention of :mod:`framework.cloud_sync`: base URL from
``HIVE_CLOUD_BASE``, ``Authorization: jwt <HIVE_CLOUD_JWT>``. The backend
derives ``team_id`` from the JWT and scopes every call to that team's schema,
so this client never sends a team id.

All functions are async (used by the tracker tools and the global-db proxy
routes, both async). The ``hive-global-db`` CLI drives them via ``asyncio.run``.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx

# Bulk imports can be large; allow more headroom than the 15s sync default.
HTTP_TIMEOUT = httpx.Timeout(60.0, connect=5.0)

# Test seam: when set, requests route through this transport instead of the
# network (mirrors cloud_sync._TRANSPORT_OVERRIDE).
_TRANSPORT_OVERRIDE: Any = None


class NotSignedInError(Exception):
    """No cloud session — the global DB requires sign-in (HIVE_CLOUD_JWT/BASE)."""


class GlobalDbError(Exception):
    """Non-2xx response from the global-db backend."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _cloud_config() -> tuple[str, str]:
    """Return ``(base_url, jwt)`` or raise :class:`NotSignedInError`."""
    jwt = os.environ.get("HIVE_CLOUD_JWT", "").strip()
    base = os.environ.get("HIVE_CLOUD_BASE", "").strip()
    if not jwt or not base:
        raise NotSignedInError("Sign in to use the shared global DB — no cloud session (HIVE_CLOUD_JWT / HIVE_CLOUD_BASE unset).")
    return base.rstrip("/"), jwt


def _extract_error(resp: httpx.Response) -> str:
    """Pull the backend's ``{error:{message}}`` envelope, else a generic msg."""
    try:
        body = resp.json()
    except Exception:
        return f"HTTP {resp.status_code}"
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or f"HTTP {resp.status_code}")
    if isinstance(err, str):
        return err
    return f"HTTP {resp.status_code}"


async def request(
    method: str,
    path: str,
    *,
    json: Any = None,
    params: dict[str, Any] | None = None,
) -> Any:
    """Issue an authenticated global-db request. Raises NotSignedInError / GlobalDbError."""
    base, jwt = _cloud_config()
    kwargs: dict[str, Any] = {
        "base_url": base,
        "headers": {"Authorization": f"jwt {jwt}"},
        "timeout": HTTP_TIMEOUT,
    }
    if _TRANSPORT_OVERRIDE is not None:
        kwargs["transport"] = _TRANSPORT_OVERRIDE
    async with httpx.AsyncClient(**kwargs) as client:
        resp = await client.request(method, path, json=json, params=params)
    if resp.status_code == 401:
        raise NotSignedInError("Cloud session rejected (401) — sign in again.")
    if resp.status_code >= 400:
        raise GlobalDbError(_extract_error(resp), status=resp.status_code)
    if resp.content:
        return resp.json()
    return {}


# --------------------------------------------------------------------------
# Convenience wrappers (one per backend endpoint)
# --------------------------------------------------------------------------


async def sql(sql_text: str, *, row_cap: int | None = None) -> Any:
    body: dict[str, Any] = {"sql": sql_text}
    if row_cap:
        body["row_cap"] = row_cap
    return await request("POST", "/v1/global-db/sql", json=body)


async def query(sql_text: str, *, row_cap: int | None = None) -> Any:
    body: dict[str, Any] = {"sql": sql_text}
    if row_cap:
        body["row_cap"] = row_cap
    return await request("POST", "/v1/global-db/query", json=body)


async def upsert(
    table: str,
    row: dict[str, Any],
    *,
    source_colony: str | None = None,
    mode: str | None = None,
) -> Any:
    """mode=None/'upsert' — agent path, conflict updates in place.
    mode='insert' — UI path; a conflict raises GlobalDbError(status=409)
    instead of overwriting the existing row."""
    body: dict[str, Any] = {"table": table, "row": row}
    if source_colony:
        body["source_colony"] = source_colony
    if mode:
        body["mode"] = mode
    return await request("POST", "/v1/global-db/upsert", json=body)


async def import_rows(table: str, rows: list[dict[str, Any]], *, source_colony: str | None = None) -> Any:
    body: dict[str, Any] = {"table": table, "rows": rows}
    if source_colony:
        body["source_colony"] = source_colony
    return await request("POST", "/v1/global-db/import", json=body)


async def list_tables() -> Any:
    return await request("GET", "/v1/global-db/tables")


async def list_changes(since: str | None = None) -> Any:
    """Row-level change feed. ``since=None`` initializes: cursor + covered
    tables only. Pass the returned ``cursor`` back verbatim on later polls."""
    params = {"since": since} if since else None
    return await request("GET", "/v1/global-db/changes", params=params)


async def list_rows(table: str, *, params: dict[str, Any] | None = None) -> Any:
    return await request("GET", f"/v1/global-db/tables/{quote(table, safe='')}/rows", params=params)


async def update_row(table: str, pk: dict[str, Any], updates: dict[str, Any]) -> Any:
    return await request(
        "PATCH",
        f"/v1/global-db/tables/{quote(table, safe='')}/rows",
        json={"pk": pk, "updates": updates},
    )
