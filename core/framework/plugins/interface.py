"""Plugin system interface."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pydantic import BaseModel


class PluginMetadata(BaseModel):
    """Plugin metadata."""
    name: str
    version: str
    description: str
    author: str
    dependencies: list[str] = []
    capabilities: list[str] = []
    config_schema: Dict[str, Any] = {}


class PluginInterface(ABC):
    """Base plugin interface."""

    @abstractmethod
    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        pass

    @abstractmethod
    async def initialize(self, config: Dict[str, Any]) -> None:
        """Initialize plugin with configuration."""
        pass

    @abstractmethod
    async def validate(self) -> bool:
        """Validate plugin configuration."""
        pass

    @abstractmethod
    async def start(self) -> None:
        """Start plugin."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop plugin."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check plugin health."""
        pass


class NodePlugin(PluginInterface):
    """Node plugin interface."""

    @abstractmethod
    async def execute(self, context: 'NodeContext') -> Any:
        """Execute node logic."""
        pass


class ToolPlugin(PluginInterface):
    """Tool plugin interface."""

    @abstractmethod
    async def invoke(self, params: Dict[str, Any]) -> Any:
        """Invoke tool."""
        pass

    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """Get tool schema."""
        pass
