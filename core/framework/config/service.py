"""Configuration management service."""

from typing import Dict, Any, Optional, List
from datetime import datetime
from uuid import UUID
import json

from .models import Configuration, FeatureFlag, ConfigHistory
from .feature_flags import FeatureFlagEngine


class ConfigService:
    """Centralized configuration management service."""

    def __init__(self):
        self.configurations: Dict[str, Configuration] = {}
        self.feature_flags = FeatureFlagEngine()
        self.config_history: List[ConfigHistory] = []

    def set_config(
        self,
        environment: str,
        service: str,
        key: str,
        value: Any,
        config_type: str = "string",
        is_sensitive: bool = False
    ) -> Configuration:
        """Set a configuration value."""
        config_key = f"{environment}:{service}:{key}"

        # Get old value if exists
        old_config = self.configurations.get(config_key)

        # Create or update configuration
        if old_config:
            config = old_config
            old_value = config.value
            config.value = value
            config.type = config_type
            config.is_sensitive = is_sensitive
            config.version += 1
            config.updated_at = datetime.utcnow()
        else:
            config = Configuration(
                environment=environment,
                service=service,
                key=key,
                value=value,
                type=config_type,
                is_sensitive=is_sensitive
            )
            old_value = None

        self.configurations[config_key] = config

        # Record history
        history = ConfigHistory(
            config_id=config.id,
            old_value=old_value,
            new_value=value
        )
        self.config_history.append(history)

        return config

    def get_config(
        self,
        environment: str,
        service: str,
        key: str
    ) -> Optional[Configuration]:
        """Get a configuration value."""
        config_key = f"{environment}:{service}:{key}"
        return self.configurations.get(config_key)

    def get_all_configs(self, environment: str, service: str) -> List[Configuration]:
        """Get all configurations for a service."""
        prefix = f"{environment}:{service}:"
        return [
            config for key, config in self.configurations.items()
            if key.startswith(prefix)
        ]

    def delete_config(
        self,
        environment: str,
        service: str,
        key: str
    ) -> bool:
        """Delete a configuration."""
        config_key = f"{environment}:{service}:{key}"
        if config_key in self.configurations:
            del self.configurations[config_key]
            return True
        return False

    def set_feature_flag(
        self,
        name: str,
        enabled: bool,
        description: str = None,
        rules: List[Dict[str, Any]] = None,
        rollout_percentage: int = 100
    ) -> FeatureFlag:
        """Set or create a feature flag."""
        flag = FeatureFlag(
            name=name,
            description=description,
            enabled=enabled,
            rules=rules or [],
            rollout_percentage=rollout_percentage
        )
        self.feature_flags.add_flag(flag)
        return flag

    def evaluate_feature_flag(
        self,
        flag_name: str,
        user_attributes: Dict[str, Any] = None
    ) -> bool:
        """Evaluate a feature flag."""
        return self.feature_flags.evaluate(flag_name, user_attributes)

    def get_all_feature_flags(self) -> List[FeatureFlag]:
        """Get all feature flags."""
        return self.feature_flags.get_all_flags()

    def get_config_history(
        self,
        config_id: UUID,
        limit: int = 100
    ) -> List[ConfigHistory]:
        """Get configuration change history."""
        history = [
            h for h in self.config_history
            if h.config_id == config_id
        ]
        return sorted(history, key=lambda x: x.changed_at, reverse=True)[:limit]

    def export_configs(self, environment: str) -> Dict[str, Any]:
        """Export all configurations for an environment."""
        env_configs = {
            key: config
            for key, config in self.configurations.items()
            if key.startswith(f"{environment}:")
        }

        # Filter sensitive values
        exported = {}
        for key, config in env_configs.items():
            exported[key] = {
                "value": "***HIDDEN***" if config.is_sensitive else config.value,
                "type": config.type,
                "version": config.version
            }

        return exported

    def validate_config(self, value: Any, config_type: str) -> bool:
        """Validate configuration value against type."""
        if config_type == "string":
            return isinstance(value, str)
        elif config_type == "number":
            return isinstance(value, (int, float))
        elif config_type == "boolean":
            return isinstance(value, bool)
        elif config_type == "json":
            try:
                json.dumps(value)
                return True
            except:
                return False
        return False
