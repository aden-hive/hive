"""CLI commands for the Hive skill system (CLI-1 through CLI-13).

Commands:
  hive skill list             — list discovered skills (all scopes)
  hive skill install          — install from registry or git URL
  hive skill remove           — uninstall a skill
  hive skill info             — show skill details
  hive skill init             — scaffold a new SKILL.md
  hive skill validate         — strict-validate a SKILL.md
  hive skill doctor           — health-check skills / default skills
  hive skill update           — refresh registry cache or re-install a skill
  hive skill search           — search registry by name/tag/description
  hive skill fork             — create local editable copy of a skill
  hive skill trust            — permanently trust a project repo's skills
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_SKILL_MD_TEMPLATE = """\
---
name: {name}
description: <One-sentence description of what this skill does and when to use it.>
version: 0.1.0
license: MIT
author: ""
compatibility:
  - claude-code
  - hive
metadata:
  tags: []
# allowed-tools:
#   - tool_name
---

## Instructions

Describe what the agent should do when this skill is activated.

### When to Use This Skill

Describe the conditions under which the agent should activate this skill.

### Step-by-Step Protocol

1. First, ...
2. Then, ...
3. Finally, ...

### Output Format

Describe the expected output format or deliverable.
"""


def register_skill_commands(subparsers) -> None:
    """Register the ``hive skill`` subcommand group."""
    skill_parser = subparsers.add_parser("skill", help="Manage skills")
    skill_sub = skill_parser.add_subparsers(dest="skill_command", required=True)

    # hive skill list
    list_parser = skill_sub.add_parser("list", help="List discovered skills across all scopes")
    list_parser.add_argument(
        "--project-dir",
        default=None,
        metavar="PATH",
        help="Project directory to scan (default: current directory)",
    )
    list_parser.set_defaults(func=cmd_skill_list)

    # hive skill install
    install_parser = skill_sub.add_parser(
        "install",
        help="Install a skill from the registry or a git URL",
    )
    install_parser.add_argument(
        "name_or_url",
        nargs="?",
        help="Skill name (from registry) or git URL",
    )
    install_parser.add_argument(
        "--version",
        default=None,
        metavar="REF",
        help="Git ref (branch/tag) to install",
    )
    install_parser.add_argument(
        "--from",
        dest="from_url",
        default=None,
        metavar="URL",
        help="Install from this git URL directly",
    )
    install_parser.add_argument(
        "--pack",
        default=None,
        metavar="PACK",
        help="Install a starter pack by name",
    )
    install_parser.add_argument(
        "--name",
        dest="install_name",
        default=None,
        metavar="NAME",
        help="Override the skill directory name on install",
    )
    install_parser.set_defaults(func=cmd_skill_install)

    # hive skill remove
    remove_parser = skill_sub.add_parser("remove", help="Uninstall a skill")
    remove_parser.add_argument("name", help="Skill name to remove")
    remove_parser.set_defaults(func=cmd_skill_remove)

    # hive skill info
    info_parser = skill_sub.add_parser("info", help="Show skill details")
    info_parser.add_argument("name", help="Skill name")
    info_parser.add_argument(
        "--project-dir",
        default=None,
        metavar="PATH",
        help="Project directory to scan (default: current directory)",
    )
    info_parser.set_defaults(func=cmd_skill_info)

    # hive skill init
    init_parser = skill_sub.add_parser(
        "init", help="Scaffold a new skill directory with a SKILL.md template"
    )
    init_parser.add_argument("--name", dest="skill_name", default=None, metavar="NAME")
    init_parser.add_argument(
        "--dir",
        dest="target_dir",
        default=None,
        metavar="PATH",
        help="Parent directory for the new skill (default: current directory)",
    )
    init_parser.set_defaults(func=cmd_skill_init)

    # hive skill validate
    validate_parser = skill_sub.add_parser(
        "validate", help="Strictly validate a SKILL.md against the Agent Skills spec"
    )
    validate_parser.add_argument("path", help="Path to SKILL.md or its parent directory")
    validate_parser.set_defaults(func=cmd_skill_validate)

    # hive skill doctor
    doctor_parser = skill_sub.add_parser(
        "doctor", help="Health-check skills (parseable, scripts executable, tools available)"
    )
    doctor_parser.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Skill name to check (default: all discovered skills)",
    )
    doctor_parser.add_argument(
        "--defaults",
        action="store_true",
        help="Check all 6 framework default skills",
    )
    doctor_parser.add_argument(
        "--project-dir",
        default=None,
        metavar="PATH",
    )
    doctor_parser.set_defaults(func=cmd_skill_doctor)

    # hive skill update
    update_parser = skill_sub.add_parser(
        "update",
        help="Refresh registry cache or re-install a specific skill",
    )
    update_parser.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Skill name to update (default: refresh registry cache only)",
    )
    update_parser.set_defaults(func=cmd_skill_update)

    # hive skill search
    search_parser = skill_sub.add_parser(
        "search", help="Search the skill registry by name, tag, or description"
    )
    search_parser.add_argument("query", help="Search query string")
    search_parser.set_defaults(func=cmd_skill_search)

    # hive skill fork
    fork_parser = skill_sub.add_parser("fork", help="Create a local editable copy of a skill")
    fork_parser.add_argument("name", help="Skill name to fork")
    fork_parser.add_argument(
        "--name",
        dest="new_name",
        default=None,
        metavar="NEW_NAME",
        help="Name for the forked skill (default: <name>-fork)",
    )
    fork_parser.add_argument(
        "--dir",
        dest="target_dir",
        default=None,
        metavar="PATH",
        help="Parent directory for the fork (default: ~/.hive/skills/)",
    )
    fork_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    fork_parser.add_argument(
        "--project-dir",
        default=None,
        metavar="PATH",
    )
    fork_parser.set_defaults(func=cmd_skill_fork)

    # hive skill trust
    trust_parser = skill_sub.add_parser(
        "trust",
        help="Permanently trust a project repository so its skills load without prompting",
    )
    trust_parser.add_argument(
        "project_path",
        help="Path to the project directory (must contain a .git with a remote origin)",
    )
    trust_parser.set_defaults(func=cmd_skill_trust)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def cmd_skill_list(args) -> int:
    """List all discovered skills grouped by scope."""
    from framework.skills.discovery import DiscoveryConfig, SkillDiscovery

    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    skills = SkillDiscovery(DiscoveryConfig(project_root=project_dir)).discover()

    if not skills:
        print("No skills discovered.")
        return 0

    scope_headers = {
        "project": "PROJECT SKILLS",
        "user": "USER SKILLS",
        "framework": "FRAMEWORK SKILLS",
    }

    for scope in ("project", "user", "framework"):
        scope_skills = [s for s in skills if s.source_scope == scope]
        if not scope_skills:
            continue
        print(f"\n{scope_headers[scope]}")
        print("─" * 40)
        for skill in scope_skills:
            print(f"  • {skill.name}")
            print(f"    {skill.description}")
            print(f"    {skill.location}")

    return 0


def cmd_skill_install(args) -> int:
    """Install a skill from the registry or a git URL."""
    from framework.skills.installer import (
        USER_SKILLS_DIR,
        install_from_git,
        install_from_registry,
        maybe_show_install_notice,
    )
    from framework.skills.registry import RegistryClient
    from framework.skills.skill_errors import SkillError

    maybe_show_install_notice()
    sys.stdout.flush()

    target_dir = USER_SKILLS_DIR

    # hive skill install --pack <name>
    if args.pack:
        return _install_pack(args.pack, target_dir, args.version)

    # hive skill install --from <url> [--name <name>]
    if args.from_url:
        skill_name = args.install_name or _derive_name_from_url(args.from_url)
        print(f"Installing '{skill_name}' from {args.from_url} ...", flush=True)
        try:
            dest = install_from_git(
                git_url=args.from_url,
                skill_name=skill_name,
                version=args.version,
                target_dir=target_dir,
            )
        except SkillError as exc:
            print(f"Error: {exc.what}", file=sys.stderr)
            print(f"  Why: {exc.why}", file=sys.stderr)
            print(f"  Fix: {exc.fix}", file=sys.stderr)
            return 1
        print(f"✓ Installed: {skill_name}")
        print(f"  Location: {dest}")
        return 0

    # hive skill install <name>  (registry lookup)
    if args.name_or_url:
        name = args.install_name or args.name_or_url
        client = RegistryClient()
        entry = client.get_skill_entry(args.name_or_url)
        if entry is None:
            print(
                f"Error: skill '{args.name_or_url}' not found in registry.",
                file=sys.stderr,
            )
            print(
                "  The registry may be unavailable, or the skill name is incorrect.",
                file=sys.stderr,
            )
            print(
                "  Install from a git URL directly: hive skill install --from <url>",
                file=sys.stderr,
            )
            return 1
        print(f"Installing '{name}' from registry ...")
        try:
            dest = install_from_registry(entry, target_dir=target_dir, version=args.version)
        except SkillError as exc:
            print(f"Error: {exc.what}", file=sys.stderr)
            print(f"  Why: {exc.why}", file=sys.stderr)
            print(f"  Fix: {exc.fix}", file=sys.stderr)
            return 1
        print(f"✓ Installed: {name}")
        print(f"  Location: {dest}")
        return 0

    print("Error: specify a skill name, --from <url>, or --pack <name>.", file=sys.stderr)
    print("  Usage: hive skill install <name>", file=sys.stderr)
    print("         hive skill install --from <git-url>", file=sys.stderr)
    print("         hive skill install --pack <pack-name>", file=sys.stderr)
    return 1


def cmd_skill_remove(args) -> int:
    """Uninstall a skill from ~/.hive/skills/."""
    from framework.skills.installer import remove_skill
    from framework.skills.skill_errors import SkillError

    try:
        removed = remove_skill(args.name)
    except SkillError as exc:
        print(f"Error: {exc.what}", file=sys.stderr)
        print(f"  Why: {exc.why}", file=sys.stderr)
        print(f"  Fix: {exc.fix}", file=sys.stderr)
        return 1

    if not removed:
        print(f"Error: skill '{args.name}' not found in ~/.hive/skills/.", file=sys.stderr)
        print("  Use 'hive skill list' to see installed skills.", file=sys.stderr)
        return 1

    print(f"✓ Removed: {args.name}")
    return 0


def cmd_skill_info(args) -> int:
    """Show details for a skill by name."""
    from framework.skills.discovery import DiscoveryConfig, SkillDiscovery
    from framework.skills.registry import RegistryClient

    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    skills = SkillDiscovery(DiscoveryConfig(project_root=project_dir)).discover()
    match = next((s for s in skills if s.name == args.name), None)

    if match:
        print(f"\n{match.name}")
        print("─" * 40)
        print(f"  Description:   {match.description}")
        print(f"  Scope:         {match.source_scope}")
        print(f"  Location:      {match.location}")
        if match.license:
            print(f"  License:       {match.license}")
        if match.compatibility:
            print(f"  Compatibility: {', '.join(match.compatibility)}")
        if match.allowed_tools:
            print(f"  Allowed tools: {', '.join(match.allowed_tools)}")
        if match.metadata:
            tags = match.metadata.get("tags", [])
            if tags:
                print(f"  Tags:          {', '.join(str(t) for t in tags)}")
        # List scripts and references if present
        base = Path(match.base_dir)
        for sub in ("scripts", "references", "assets"):
            sub_dir = base / sub
            if sub_dir.is_dir():
                files = sorted(f.name for f in sub_dir.iterdir() if f.is_file())
                if files:
                    print(f"  {sub.capitalize():13s}: {', '.join(files)}")
        return 0

    # Not installed locally — try registry
    client = RegistryClient()
    entry = client.get_skill_entry(args.name)
    if entry:
        print(f"\n{entry.get('name', args.name)}  (not installed)")
        print("─" * 40)
        print(f"  Description:   {entry.get('description', '')}")
        print(f"  Version:       {entry.get('version', 'unknown')}")
        print(f"  Author:        {entry.get('author', 'unknown')}")
        print(f"  Trust tier:    {entry.get('trust_tier', 'community')}")
        if entry.get("license"):
            print(f"  License:       {entry['license']}")
        if entry.get("tags"):
            print(f"  Tags:          {', '.join(entry['tags'])}")
        print(f"\n  Install with: hive skill install {args.name}")
        return 0

    print(f"Error: skill '{args.name}' not found locally or in registry.", file=sys.stderr)
    return 1


def cmd_skill_init(args) -> int:
    """Scaffold a new skill directory with a SKILL.md template."""
    name = args.skill_name
    if not name:
        # Prompt interactively if not provided
        if sys.stdin.isatty():
            name = input("Skill name (e.g. my-research-skill): ").strip()
        if not name:
            print("Error: provide a skill name with --name <name>.", file=sys.stderr)
            return 1

    parent = Path(args.target_dir).resolve() if args.target_dir else Path.cwd()
    skill_dir = parent / name

    if skill_dir.exists():
        print(f"Error: directory already exists: {skill_dir}", file=sys.stderr)
        print(
            "  Choose a different --name or use --dir to place it elsewhere.",
            file=sys.stderr,
        )
        return 1

    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(_SKILL_MD_TEMPLATE.format(name=name), encoding="utf-8")

    print(f"✓ Created: {skill_md}")
    print("  Next steps:")
    print("  1. Edit SKILL.md — fill in description and instructions")
    print(f"  2. Run: hive skill validate {skill_md}")
    print(f"  3. Move to ~/.hive/skills/{name}/ to make it available to all agents")
    return 0


def cmd_skill_validate(args) -> int:
    """Strictly validate a SKILL.md against the Agent Skills spec."""
    from framework.skills.validator import validate_strict

    path = Path(args.path)
    # Accept either the file or its parent directory
    if path.is_dir():
        path = path / "SKILL.md"

    result = validate_strict(path)

    for warning in result.warnings:
        print(f"  [WARN]  {warning}")
    for error in result.errors:
        print(f"  [ERROR] {error}")

    if result.passed:
        if not result.warnings:
            print(f"✓ {path} — valid")
        else:
            print(f"✓ {path} — valid ({len(result.warnings)} warning(s))")
        return 0
    else:
        print(
            f"✗ {path} — invalid ({len(result.errors)} error(s), {len(result.warnings)} warning(s))"
        )
        return 1


def cmd_skill_doctor(args) -> int:
    """Health-check skills: parseable, scripts executable, tools available."""
    from framework.skills.defaults import _DEFAULT_SKILLS_DIR, SKILL_REGISTRY
    from framework.skills.discovery import DiscoveryConfig, SkillDiscovery
    from framework.skills.parser import parse_skill_md

    overall_errors = 0

    if args.defaults:
        print("\nFRAMEWORK DEFAULT SKILLS")
        print("─" * 40)
        for skill_name, dir_name in SKILL_REGISTRY.items():
            skill_md = _DEFAULT_SKILLS_DIR / dir_name / "SKILL.md"
            overall_errors += _doctor_skill_file(skill_name, skill_md, parse_skill_md)
        return 0 if overall_errors == 0 else 1

    # Discover skills for doctor
    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    skills = SkillDiscovery(DiscoveryConfig(project_root=project_dir)).discover()

    if args.name:
        skills = [s for s in skills if s.name == args.name]
        if not skills:
            # Skill failed to parse (e.g. missing description) — look for the file directly
            from framework.skills.installer import USER_SKILLS_DIR

            candidate = USER_SKILLS_DIR / args.name / "SKILL.md"
            if candidate.exists():
                print(f"\nChecking skill: {args.name}  [user]")
                overall_errors += _doctor_skill_file(args.name, candidate, parse_skill_md)
                print()
                print(f"✗ {overall_errors} error(s) found.")
                return 1
            print(f"Error: skill '{args.name}' not found.", file=sys.stderr)
            return 1

    if not skills:
        print("No skills discovered.")
        return 0

    for skill in skills:
        print(f"\nChecking skill: {skill.name}  [{skill.source_scope}]")
        overall_errors += _doctor_skill_file(skill.name, Path(skill.location), parse_skill_md)

    print()
    if overall_errors == 0:
        print("✓ All skills healthy.")
    else:
        print(f"✗ {overall_errors} error(s) found.")
    return 0 if overall_errors == 0 else 1


def cmd_skill_update(args) -> int:
    """Refresh registry cache or re-install a specific skill."""
    from framework.skills.installer import (
        USER_SKILLS_DIR,
        install_from_registry,
        remove_skill,
    )
    from framework.skills.registry import RegistryClient
    from framework.skills.skill_errors import SkillError

    client = RegistryClient()

    if not args.name:
        # Refresh cache only
        print("Refreshing registry cache ...")
        index = client.fetch_index(force_refresh=True)
        if index is None:
            print("Warning: registry unavailable — could not refresh cache.", file=sys.stderr)
            return 0  # Non-fatal
        count = len(index.get("skills", []))
        print(f"✓ Registry cache updated ({count} skills).")
        return 0

    # Update a specific skill
    entry = client.get_skill_entry(args.name)
    if entry is None:
        print(
            f"Error: skill '{args.name}' not found in registry — cannot update.",
            file=sys.stderr,
        )
        print("  Check your network connection or verify the skill name.", file=sys.stderr)
        return 1

    registry_version = entry.get("version")
    installed_dir = USER_SKILLS_DIR / args.name
    installed_skill_md = installed_dir / "SKILL.md"

    if installed_skill_md.exists():
        # Check installed version
        import yaml

        try:
            content = installed_skill_md.read_text(encoding="utf-8")
            parts = content.split("---", 2)
            fm = yaml.safe_load(parts[1]) if len(parts) >= 3 else {}
            installed_version = fm.get("version") if isinstance(fm, dict) else None
        except Exception:
            installed_version = None

        if installed_version and installed_version == registry_version:
            print(f"✓ '{args.name}' is already at version {registry_version}.")
            return 0

        if not installed_version:
            print(
                f"Warning: installed skill '{args.name}' has no version field — "
                "cannot compare. Re-installing.",
                file=sys.stderr,
            )

    # Remove and reinstall
    print(f"Updating '{args.name}' ...")
    try:
        remove_skill(args.name)
        dest = install_from_registry(entry, target_dir=USER_SKILLS_DIR)
    except SkillError as exc:
        print(f"Error: {exc.what}", file=sys.stderr)
        print(f"  Why: {exc.why}", file=sys.stderr)
        print(f"  Fix: {exc.fix}", file=sys.stderr)
        return 1

    new_version = registry_version or "unknown"
    print(f"✓ Updated '{args.name}' to version {new_version}.")
    print(f"  Location: {dest}")
    return 0


def cmd_skill_search(args) -> int:
    """Search the skill registry by name, tag, or description."""
    from framework.skills.registry import RegistryClient

    client = RegistryClient()
    # Trigger a fetch to check availability
    index = client.fetch_index()
    if index is None:
        print(
            f"Error: registry unavailable — cannot search for '{args.query}'.",
            file=sys.stderr,
        )
        print(
            "  Install from a git URL directly: hive skill install --from <url>",
            file=sys.stderr,
        )
        return 1

    results = client.search(args.query)
    if not results:
        print(f"No skills found matching '{args.query}'.")
        return 0

    print(f"\n{len(results)} result(s) for '{args.query}':\n")
    for entry in results:
        name = entry.get("name", "")
        tier = entry.get("trust_tier", "community")
        description = entry.get("description", "")
        print(f"  • {name}  [{tier}]")
        print(f"    {description}")
        print()
    return 0


def cmd_skill_fork(args) -> int:
    """Create a local editable copy of a skill."""
    from framework.skills.discovery import DiscoveryConfig, SkillDiscovery
    from framework.skills.installer import USER_SKILLS_DIR, fork_skill
    from framework.skills.skill_errors import SkillError

    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    skills = SkillDiscovery(DiscoveryConfig(project_root=project_dir)).discover()
    source = next((s for s in skills if s.name == args.name), None)

    if source is None:
        print(f"Error: skill '{args.name}' not found.", file=sys.stderr)
        print("  Use 'hive skill list' to see available skills.", file=sys.stderr)
        return 1

    new_name = args.new_name or f"{args.name}-fork"
    target_dir = Path(args.target_dir).resolve() if args.target_dir else USER_SKILLS_DIR
    dest = target_dir / new_name

    if not args.yes:
        answer = _prompt_yes_no(f"Fork '{args.name}' to {dest}? [y/N] ")
        if not answer:
            print("Aborted.")
            return 0

    try:
        result = fork_skill(source, new_name, target_dir)
    except SkillError as exc:
        print(f"Error: {exc.what}", file=sys.stderr)
        print(f"  Why: {exc.why}", file=sys.stderr)
        print(f"  Fix: {exc.fix}", file=sys.stderr)
        return 1

    print(f"✓ Forked '{args.name}' → '{new_name}'")
    print(f"  Location: {result}")
    print("  Edit SKILL.md to customise, then run: hive skill validate")
    return 0


def cmd_skill_trust(args) -> int:
    """Permanently trust a project repository's skills."""
    from framework.skills.trust import TrustedRepoStore, _normalize_remote_url

    project_path = Path(args.project_path).resolve()

    if not project_path.exists():
        print(f"Error: path does not exist: {project_path}", file=sys.stderr)
        return 1

    if not (project_path / ".git").exists():
        print(
            f"Error: {project_path} is not a git repository (no .git directory).",
            file=sys.stderr,
        )
        return 1

    try:
        result = subprocess.run(
            ["git", "-C", str(project_path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            print(
                "Error: no remote 'origin' configured in this repository.",
                file=sys.stderr,
            )
            return 1
        remote_url = result.stdout.strip()
    except subprocess.TimeoutExpired:
        print("Error: git remote lookup timed out.", file=sys.stderr)
        return 1
    except (FileNotFoundError, OSError) as e:
        print(f"Error reading git remote: {e}", file=sys.stderr)
        return 1

    repo_key = _normalize_remote_url(remote_url)
    store = TrustedRepoStore()
    store.trust(repo_key, project_path=str(project_path))

    print(f"✓ Trusted: {repo_key}")
    print("  Stored in ~/.hive/trusted_repos.json")
    print("  Skills from this repository will load without prompting in future runs.")
    return 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _install_pack(pack_name: str, target_dir: Path, version: str | None) -> int:
    """Install all skills in a registry starter pack."""
    from framework.skills.installer import install_from_registry
    from framework.skills.registry import RegistryClient
    from framework.skills.skill_errors import SkillError

    client = RegistryClient()
    skill_names = client.get_pack(pack_name)

    if skill_names is None:
        print(f"Error: pack '{pack_name}' not found in registry.", file=sys.stderr)
        print(
            "  The registry may be unavailable. Check your network connection.",
            file=sys.stderr,
        )
        return 1

    if not skill_names:
        print(f"Warning: pack '{pack_name}' contains no skills.", file=sys.stderr)
        return 0

    print(f"Installing pack '{pack_name}' ({len(skill_names)} skills) ...")
    errors = 0
    for name in skill_names:
        entry = client.get_skill_entry(name)
        if not entry:
            print(f"  ✗ {name} — not found in registry, skipping", file=sys.stderr)
            errors += 1
            continue
        try:
            dest = install_from_registry(entry, target_dir=target_dir, version=version)
            print(f"  ✓ {name} → {dest}")
        except SkillError as exc:
            print(f"  ✗ {name} — {exc.why}", file=sys.stderr)
            errors += 1

    print()
    if errors == 0:
        print(f"✓ Pack '{pack_name}' installed successfully.")
    else:
        print(f"✗ Pack install completed with {errors} error(s).")
    return 0 if errors == 0 else 1


def _derive_name_from_url(url: str) -> str:
    """Derive a skill directory name from a git URL.

    github.com/org/deep-research.git → deep-research
    github.com/org/skills            → skills
    """
    last = url.rstrip("/").split("/")[-1]
    return last[:-4] if last.endswith(".git") else last


def _doctor_skill_file(skill_name: str, skill_md: Path, parse_fn) -> int:
    """Run doctor checks on a single skill file. Returns error count."""
    errors = 0

    # Check 1: SKILL.md parseable
    parsed = parse_fn(skill_md)
    if parsed is None:
        print(f"  ✗ SKILL.md not parseable: {skill_md}")
        errors += 1
        return errors
    print("  ✓ SKILL.md parseable")

    base_dir = skill_md.parent

    # Check 2: scripts exist and are executable
    scripts_dir = base_dir / "scripts"
    if scripts_dir.is_dir():
        for script in sorted(scripts_dir.iterdir()):
            if script.is_file():
                if not script.exists():
                    print(f"  ✗ Script missing: {script.name}")
                    errors += 1
                elif not os.access(script, os.X_OK):
                    print(f"  ✗ Script not executable: {script.name}  (run: chmod +x {script})")
                    errors += 1
                else:
                    print(f"  ✓ Script executable: {script.name}")

    # Check 3: references readable
    references_dir = base_dir / "references"
    if references_dir.is_dir():
        for ref in sorted(references_dir.iterdir()):
            if ref.is_file():
                if not os.access(ref, os.R_OK):
                    print(f"  ✗ Reference not readable: {ref.name}")
                    errors += 1
                else:
                    print(f"  ✓ Reference readable: {ref.name}")

    # Check 4: allowed-tools available on PATH (warning, not error)
    if parsed.allowed_tools:
        for tool in parsed.allowed_tools:
            tool_name = tool.split("/")[-1].split("(")[0].strip()
            if tool_name and shutil.which(tool_name) is None:
                print(f"  ! Tool not found in PATH: {tool_name}  (may be an MCP tool — OK)")

    return errors


def _prompt_yes_no(prompt: str) -> bool:
    """Prompt the user for yes/no. Returns True for y/Y. Non-interactive → False."""
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(prompt).strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False
