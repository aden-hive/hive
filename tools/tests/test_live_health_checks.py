"""Live integration tests for credential health checkers.

These tests make REAL API calls. They are gated behind the ``live`` marker
and never run in CI.  Run them manually::

    pytest -m live -s --log-cli-level=INFO          # all live tests
    pytest -m live -k anthropic -s                  # just anthropic
    pytest -m live -k "not google" -s               # skip google variants
    pytest -m live --tb=short -q                    # quick summary

Prerequisites:
    - Credentials available via env vars or ~/.hive/credentials/ encrypted store
    - Tests skip gracefully when credentials are unavailable
    - Rate-limited responses (429) are treated as PASS (credential is valid)
"""

from __future__ import annotations

import logging

import pytest

from aden_tools.credentials import CREDENTIAL_SPECS
from aden_tools.credentials.health_check import (
    HEALTH_CHECKERS,
    check_credential_health,
    validate_integration_wiring,
)

logger = logging.getLogger(__name__)

# All credential names that have registered health checkers
CHECKER_NAMES = sorted(HEALTH_CHECKERS.keys())


def _redact(value: str) -> str:
    """Redact a credential for safe logging."""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-2:]}"


# ---------------------------------------------------------------------------
# 1. Direct checker tests
# ---------------------------------------------------------------------------


@pytest.mark.live
class TestLiveHealthCheckers:
    """Call each health checker against the real API."""

    @pytest.mark.parametrize("credential_name", CHECKER_NAMES, ids=CHECKER_NAMES)
    def test_checker_returns_valid(self, credential_name, live_credential_resolver):
        """Health checker returns valid=True with a real credential."""
        credential_value = live_credential_resolver(credential_name)
        if credential_value is None:
            spec = CREDENTIAL_SPECS.get(credential_name)
            env_var = spec.env_var if spec else "???"
            pytest.skip(f"No credential available ({env_var})")

        checker = HEALTH_CHECKERS[credential_name]
        result = checker.check(credential_value)

        logger.info(
            "Live check %s: valid=%s message=%r",
            credential_name,
            result.valid,
            result.message,
        )

        assert result.valid is True, (
            f"Health check for '{credential_name}' returned valid=False: "
            f"{result.message} (details: {result.details})"
        )
        assert result.message

    @pytest.mark.parametrize("credential_name", CHECKER_NAMES, ids=CHECKER_NAMES)
    def test_checker_extracts_identity(self, credential_name, live_credential_resolver):
        """Identity metadata (when present) contains non-empty strings."""
        credential_value = live_credential_resolver(credential_name)
        if credential_value is None:
            pytest.skip(f"No credential available for '{credential_name}'")

        checker = HEALTH_CHECKERS[credential_name]
        result = checker.check(credential_value)

        assert result.valid is True, (
            f"Cannot verify identity -- health check failed: {result.message}"
        )

        identity = result.details.get("identity", {})
        if identity:
            logger.info("Identity for %s: %s", credential_name, identity)
            for key, value in identity.items():
                assert isinstance(value, str), (
                    f"Identity key '{key}' is not a string: {type(value)}"
                )
                assert value, f"Identity key '{key}' is empty"
        else:
            logger.info("No identity metadata for %s (OK for some APIs)", credential_name)


# ---------------------------------------------------------------------------
# 2. Dispatcher path (check_credential_health)
# ---------------------------------------------------------------------------


@pytest.mark.live
class TestLiveDispatcher:
    """Verify the full check_credential_health() dispatch path."""

    @pytest.mark.parametrize("credential_name", CHECKER_NAMES, ids=CHECKER_NAMES)
    def test_dispatcher_returns_valid(self, credential_name, live_credential_resolver):
        """check_credential_health() returns valid=True via dispatcher."""
        credential_value = live_credential_resolver(credential_name)
        if credential_value is None:
            pytest.skip(f"No credential available for '{credential_name}'")

        result = check_credential_health(credential_name, credential_value)

        logger.info(
            "Dispatcher check %s: valid=%s message=%r",
            credential_name,
            result.valid,
            result.message,
        )

        assert result.valid is True, (
            f"Dispatcher check for '{credential_name}' returned valid=False: "
            f"{result.message} (details: {result.details})"
        )


# ---------------------------------------------------------------------------
# 3. Integration wiring verification
# ---------------------------------------------------------------------------


@pytest.mark.live
class TestLiveIntegrationWiring:
    """validate_integration_wiring() passes for every registered checker."""

    @pytest.mark.parametrize("credential_name", CHECKER_NAMES, ids=CHECKER_NAMES)
    def test_wiring_valid(self, credential_name):
        """No wiring issues for credentials with health checkers."""
        issues = validate_integration_wiring(credential_name)
        assert not issues, (
            f"Wiring issues for '{credential_name}':\n"
            + "\n".join(f"  - {i}" for i in issues)
        )


# ---------------------------------------------------------------------------
# 4. Summary reporter
# ---------------------------------------------------------------------------


@pytest.mark.live
class TestLiveCredentialSummary:
    """Print a human-readable summary of tested vs skipped credentials."""

    def test_credential_availability_summary(self, live_credential_resolver):
        """Report which credentials were available for live testing."""
        available = []
        skipped = []

        for name in CHECKER_NAMES:
            value = live_credential_resolver(name)
            spec = CREDENTIAL_SPECS.get(name)
            env_var = spec.env_var if spec else "???"
            if value:
                available.append((name, env_var))
            else:
                skipped.append((name, env_var))

        lines = [
            "",
            "=" * 60,
            "LIVE CREDENTIAL TEST SUMMARY",
            "=" * 60,
            f"  Available: {len(available)} / {len(CHECKER_NAMES)}",
            f"  Skipped:   {len(skipped)} / {len(CHECKER_NAMES)}",
            "",
        ]
        if available:
            lines.append("  TESTED:")
            for name, env_var in available:
                lines.append(f"    [PASS] {name} ({env_var})")
        if skipped:
            lines.append("")
            lines.append("  SKIPPED (no credential):")
            for name, env_var in skipped:
                lines.append(f"    [SKIP] {name} ({env_var})")
        lines.append("=" * 60)

        summary = "\n".join(lines)
        logger.info(summary)
        print(summary)  # noqa: T201  -- visible with pytest -s
