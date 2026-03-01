"""
Telemetry module for collecting anonymous usage data.

This module integrates with PostHog to collect analytics events
such as agent execution success/failure rates, duration, and errors.
This helps improve the stability and performance of the framework.

Telemetry is OPT-IN via configuration.
"""

import logging
import os
import platform
import uuid
from functools import lru_cache
from typing import Any

from framework.config import get_hive_config

logger = logging.getLogger(__name__)

try:
    import posthog
    POSTHOG_AVAILABLE = True
except ImportError:
    POSTHOG_AVAILABLE = False


@lru_cache(maxsize=1)
def get_machine_id() -> str:
    """Get a unique identifier for the machine."""
    # Check for existing ID file
    id_file = os.path.expanduser("~/.hive/machine_id")
    if os.path.exists(id_file):
        try:
            with open(id_file, "r") as f:
                return f.read().strip()
        except OSError:
            pass
            
    # Generate new ID
    new_id = str(uuid.uuid4())
    try:
        os.makedirs(os.path.dirname(id_file), exist_ok=True)
        with open(id_file, "w") as f:
            f.write(new_id)
    except OSError:
        # Fallback to random ID in memory if we can't write to disk
        pass
        
    return new_id


class TelemetryClient:
    """Client for sending telemetry events to PostHog."""

    def __init__(self):
        self.enabled = False
        self.client = None
        self.user_id = get_machine_id()
        self._initialize()

    def _initialize(self):
        """Initialize the PostHog client if configured."""
        if not POSTHOG_AVAILABLE:
            logger.debug("PostHog library not available, skipping telemetry initialization")
            return

        config = get_hive_config().get("telemetry", {})
        self.enabled = config.get("enabled", False)
        
        if not self.enabled:
            return

        api_key = config.get("posthog_api_key")
        host = config.get("posthog_host", "https://app.posthog.com")

        if api_key:
            try:
                self.client = posthog.Posthog(
                    project_api_key=api_key,
                    host=host
                )
                # Disable capturing personal data by default
                self.client.disable_geoip() 
            except Exception as e:
                logger.warning(f"Failed to initialize PostHog client: {e}")
                self.enabled = False

    def capture(self, event_name: str, properties: dict[str, Any] | None = None) -> None:
        """
        Capture a telemetry event.

        Args:
            event_name: Name of the event
            properties: Dictionary of event properties
        """
        if not self.enabled or not self.client:
            return

        try:
            props = properties or {}
            
            # Add standard properties
            props.update({
                "os": platform.system(),
                "python_version": platform.python_version(),
                "$lib": "hive-framework",
            })

            self.client.capture(
                distinct_id=self.user_id,
                event=event_name,
                properties=props
            )
        except Exception as e:
            logger.debug(f"Failed to capture telemetry event: {e}")

    def shutdown(self):
        """Flush and close the client."""
        if self.client:
            try:
                self.client.shutdown()
            except Exception:
                pass


# Global singleton
_telemetry_client = None


def get_telemetry_client() -> TelemetryClient:
    """Get the global telemetry client instance."""
    global _telemetry_client
    if _telemetry_client is None:
        _telemetry_client = TelemetryClient()
    return _telemetry_client


def capture_event(event_name: str, properties: dict[str, Any] | None = None) -> None:
    """Helper function to capture an event using the global client."""
    try:
        client = get_telemetry_client()
        client.capture(event_name, properties)
    except Exception:
        # Never crash the application due to telemetry
        pass
