"""Registry client for the Hive community skill registry.

Fetches the skill index from the hive-skill-registry GitHub repo, caches it
locally, and provides search and resolution utilities.

The registry repo (Phase 3) may not exist yet. All public methods degrade
gracefully — returning None or [] on any network or parse failure.

Configure a custom registry URL via the HIVE_REGISTRY_URL environment variable.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

logger = logging.getLogger(__name__)

# Default registry index URL (Phase 3 repo, may not exist yet)
_DEFAULT_REGISTRY_URL = (
    "https://raw.githubusercontent.com/hive-skill-registry/hive-skill-registry/main/skill_index.json"
)

_CACHE_DIR = Path.home() / ".hive" / "registry_cache"
_CACHE_INDEX_PATH = _CACHE_DIR / "skill_index.json"
_CACHE_METADATA_PATH = _CACHE_DIR / "metadata.json"
_CACHE_TTL_SECONDS = 3600  # 1 hour


class RegistryClient:
    """Client for the Hive community skill registry.

    All public methods return None / [] on any failure — never raise.
    Network errors, parse failures, and missing registries are all
    treated as graceful degradation.
    """

    def __init__(
        self,
        registry_url: str | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._url = registry_url or os.environ.get("HIVE_REGISTRY_URL", _DEFAULT_REGISTRY_URL)
        cache_root = cache_dir or _CACHE_DIR
        self._index_path = cache_root / "skill_index.json"
        self._metadata_path = cache_root / "metadata.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_index(self, force_refresh: bool = False) -> dict | None:
        """Return the registry index dict.

        Uses the local cache if it is fresh (within TTL) unless
        force_refresh=True. Returns None on any failure.
        """
        if not force_refresh and self._is_cache_fresh():
            cached = self._load_cache()
            if cached is not None:
                return cached

        raw = self._http_fetch(self._url)
        if raw is None:
            # Network unavailable — fall back to stale cache if present
            stale = self._load_cache()
            if stale is not None:
                logger.debug("registry: network unavailable, using stale cache")
            return stale

        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("registry: failed to parse index JSON: %s", exc)
            return self._load_cache()

        if not isinstance(data, dict):
            logger.warning("registry: index is not a JSON object")
            return self._load_cache()

        self._save_cache(data)
        return data

    def search(self, query: str) -> list[dict]:
        """Search registry skills by name, description, or tags.

        Case-insensitive substring match. Returns [] if index unavailable.
        """
        index = self.fetch_index()
        if not index:
            return []
        skills = index.get("skills", [])
        if not isinstance(skills, list):
            return []
        q = query.lower()
        results = []
        for entry in skills:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).lower()
            description = str(entry.get("description", "")).lower()
            tags = " ".join(str(t) for t in entry.get("tags", [])).lower()
            if q in name or q in description or q in tags:
                results.append(entry)
        return results

    def get_skill_entry(self, name: str) -> dict | None:
        """Look up a single skill by exact name. Returns None if not found."""
        index = self.fetch_index()
        if not index:
            return None
        for entry in index.get("skills", []):
            if isinstance(entry, dict) and entry.get("name") == name:
                return entry
        return None

    def get_pack(self, pack_name: str) -> list[str] | None:
        """Return the list of skill names in a starter pack.

        Returns None if the pack is not found or the index is unavailable.
        """
        index = self.fetch_index()
        if not index:
            return None
        for pack in index.get("packs", []):
            if isinstance(pack, dict) and pack.get("name") == pack_name:
                skills = pack.get("skills", [])
                if isinstance(skills, list):
                    return [s for s in skills if isinstance(s, str)]
        return None

    def resolve_git_url(self, name: str) -> tuple[str, str | None] | None:
        """Return (git_url, subdirectory) for a skill name.

        Returns None if the skill is not in the registry or the index
        is unavailable.
        """
        entry = self.get_skill_entry(name)
        if not entry:
            return None
        git_url = entry.get("git_url")
        if not git_url:
            return None
        subdirectory = entry.get("subdirectory") or None
        return str(git_url), subdirectory

    # ------------------------------------------------------------------
    # Cache internals
    # ------------------------------------------------------------------

    def _load_cache(self) -> dict | None:
        """Read cached index from disk. Returns None if absent or unreadable."""
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.debug("registry: could not read cache: %s", exc)
            return None

    def _save_cache(self, data: dict) -> None:
        """Write index to disk atomically (.tmp then rename)."""
        try:
            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._index_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self._index_path)
            # Update metadata
            meta = {"last_fetched": datetime.now(tz=UTC).isoformat()}
            meta_tmp = self._metadata_path.with_suffix(".tmp")
            meta_tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            meta_tmp.replace(self._metadata_path)
        except Exception as exc:
            logger.debug("registry: could not write cache: %s", exc)

    def _is_cache_fresh(self) -> bool:
        """Return True if the cached index was fetched within the TTL."""
        try:
            meta = json.loads(self._metadata_path.read_text(encoding="utf-8"))
            last_fetched = datetime.fromisoformat(meta["last_fetched"])
            age = (datetime.now(tz=UTC) - last_fetched).total_seconds()
            return age < _CACHE_TTL_SECONDS
        except Exception:
            return False

    def _http_fetch(self, url: str, timeout: int = 10) -> bytes | None:
        """Fetch URL contents. Returns None on any network error — never raises."""
        try:
            with urlopen(url, timeout=timeout) as resp:  # noqa: S310
                return resp.read()
        except URLError as exc:
            logger.debug("registry: HTTP fetch failed for %s: %s", url, exc)
            return None
        except TimeoutError as exc:
            logger.debug("registry: HTTP fetch timed out for %s: %s", url, exc)
            return None
        except Exception as exc:
            logger.debug("registry: unexpected error fetching %s: %s", url, exc)
            return None
