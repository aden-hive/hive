"""Diagnostic tool for checking Hive setup.

Provides the ``hive doctor`` command that verifies:

- LLM provider credentials are present and properly formatted.
- Python version meets the minimum requirement (3.11+).
- Core dependencies are importable.

This helps new users quickly diagnose configuration issues instead of
encountering cryptic runtime errors.

Resolves: https://github.com/aden-hive/hive/issues/4391

Usage::

    hive doctor           # Check all providers and dependencies
    hive doctor --fix     # Attempt automatic fixes (e.g., suggest exports)
"""

from __future__ import annotations

import sys


def run_doctor(fix: bool = False) -> int:
    """Check Hive installation and configuration.

    Runs a series of diagnostic checks and prints a summary indicating
    which items pass and which require attention.

    Args:
        fix: If True, print suggested fix commands for each issue.

    Returns:
        Exit code: 0 if all checks pass, 1 if any issue was found.
    """
    print("🏥 Running Hive Doctor...\n")

    issues_found: list[str] = []

    # ── 1. Check credentials ──────────────────────────────────────────
    _check_credentials(issues_found)

    # ── 2. Check Python version ───────────────────────────────────────
    _check_python_version(issues_found)

    # ── 3. Check core dependencies ────────────────────────────────────
    _check_dependencies(issues_found)

    # ── Summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if not issues_found:
        print("✅ All checks passed! Hive is ready to use.")
        return 0
    else:
        print(f"❌ Found {len(issues_found)} issue(s). See details above.")
        if fix:
            print("\n🔧 Suggested fixes:")
            for suggestion in issues_found:
                print(f"  • {suggestion}")
        else:
            print("\nRun with --fix to see suggested fixes.")
        return 1


def _check_credentials(issues: list[str]) -> None:
    """Check LLM provider credentials for presence and basic validity.

    Args:
        issues: Mutable list to append fix suggestions to.
    """
    from framework.credentials.validator import CredentialValidator

    print("📋 Checking credentials...")
    for provider, config in CredentialValidator.PROVIDERS.items():
        error = CredentialValidator.validate(provider)
        if error is None:
            print(f"  ✅ {config['display_name']}: OK")
        elif error.error_type == "missing":
            print(f"  ⚠️  {config['display_name']}: NOT SET")
            issues.append(
                f"Set {config['env_var']} — "
                f"get a key at {config['console_url']}"
            )
        else:
            print(f"  ❌ {config['display_name']}: {error.error_type.upper()}")
            issues.append(
                f"Fix {config['env_var']} — "
                f"{error.error_type} (see {config['console_url']})"
            )


def _check_python_version(issues: list[str]) -> None:
    """Verify the Python version meets the minimum requirement.

    Args:
        issues: Mutable list to append fix suggestions to.
    """
    print("\n🐍 Checking Python version...")
    major, minor = sys.version_info.major, sys.version_info.minor
    if (major, minor) >= (3, 11):
        print(f"  ✅ Python {major}.{minor}")
    else:
        print(f"  ❌ Python {major}.{minor} (need 3.11+)")
        issues.append(
            "Upgrade to Python 3.11+: "
            "https://www.python.org/downloads/"
        )


def _check_dependencies(issues: list[str]) -> None:
    """Verify that core Hive dependencies are importable.

    Args:
        issues: Mutable list to append fix suggestions to.
    """
    print("\n📦 Checking dependencies...")

    deps = [
        ("litellm", "LiteLLM (LLM provider)"),
        ("pydantic", "Pydantic (data models)"),
    ]

    for module_name, label in deps:
        try:
            __import__(module_name)
            print(f"  ✅ {label}")
        except ImportError:
            print(f"  ❌ {label}: NOT INSTALLED")
            issues.append(f"Install {module_name}: pip install {module_name}")

    # Optional dependencies — warn but don't count as issues
    optional_deps = [
        ("textual", "Textual (TUI dashboard)"),
        ("httpx", "httpx (Aden sync)"),
    ]

    print("\n📦 Checking optional dependencies...")
    for module_name, label in optional_deps:
        try:
            __import__(module_name)
            print(f"  ✅ {label}")
        except ImportError:
            print(f"  ⚠️  {label}: not installed (optional)")
