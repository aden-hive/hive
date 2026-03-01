import unittest
from unittest.mock import MagicMock, patch
from framework.observability.telemetry import capture_event, TelemetryClient

class TestTelemetry(unittest.TestCase):
    def test_capture_event_no_crash(self):
        """Ensure capture_event doesn't crash even if client fails."""
        with patch('framework.observability.telemetry.get_telemetry_client') as mock_get:
            mock_client = MagicMock()
            mock_client.capture.side_effect = Exception("PostHog failed")
            mock_get.return_value = mock_client
            
            # Should not raise exception
            capture_event("test_event", {"prop": "val"})
            mock_client.capture.assert_called_once()

    def test_telemetry_disabled_by_default(self):
        """Ensure telemetry is disabled if no config exists."""
        with patch('framework.observability.telemetry.get_hive_config') as mock_config:
            mock_config.return_value = {}
            client = TelemetryClient()
            self.assertFalse(client.enabled)
            self.assertIsNone(client.client)

if __name__ == "__main__":
    unittest.main()
