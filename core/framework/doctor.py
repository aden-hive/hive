"""Diagnostic tool for checking Hive setup.

Usage:
    hive doctor          - Run all diagnostic checks
    hive doctor --verify - Also health-check credentials via API calls
"""

from __future__ import annotations

import argparse
import os
import sys


def register_doctor_command(subparsers: argparse._SubParsersAction) -> None:
    """Register the doctor command with the main CLI."""
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run diagnostic checks on Hive setup",
        description="Check Python version, credentials, and dependencies.",
    )
    doctor_parser.add_argument(
        "--verify",
        action="store_true",
        help="Health-check credentials via live API calls (slower)",
    )
    doctor_parser.set_defaults(func=cmd_doctor)


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run diagnostic checks on Hive installation and configuration."""
    # Ensure stdout can handle emoji/Unicode on Windows subprocesses
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        import io

        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    verify = getattr(args, "verify", False)
    issues: list[str] = []

    print()
    print("🏥 Hive Doctor")
    print("=" * 60)

    # ── 1. Python version ────────────────────────────────────────
    print("\n🐍 Python version")
    v = sys.version_info
    if v >= (3, 11):
        print(f"   ✅ Python {v.major}.{v.minor}.{v.micro}")
    else:
        msg = f"Python {v.major}.{v.minor}.{v.micro} (need ≥ 3.11)"
        print(f"   ❌ {msg}")
        issues.append(msg)

    # ── 2. Credential key environment ────────────────────────────
    print("\n🔑 Credential environment")
    try:
        from framework.credentials.validation import ensure_credential_key_env

        ensure_credential_key_env()
    except Exception as exc:
        print(f"   ⚠️  Could not load credential env: {exc}")

    hive_key = bool(os.environ.get("HIVE_CREDENTIAL_KEY"))
    aden_key = bool(os.environ.get("ADEN_API_KEY"))
    print(f"   {'✅' if hive_key else '❌'} HIVE_CREDENTIAL_KEY {'set' if hive_key else 'not set'}")
    aden_status = "set" if aden_key else "not set (optional)"
    aden_icon = "✅" if aden_key else "⚠️ "
    print(f"   {aden_icon} ADEN_API_KEY {aden_status}")
    if not hive_key:
        issues.append("HIVE_CREDENTIAL_KEY not set")

    # ── 3. Credential checks ────────────────────────────────────
    print("\n📋 Credentials")
    try:
        from aden_tools.credentials import CREDENTIAL_SPECS, check_credential_health

        from framework.credentials.storage import (
            CompositeStorage,
            EncryptedFileStorage,
            EnvVarStorage,
        )
        from framework.credentials.store import CredentialStore

        # Build credential store (same logic as validate_agent_credentials)
        env_mapping = {
            (spec.credential_id or name): spec.env_var for name, spec in CREDENTIAL_SPECS.items()
        }
        env_storage = EnvVarStorage(env_mapping=env_mapping)
        if hive_key:
            storage = CompositeStorage(primary=env_storage, fallbacks=[EncryptedFileStorage()])
        else:
            storage = env_storage
        store = CredentialStore(storage=storage)

        ok_count = 0
        missing_count = 0
        invalid_count = 0

        for name, spec in sorted(CREDENTIAL_SPECS.items()):
            cred_id = spec.credential_id or name
            available = store.is_available(cred_id)

            if not available:
                missing_count += 1
                print(f"   ➖ {name:<28} not configured")
                continue

            # Credential is present — optionally health-check it
            if verify and spec.health_check_endpoint:
                value = store.get(cred_id)
                if value:
                    try:
                        result = check_credential_health(
                            name,
                            value,
                            health_check_endpoint=spec.health_check_endpoint,
                            health_check_method=spec.health_check_method,
                        )
                        if result.valid:
                            ok_count += 1
                            print(f"   ✅ {name:<28} valid — {result.message}")
                        else:
                            invalid_count += 1
                            print(f"   ❌ {name:<28} INVALID — {result.message}")
                            issues.append(f"{name}: {result.message}")
                    except Exception as exc:
                        ok_count += 1  # present, check failed — don't penalize
                        print(f"   ⚠️  {name:<28} present (check failed: {exc})")
                else:
                    ok_count += 1
                    print(f"   ✅ {name:<28} present")
            else:
                ok_count += 1
                print(f"   ✅ {name:<28} present")

        print(
            f"\n   Summary: {ok_count} present, {missing_count} not configured, "
            f"{invalid_count} invalid"
        )
        if invalid_count:
            issues.append(f"{invalid_count} credential(s) invalid")

    except ImportError:
        print("   ⚠️  aden_tools not installed — skipping credential checks")

    # ── 4. Core dependencies ─────────────────────────────────────
    print("\n📦 Core dependencies")
    deps = ["anthropic", "httpx", "litellm", "pydantic", "textual", "mcp"]
    for dep in deps:
        try:
            mod = __import__(dep)
            version = getattr(mod, "__version__", "?")
            print(f"   ✅ {dep:<20} {version}")
        except ImportError:
            print(f"   ❌ {dep:<20} not installed")
            issues.append(f"Missing dependency: {dep}")

    # ── Summary ──────────────────────────────────────────────────
    print()
    print("=" * 60)
    if not issues:
        print("✅ All checks passed! Hive is ready to use.")
    else:
        print(f"❌ Found {len(issues)} issue(s):")
        for issue in issues:
            print(f"   • {issue}")
        print("\nTo fix credentials: run 'hive setup-credentials <agent_path>'")
        print("                    or set env vars in your shell config.")
    print()

    return 1 if issues else 0
