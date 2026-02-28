"""Credential helpers for RSS Twitter Playwright agent (Hive v0.6+)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _extract_session_dir(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in (
            "session_dir",
            "user_data_dir",
            "twitter_session_dir",
            "playwright_user_data_dir",
            "path",
            "value",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    elif isinstance(payload, str):
        raw = payload.strip()
        if not raw:
            return None
        if raw.startswith("{"):
            try:
                obj = json.loads(raw)
                return _extract_session_dir(obj)
            except json.JSONDecodeError:
                return None
        return raw
    return None


def resolve_twitter_session_dir(credential_ref: str | None = None) -> str:
    """Resolve session dir from env first, then Hive credential store."""
    env_dir = os.environ.get("HIVE_TWITTER_SESSION_DIR")
    if env_dir:
        return str(Path(env_dir).expanduser())

    ref = credential_ref or os.environ.get("TWITTER_CREDENTIAL_REF")
    if ref and "/" in ref:
        try:
            from framework.credentials.store import CredentialStore

            store = CredentialStore.with_encrypted_storage(Path.home() / ".hive" / "credentials")
            value = store.get(ref)
            resolved = _extract_session_dir(value)
            if resolved:
                return str(Path(resolved).expanduser())
        except Exception:
            pass

    return str(Path.home() / ".hive" / "twitter_session")
