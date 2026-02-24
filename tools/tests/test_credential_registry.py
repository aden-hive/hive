"""Tests that enforce credential registry completeness and consistency.

These tests run in CI and catch common mistakes when adding new integrations:
- Missing health checker for a spec with health_check_endpoint
- Orphaned entries in HEALTH_CHECKERS (no corresponding spec)
- CredentialSpec fields that are incomplete
- Duplicate env var conflicts
"""

import pytest

from aden_tools.credentials import CREDENTIAL_SPECS
from aden_tools.credentials.health_check import HEALTH_CHECKERS, validate_integration_wiring


class TestRegistryCompleteness:
    """Every credential with a health_check_endpoint must have a registered checker."""

    # Credentials that intentionally don't have their own dedicated checker:
    # - google_cse: shares google_search checker (same credential_group)
    # - razorpay/razorpay_secret: requires HTTP Basic auth with TWO credentials,
    #   which the single-value health check dispatcher can't support
    KNOWN_EXCEPTIONS = {"google_cse", "razorpay", "razorpay_secret"}

    def test_specs_with_endpoint_have_checkers(self):
        """Every CredentialSpec with health_check_endpoint has a HEALTH_CHECKERS entry."""
        missing = []
        for name, spec in CREDENTIAL_SPECS.items():
            if name in self.KNOWN_EXCEPTIONS:
                continue
            if spec.health_check_endpoint and name not in HEALTH_CHECKERS:
                missing.append(
                    f"{name}: has endpoint '{spec.health_check_endpoint}' "
                    f"but no dedicated health checker"
                )
        assert not missing, (
            f"{len(missing)} credential(s) have health_check_endpoint but no checker:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_checkers_have_corresponding_specs(self):
        """Every key in HEALTH_CHECKERS matches a CREDENTIAL_SPECS entry."""
        orphaned = [name for name in HEALTH_CHECKERS if name not in CREDENTIAL_SPECS]
        assert not orphaned, f"HEALTH_CHECKERS has entries with no CREDENTIAL_SPECS: {orphaned}"


class TestSpecRequiredFields:
    """Every CredentialSpec should have minimum required fields."""

    @pytest.mark.parametrize(
        "cred_name,spec",
        list(CREDENTIAL_SPECS.items()),
        ids=list(CREDENTIAL_SPECS.keys()),
    )
    def test_has_env_var(self, cred_name, spec):
        assert spec.env_var, f"{cred_name}: missing env_var"

    @pytest.mark.parametrize(
        "cred_name,spec",
        list(CREDENTIAL_SPECS.items()),
        ids=list(CREDENTIAL_SPECS.keys()),
    )
    def test_has_description(self, cred_name, spec):
        assert spec.description, f"{cred_name}: missing description"

    @pytest.mark.parametrize(
        "cred_name,spec",
        list(CREDENTIAL_SPECS.items()),
        ids=list(CREDENTIAL_SPECS.keys()),
    )
    def test_has_tools_or_node_types(self, cred_name, spec):
        assert spec.tools or spec.node_types, (
            f"{cred_name}: must have at least one tool or node_type"
        )


class TestNoDuplicateEnvVars:
    """No two credential specs should use the same env_var (unless in same credential_group)."""

    def test_no_accidental_env_var_collisions(self):
        seen: dict[str, list[str]] = {}
        for name, spec in CREDENTIAL_SPECS.items():
            seen.setdefault(spec.env_var, []).append(name)

        duplicates = {}
        for env_var, names in seen.items():
            if len(names) <= 1:
                continue
            # Filter out intentional duplicates (same credential_group)
            groups = {CREDENTIAL_SPECS[n].credential_group for n in names}
            if len(groups) == 1 and groups != {""}:
                continue  # All share the same non-empty group -- intentional
            duplicates[env_var] = names

        assert not duplicates, f"Duplicate env_vars across unrelated credentials: {duplicates}"


class TestIntegrationWiring:
    """validate_integration_wiring() catches wiring issues."""

    def test_nonexistent_credential(self):
        issues = validate_integration_wiring("nonexistent_service_xyz")
        assert any("No CredentialSpec" in i for i in issues)

    def test_known_credential_no_critical_issues(self):
        """A well-wired credential (e.g. 'hubspot') should have no issues."""
        issues = validate_integration_wiring("hubspot")
        assert not issues, f"Unexpected issues for hubspot: {issues}"

    @pytest.mark.parametrize("cred_name", list(HEALTH_CHECKERS.keys()))
    def test_all_checkers_pass_wiring(self, cred_name):
        """Every registered checker should pass wiring validation."""
        issues = validate_integration_wiring(cred_name)
        assert not issues, f"Wiring issues for '{cred_name}':\n" + "\n".join(
            f"  - {i}" for i in issues
        )
