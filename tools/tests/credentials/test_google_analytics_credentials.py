"""Tests for Google Analytics credential spec."""

from aden_tools.credentials import CREDENTIAL_SPECS
from aden_tools.credentials.google_analytics import GOOGLE_ANALYTICS_CREDENTIALS


class TestGoogleAnalyticsCredentials:
    """Tests for the Google Analytics credential specification."""

    def test_credential_spec_exists(self):
        """google_analytics spec exists in the module."""
        assert "google_analytics" in GOOGLE_ANALYTICS_CREDENTIALS

    def test_credential_registered_in_global_specs(self):
        """google_analytics spec is merged into CREDENTIAL_SPECS."""
        assert "google_analytics" in CREDENTIAL_SPECS

    def test_env_var(self):
        """Spec points to the correct environment variable."""
        spec = GOOGLE_ANALYTICS_CREDENTIALS["google_analytics"]
        assert spec.env_var == "GOOGLE_APPLICATION_CREDENTIALS"

    def test_tools_list(self):
        """Spec lists all four GA tool names."""
        spec = GOOGLE_ANALYTICS_CREDENTIALS["google_analytics"]
        expected = [
            "ga_run_report",
            "ga_get_realtime",
            "ga_get_top_pages",
            "ga_get_traffic_sources",
        ]
        assert spec.tools == expected

    def test_required_flag(self):
        """Credential is required."""
        spec = GOOGLE_ANALYTICS_CREDENTIALS["google_analytics"]
        assert spec.required is True

    def test_not_startup_required(self):
        """Credential is not required at startup."""
        spec = GOOGLE_ANALYTICS_CREDENTIALS["google_analytics"]
        assert spec.startup_required is False

    def test_help_url_set(self):
        """Help URL points to GA4 quickstart docs."""
        spec = GOOGLE_ANALYTICS_CREDENTIALS["google_analytics"]
        assert "developers.google.com" in spec.help_url

    def test_description_set(self):
        """Description is non-empty."""
        spec = GOOGLE_ANALYTICS_CREDENTIALS["google_analytics"]
        assert spec.description
        assert "service account" in spec.description.lower()
