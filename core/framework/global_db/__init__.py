"""Runtime client for the cloud team global DB (hive-backend ``/v1/global-db/*``).

The shared, cross-colony GTM tracker lives in the backend's Postgres
(schema-per-team), not on local disk. ``scope="global"`` tracker calls and
the ``hive-global-db`` CLI route through here. Requires a signed-in cloud
session (``HIVE_CLOUD_JWT`` / ``HIVE_CLOUD_BASE``); without one, calls raise
:class:`NotSignedInError`.
"""

from framework.global_db.client import (
    GlobalDbError,
    NotSignedInError,
    import_rows,
    list_rows,
    list_tables,
    query,
    request,
    sql,
    update_row,
    upsert,
)

__all__ = [
    "GlobalDbError",
    "NotSignedInError",
    "import_rows",
    "list_rows",
    "list_tables",
    "query",
    "request",
    "sql",
    "update_row",
    "upsert",
]
