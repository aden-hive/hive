"""Plugin registry and loader."""

from typing import Dict, Type, Optional
import importlib
import pkgutil
from .interface import PluginInterface, PluginMetadata


class PluginRegistry:
    """Central plugin registry."""

    def __init__(self):
        self._plugins: Dict[str, Type[PluginInterface]] = {}
        self._loaded_plugins: Dict[str, PluginInterface] = {}

    def register(self, plugin_class: Type[PluginInterface]) -> None:
        """Register a plugin class."""
        plugin = plugin_class()
        metadata = plugin.get_metadata()
        self._plugins[metadata.name] = plugin_class

    async def load_plugin(
        self,
        name: str,
        config: Dict[str, Any] = None
    ) -> PluginInterface:
        """Load and initialize a plugin."""
        if name not in self._plugins:
            raise ValueError(f"Plugin {name} not found in registry")

        plugin_class = self._plugins[name]
        plugin = plugin_class()
        await plugin.initialize(config or {})
        await plugin.validate()
        await plugin.start()

        self._loaded_plugins[name] = plugin
        return plugin

    def list_plugins(self) -> Dict[str, PluginMetadata]:
        """List all registered plugins."""
        return {
            name: cls().get_metadata()
            for name, cls in self._plugins.items()
        }

    async def unload_plugin(self, name: str) -> None:
        """Unload a plugin."""
        if name in self._loaded_plugins:
            plugin = self._loaded_plugins[name]
            await plugin.stop()
            del self._loaded_plugins[name]

    async def discover_plugins(self, package_path: str) -> None:
        """Auto-discover plugins in a package."""
        for _, name, _ in pkgutil.iter_modules([package_path]):
            try:
                module = importlib.import_module(f"{package_path}.{name}")
                if hasattr(module, 'register_plugin'):
                    module.register_plugin(self)
            except Exception as e:
                print(f"Failed to load plugin {name}: {e}")

    async def get_plugin(self, name: str) -> Optional[PluginInterface]:
        """Get loaded plugin by name."""
        return self._loaded_plugins.get(name)
