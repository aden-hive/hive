"""
Pluggable credential management system.

Supports multiple credential sources (Env vars, config files, Vault, etc.)
managed via a priority chain.
"""

import os
import logging
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from pathlib import Path
import yaml

from framework.errors import ConfigurationError

logger = logging.getLogger(__name__)

class CredentialSource(ABC):
    """Abstract base class for credential sources."""

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """Retrieve a credential value by key."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the source for logging/audit."""
        pass


class EnvVarSource(CredentialSource):
    """Credential source that reads from environment variables."""

    def __init__(self, prefix: str = ""):
        self.prefix = prefix

    @property
    def name(self) -> str:
        return "Environment Variables"

    def get(self, key: str) -> Optional[str]:
        # Try exact match first, then with prefix
        val = os.environ.get(key)
        if val is None and self.prefix:
            val = os.environ.get(f"{self.prefix}{key}")
        return val


class ConfigFileSource(CredentialSource):
    """
    Credential source that reads from a YAML or JSON config file.
    
    Supports nested keys via dot notation for internal lookup, 
    but the main interface 'get' expects top-level keys usually.
    This simple implementation assumes a flat key-value map or uses the key directly.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self._cache: Dict[str, Any] = {}
        self._ensure_loaded()

    @property
    def name(self) -> str:
        return f"Config File ({self.path})"

    def _ensure_loaded(self):
        if not self.path.exists():
            return

        try:
            with open(self.path, "r") as f:
                content = yaml.safe_load(f) or {}
                if isinstance(content, dict):
                    self._cache = content
                else:
                    logger.warning(f"Config file {self.path} must contain a dictionary")
        except Exception as e:
            logger.error(f"Failed to load credential config file {self.path}: {e}")

    def get(self, key: str) -> Optional[str]:
        # Reloading logic could be added here for hot-reloading
        val = self._cache.get(key)
        return str(val) if val is not None else None


class CredentialManager:
    """
    Manager that chains multiple CredentialSources.
    
    Attributes:
        sources: List of CredentialSource instances in priority order.
    """

    def __init__(self, sources: List[CredentialSource] | None = None):
        if sources is None:
            # Default chain: Env Vars only
            self.sources = [EnvVarSource()]
        else:
            self.sources = sources

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Retrieve a credential by checking sources in order.
        
        Args:
            key: The credential key (e.g. "OPENAI_API_KEY")
            default: Value to return if not found in any source
            
        Returns:
            The credential value provided by the highest priority source, or default.
        """
        for source in self.sources:
            try:
                val = source.get(key)
                if val is not None:
                    # Optional: Add audit logging here (Phase 3)
                    # logger.debug(f"Found credential {key} in {source.name}")
                    return val
            except Exception as e:
                logger.warning(f"Error reading from credential source {source.name}: {e}")
                continue
        
        return default

    def get_or_error(self, key: str) -> str:
        """
        Retrieve a credential or raise an error if missing.
        
        Raises:
            ConfigurationError: If credential is not found.
        """
        val = self.get(key)
        if val is None:
            raise ConfigurationError(
                f"Missing required credential: {key}. "
                f"Checked sources: {', '.join(s.name for s in self.sources)}"
            )
        return val
