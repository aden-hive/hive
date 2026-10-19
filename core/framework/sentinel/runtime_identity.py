"""Stable identity for this runtime instance — the Hive Inbox routing key.

A reply is routed back to the runtime that ORIGINATED the escalation, so each
runtime needs a ``runtime_id`` that is globally unique and stable across the
life of the process/sandbox:

  * **cloud** — the e2b sandbox id, so it reconciles with ``account_vm`` on the
    backend. The cloud spawner should set ``HIVE_RUNTIME_ID`` (and
    ``HIVE_RUNTIME_KIND=cloud``).
  * **local** — a uuid persisted under ``$HIVE_HOME/runtime_id`` so it survives
    restarts of the desktop-spawned subprocess.

Both are overridable via ``HIVE_RUNTIME_ID`` / ``HIVE_RUNTIME_KIND`` so the
spawner can pin them explicitly. See docs/hive-inbox-design.md.
"""

from __future__ import annotations

import logging
import os
import uuid

from framework.config import HIVE_HOME

logger = logging.getLogger(__name__)

_ID_PATH = HIVE_HOME / "runtime_id"

# Cache so we don't re-read/re-generate per escalation.
_cached_id: str | None = None


def get_runtime_kind() -> str:
    """``"cloud"`` or ``"local"``. Explicit env wins; otherwise a cloud id env
    implies cloud, else local."""
    k = os.environ.get("HIVE_RUNTIME_KIND", "").strip().lower()
    if k in ("local", "cloud"):
        return k
    if os.environ.get("HIVE_RUNTIME_ID", "").strip() or os.environ.get("E2B_SANDBOX_ID", "").strip():
        return "cloud"
    return "local"


def get_runtime_id() -> str:
    """Stable id for this runtime. Env override > E2B sandbox id > persisted
    local uuid (created lazily)."""
    global _cached_id
    if _cached_id is not None:
        return _cached_id

    rid = os.environ.get("HIVE_RUNTIME_ID", "").strip() or os.environ.get("E2B_SANDBOX_ID", "").strip()
    if rid:
        _cached_id = rid
        return rid

    try:
        if _ID_PATH.exists():
            v = _ID_PATH.read_text(encoding="utf-8").strip()
            if v:
                _cached_id = v
                return v
    except OSError:
        logger.debug("sentinel: could not read runtime_id, regenerating", exc_info=True)

    rid = f"local-{uuid.uuid4().hex}"
    try:
        _ID_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ID_PATH.write_text(rid, encoding="utf-8")
    except OSError:
        logger.debug("sentinel: could not persist runtime_id; using ephemeral", exc_info=True)
    _cached_id = rid
    return rid
