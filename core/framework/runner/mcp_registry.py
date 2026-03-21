"""MCP server registry: install tracking, version resolution, and upgrade safety."""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from framework.runner.mcp_manifest_schema import validate_manifest

REGISTRY_DIR = Path.home() / ".hive" / "mcp_registry"
INSTALLED_JSON = REGISTRY_DIR / "installed.json"


@dataclass
class ToolDiff:
    """Result of comparing old vs new tool lists."""

    added: list[str]  # new tools on server (non-breaking, info only)
    removed: list[str]  # tools gone from server (BREAKING)
    changed: list[str]  # same name but schema changed (BREAKING)
    unchanged: list[str]  # same name and schema

    @property
    def has_breaking_changes(self) -> bool:
        return bool(self.removed or self.changed)

    def format_report(self) -> str:
        """Format a human-readable diff report."""
        lines: list[str] = []
        for name in sorted(self.unchanged):
            lines.append(f"  PASS  {name}")
        for name in sorted(self.added):
            lines.append(f"  INFO  {name} (new tool)")
        for name in sorted(self.changed):
            lines.append(f"  FAIL  {name} (schema changed)")
        for name in sorted(self.removed):
            lines.append(f"  FAIL  {name} (removed)")
        return "\n".join(lines)


def _ensure_registry_dir() -> None:
    """Create ~/.hive/mcp_registry/ if it doesn't exist."""
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)


def read_installed() -> dict:
    """Read installed.json. Returns {} if file is missing or corrupt."""
    if not INSTALLED_JSON.exists():
        return {}
    try:
        return json.loads(INSTALLED_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_installed(data: dict) -> None:
    """Write installed.json atomically (write to temp file, then rename)."""
    _ensure_registry_dir()
    tmp = tempfile.NamedTemporaryFile(
        dir=REGISTRY_DIR, suffix=".tmp", delete=False, mode="w", encoding="utf-8"
    )
    try:
        json.dump(data, tmp, indent=2)
        tmp.close()
        Path(tmp.name).replace(INSTALLED_JSON)
    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        raise


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a dotted version string into a comparable tuple."""
    return tuple(int(x) for x in v.split("."))


def load_manifest(source: str | Path) -> dict:
    """Load and validate a manifest from a local directory or file path."""
    path = Path(source)
    if path.is_dir():
        path = path / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_manifest(data)
    if errors:
        raise ValueError(f"Invalid manifest: {'; '.join(errors)}")
    return data


def check_hive_compatibility(manifest: dict) -> list[str]:
    """Check hive.min_version/max_version against current Hive version."""
    hive_block = manifest.get("hive", {})
    min_ver = hive_block.get("min_version")
    max_ver = hive_block.get("max_version")
    if not min_ver and not max_ver:
        return []

    try:
        current = _parse_version(importlib.metadata.version("framework"))
    except importlib.metadata.PackageNotFoundError:
        return ["Could not determine current Hive version"]

    current_str = ".".join(str(x) for x in current)
    warnings: list[str] = []
    if min_ver and current < _parse_version(min_ver):
        warnings.append(f"Requires Hive >= {min_ver}, you have {current_str}")
    if max_ver and current > _parse_version(max_ver):
        warnings.append(f"Requires Hive <= {max_ver}, you have {current_str}")
    return warnings


def compare_tool_signatures(old_tools: list[dict], new_tools: list[dict]) -> ToolDiff:
    """Compare two tool lists by name and inputSchema. Returns a ToolDiff."""
    old_by_name = {t["name"]: t for t in old_tools}
    new_by_name = {t["name"]: t for t in new_tools}

    added = sorted(set(new_by_name) - set(old_by_name))
    removed = sorted(set(old_by_name) - set(new_by_name))

    changed = []
    unchanged = []
    for name in sorted(set(old_by_name) & set(new_by_name)):
        old_schema = old_by_name[name].get("inputSchema", {})
        new_schema = new_by_name[name].get("inputSchema", {})
        if old_schema != new_schema:
            changed.append(name)
        else:
            unchanged.append(name)

    return ToolDiff(added=added, removed=removed, changed=changed, unchanged=unchanged)


def resolve_agent_versions(registry_config: dict, installed: dict) -> list[str]:
    """Check agent version pins against installed versions. Returns error strings."""
    versions = registry_config.get("versions", {})
    errors: list[str] = []
    for name, pinned_ver in versions.items():
        if name not in installed:
            errors.append(
                f"Server '{name}' pinned to v{pinned_ver} but not installed."
                f" Fix: hive mcp install {name} --version {pinned_ver}"
            )
        elif installed[name].get("manifest_version") != pinned_ver:
            actual = installed[name].get("manifest_version", "unknown")
            errors.append(
                f"Server '{name}' pinned to v{pinned_ver} but v{actual} is installed."
                f" Fix: hive mcp install {name} --version {pinned_ver}"
            )
    return errors


def install_server(source: str | Path, version: str | None = None) -> dict:
    """Install an MCP server from a manifest directory."""
    manifest = load_manifest(source)
    name = manifest["name"]

    # Check Hive compatibility (VC-2)
    warnings = check_hive_compatibility(manifest)
    for w in warnings:
        print(f"Warning: {w}")

    # Determine package to install
    install_block = manifest.get("install", {})
    pkg = install_block.get("pip") or install_block.get("npm")
    if not pkg:
        raise ValueError(f"No installable package found in manifest for '{name}'")

    # Run pip install (VC-3)
    cmd = ["uv", "pip", "install"]
    if version:
        cmd.append(f"{pkg}=={version}")
    else:
        cmd.append(pkg)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Package install failed: {result.stderr.strip()}")

    # Build installed entry per PRD section 7.3
    entry = {
        "source": "local",
        "manifest_version": manifest["version"],
        "manifest": manifest,
        "installed_at": datetime.now(UTC).isoformat(),
        "installed_by": "hive mcp install",
        "transport": manifest["transport"]["default"],
        "enabled": True,
        "pinned": version is not None,  # FR-25: pinned when --version used
        "auto_update": False,
        "resolved_package_version": version or manifest["version"],  # VC-4
        "overrides": {"env": {}, "headers": {}},
    }

    # Write to installed.json (FR-20)
    installed = read_installed()
    installed[name] = entry
    write_installed(installed)

    return entry


def update_server(name: str, dry_run: bool = False) -> ToolDiff:
    """Update an installed server, checking for breaking changes (VC-5, VC-8)."""
    installed = read_installed()
    if name not in installed:
        raise ValueError(f"Server '{name}' is not installed")

    entry = installed[name]

    # Pinned servers refuse to update
    if entry.get("pinned"):
        raise ValueError(
            f"Server '{name}' is version-pinned."
            f" Unpin first: hive mcp config {name} --set pinned=false"
        )

    # Compare old tools vs new tools (VC-5, VC-9)
    old_tools = entry["manifest"]["tools"]
    new_manifest = entry["manifest"]  # placeholder: same manifest until remote registry exists
    new_tools = new_manifest["tools"]
    diff = compare_tool_signatures(old_tools, new_tools)

    # Dry run: just return the diff without applying (VC-8)
    if dry_run:
        return diff

    if diff.has_breaking_changes:
        print(f"Warning: {len(diff.removed)} removed, {len(diff.changed)} changed tools")

    # Update the entry
    entry["manifest"] = new_manifest
    entry["manifest_version"] = new_manifest["version"]
    entry["installed_at"] = datetime.now(UTC).isoformat()
    installed[name] = entry
    write_installed(installed)

    return diff
