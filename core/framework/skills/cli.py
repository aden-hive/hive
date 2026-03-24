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
  hive skill test             — run skill in isolation or execute its eval suite
  hive skill trust            — permanently trust a project repo's skills
"""

from __future__ import annotations

import json as _json
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
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")
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
    install_parser.add_argument("--json", action="store_true", help="Output as JSON")
    install_parser.set_defaults(func=cmd_skill_install)

    # hive skill remove
    remove_parser = skill_sub.add_parser("remove", help="Uninstall a skill")
    remove_parser.add_argument("name", help="Skill name to remove")
    remove_parser.add_argument("--json", action="store_true", help="Output as JSON")
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
    info_parser.add_argument("--json", action="store_true", help="Output as JSON")
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
    validate_parser.add_argument("--json", action="store_true", help="Output as JSON")
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
    doctor_parser.add_argument("--json", action="store_true", help="Output as JSON")
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
    update_parser.add_argument("--json", action="store_true", help="Output as JSON")
    update_parser.set_defaults(func=cmd_skill_update)

    # hive skill search
    search_parser = skill_sub.add_parser(
        "search", help="Search the skill registry by name, tag, or description"
    )
    search_parser.add_argument("query", help="Search query string")
    search_parser.add_argument("--json", action="store_true", help="Output as JSON")
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
    fork_parser.add_argument("--json", action="store_true", help="Output as JSON")
    fork_parser.set_defaults(func=cmd_skill_fork)

    # hive skill test
    test_parser = skill_sub.add_parser(
        "test", help="Run a skill in isolation or execute its eval suite (CLI-9)"
    )
    test_parser.add_argument("path", help="Path to SKILL.md or its parent directory")
    test_parser.add_argument(
        "--input",
        dest="input_json",
        default=None,
        metavar="JSON",
        help='JSON input to pass to the skill, e.g. \'{"prompt": "..."}\'',
    )
    test_parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help="Override the LLM model (default: claude-haiku-4-5-20251001)",
    )
    test_parser.add_argument("--json", action="store_true", help="Output as JSON")
    test_parser.set_defaults(func=cmd_skill_test)

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

    if getattr(args, "json", False):
        print(
            _json.dumps(
                {
                    "skills": [
                        {
                            "name": s.name,
                            "description": s.description,
                            "scope": s.source_scope,
                            "location": s.location,
                        }
                        for s in skills
                    ]
                }
            )
        )
        return 0

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

    use_json = getattr(args, "json", False)

    # hive skill install --from <url> [--name <name>]
    if args.from_url:
        skill_name = args.install_name or _derive_name_from_url(args.from_url)
        if not use_json:
            print(f"Installing '{skill_name}' from {args.from_url} ...", flush=True)
        try:
            dest = install_from_git(
                git_url=args.from_url,
                skill_name=skill_name,
                version=args.version,
                target_dir=target_dir,
            )
        except SkillError as exc:
            if use_json:
                print(_json.dumps({"error": exc.what, "why": exc.why, "fix": exc.fix}))
            else:
                print(f"Error: {exc.what}", file=sys.stderr)
                print(f"  Why: {exc.why}", file=sys.stderr)
                print(f"  Fix: {exc.fix}", file=sys.stderr)
            return 1
        if use_json:
            print(_json.dumps({"name": skill_name, "location": str(dest)}))
        else:
            print(f"✓ Installed: {skill_name}")
            print(f"  Location: {dest}")
        return 0

    # hive skill install <name>  (registry lookup)
    if args.name_or_url:
        name = args.install_name or args.name_or_url
        client = RegistryClient()
        entry = client.get_skill_entry(args.name_or_url)
        if entry is None:
            if use_json:
                print(
                    _json.dumps(
                        {
                            "error": f"skill '{args.name_or_url}' not found in registry",
                            "why": "Registry may be unavailable or skill name is incorrect.",
                            "fix": "hive skill install --from <url>",
                        }
                    )
                )
            else:
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
        if not use_json:
            print(f"Installing '{name}' from registry ...")
        try:
            dest = install_from_registry(entry, target_dir=target_dir, version=args.version)
        except SkillError as exc:
            if use_json:
                print(_json.dumps({"error": exc.what, "why": exc.why, "fix": exc.fix}))
            else:
                print(f"Error: {exc.what}", file=sys.stderr)
                print(f"  Why: {exc.why}", file=sys.stderr)
                print(f"  Fix: {exc.fix}", file=sys.stderr)
            return 1
        if use_json:
            print(_json.dumps({"name": name, "location": str(dest)}))
        else:
            print(f"✓ Installed: {name}")
            print(f"  Location: {dest}")
        return 0

    if use_json:
        print(
            _json.dumps(
                {
                    "error": "No install target specified",
                    "why": "Provide a skill name, --from <url>, or --pack <name>.",
                    "fix": "hive skill install --help",
                }
            )
        )
    else:
        print("Error: specify a skill name, --from <url>, or --pack <name>.", file=sys.stderr)
        print("  Usage: hive skill install <name>", file=sys.stderr)
        print("         hive skill install --from <git-url>", file=sys.stderr)
        print("         hive skill install --pack <pack-name>", file=sys.stderr)
    return 1


def cmd_skill_remove(args) -> int:
    """Uninstall a skill from ~/.hive/skills/."""
    from framework.skills.installer import remove_skill
    from framework.skills.skill_errors import SkillError

    use_json = getattr(args, "json", False)

    try:
        removed = remove_skill(args.name)
    except SkillError as exc:
        if use_json:
            print(_json.dumps({"error": exc.what, "why": exc.why, "fix": exc.fix}))
        else:
            print(f"Error: {exc.what}", file=sys.stderr)
            print(f"  Why: {exc.why}", file=sys.stderr)
            print(f"  Fix: {exc.fix}", file=sys.stderr)
        return 1

    if not removed:
        if use_json:
            print(
                _json.dumps(
                    {
                        "error": f"skill '{args.name}' not found",
                        "why": "Skill is not installed in ~/.hive/skills/.",
                        "fix": "hive skill list",
                    }
                )
            )
        else:
            print(f"Error: skill '{args.name}' not found in ~/.hive/skills/.", file=sys.stderr)
            print("  Use 'hive skill list' to see installed skills.", file=sys.stderr)
        return 1

    if use_json:
        print(_json.dumps({"name": args.name, "removed": True}))
    else:
        print(f"✓ Removed: {args.name}")
    return 0


def cmd_skill_info(args) -> int:
    """Show details for a skill by name."""
    from framework.skills.discovery import DiscoveryConfig, SkillDiscovery
    from framework.skills.registry import RegistryClient

    use_json = getattr(args, "json", False)
    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    skills = SkillDiscovery(DiscoveryConfig(project_root=project_dir)).discover()
    match = next((s for s in skills if s.name == args.name), None)

    if match:
        base = Path(match.base_dir)
        sub_files: dict[str, list[str]] = {}
        for sub in ("scripts", "references", "assets"):
            sub_dir = base / sub
            if sub_dir.is_dir():
                files = sorted(f.name for f in sub_dir.iterdir() if f.is_file())
                if files:
                    sub_files[sub] = files

        if use_json:
            print(
                _json.dumps(
                    {
                        "name": match.name,
                        "description": match.description,
                        "scope": match.source_scope,
                        "location": match.location,
                        "installed": True,
                        "license": match.license,
                        "compatibility": match.compatibility or [],
                        "allowed_tools": match.allowed_tools or [],
                        "tags": list(match.metadata.get("tags", [])) if match.metadata else [],
                        **dict(sub_files),
                    }
                )
            )
            return 0

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
        for sub, files in sub_files.items():
            print(f"  {sub.capitalize():13s}: {', '.join(files)}")
        return 0

    # Not installed locally — try registry
    client = RegistryClient()
    entry = client.get_skill_entry(args.name)
    if entry:
        if use_json:
            print(
                _json.dumps(
                    {
                        "name": entry.get("name", args.name),
                        "description": entry.get("description", ""),
                        "installed": False,
                        "version": entry.get("version", "unknown"),
                        "author": entry.get("author", "unknown"),
                        "trust_tier": entry.get("trust_tier", "community"),
                        "license": entry.get("license"),
                        "tags": entry.get("tags", []),
                    }
                )
            )
            return 0

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

    if use_json:
        print(
            _json.dumps(
                {
                    "error": f"skill '{args.name}' not found locally or in registry",
                }
            )
        )
    else:
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

    if getattr(args, "json", False):
        print(
            _json.dumps(
                {
                    "path": str(path),
                    "passed": result.passed,
                    "errors": result.errors,
                    "warnings": result.warnings,
                }
            )
        )
        return 0 if result.passed else 1

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

    use_json = getattr(args, "json", False)
    overall_errors = 0

    if args.defaults:
        if not use_json:
            print("\nFRAMEWORK DEFAULT SKILLS")
            print("─" * 40)
        skill_results = []
        for skill_name, dir_name in SKILL_REGISTRY.items():
            skill_md = _DEFAULT_SKILLS_DIR / dir_name / "SKILL.md"
            if use_json:
                report = _doctor_skill_file(
                    skill_name, skill_md, parse_skill_md, json_mode=True, scope="framework"
                )
                overall_errors += len(report["errors"])
                skill_results.append(report)
            else:
                overall_errors += _doctor_skill_file(skill_name, skill_md, parse_skill_md)
        if use_json:
            print(_json.dumps({"skills": skill_results, "total_errors": overall_errors}))
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
                if use_json:
                    report = _doctor_skill_file(
                        args.name, candidate, parse_skill_md, json_mode=True, scope="user"
                    )
                    print(_json.dumps({"skills": [report], "total_errors": len(report["errors"])}))
                    return 1 if report["errors"] else 0
                print(f"\nChecking skill: {args.name}  [user]")
                overall_errors += _doctor_skill_file(args.name, candidate, parse_skill_md)
                print()
                print(f"✗ {overall_errors} error(s) found.")
                return 1
            if use_json:
                print(_json.dumps({"error": f"skill '{args.name}' not found"}))
            else:
                print(f"Error: skill '{args.name}' not found.", file=sys.stderr)
            return 1

    if not skills:
        if use_json:
            print(_json.dumps({"skills": [], "total_errors": 0}))
        else:
            print("No skills discovered.")
        return 0

    skill_results = []
    for skill in skills:
        if use_json:
            report = _doctor_skill_file(
                skill.name,
                Path(skill.location),
                parse_skill_md,
                json_mode=True,
                scope=skill.source_scope,
            )
            overall_errors += len(report["errors"])
            skill_results.append(report)
        else:
            print(f"\nChecking skill: {skill.name}  [{skill.source_scope}]")
            overall_errors += _doctor_skill_file(skill.name, Path(skill.location), parse_skill_md)

    if use_json:
        print(_json.dumps({"skills": skill_results, "total_errors": overall_errors}))
        return 0 if overall_errors == 0 else 1

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

    use_json = getattr(args, "json", False)
    client = RegistryClient()

    if not args.name:
        # Refresh cache only
        if not use_json:
            print("Refreshing registry cache ...")
        index = client.fetch_index(force_refresh=True)
        if index is None:
            if use_json:
                print(
                    _json.dumps(
                        {
                            "status": "unavailable",
                            "warning": "registry unavailable — could not refresh cache",
                        }
                    )
                )
            else:
                print("Warning: registry unavailable — could not refresh cache.", file=sys.stderr)
            return 0  # Non-fatal
        count = len(index.get("skills", []))
        if use_json:
            print(_json.dumps({"status": "refreshed", "skill_count": count}))
        else:
            print(f"✓ Registry cache updated ({count} skills).")
        return 0

    # Update a specific skill
    entry = client.get_skill_entry(args.name)
    if entry is None:
        if use_json:
            print(
                _json.dumps(
                    {
                        "error": f"skill '{args.name}' not found in registry",
                        "why": "Registry may be unavailable or skill name is incorrect.",
                        "fix": "Check your network connection or verify the skill name.",
                    }
                )
            )
        else:
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
        import yaml

        try:
            content = installed_skill_md.read_text(encoding="utf-8")
            parts = content.split("---", 2)
            fm = yaml.safe_load(parts[1]) if len(parts) >= 3 else {}
            installed_version = fm.get("version") if isinstance(fm, dict) else None
        except Exception:
            installed_version = None

        if installed_version and installed_version == registry_version:
            if use_json:
                print(
                    _json.dumps(
                        {
                            "name": args.name,
                            "status": "up_to_date",
                            "version": registry_version,
                        }
                    )
                )
            else:
                print(f"✓ '{args.name}' is already at version {registry_version}.")
            return 0

        if not installed_version and not use_json:
            print(
                f"Warning: installed skill '{args.name}' has no version field — "
                "cannot compare. Re-installing.",
                file=sys.stderr,
            )

    # Remove and reinstall
    if not use_json:
        print(f"Updating '{args.name}' ...")
    try:
        remove_skill(args.name)
        dest = install_from_registry(entry, target_dir=USER_SKILLS_DIR)
    except SkillError as exc:
        if use_json:
            print(_json.dumps({"error": exc.what, "why": exc.why, "fix": exc.fix}))
        else:
            print(f"Error: {exc.what}", file=sys.stderr)
            print(f"  Why: {exc.why}", file=sys.stderr)
            print(f"  Fix: {exc.fix}", file=sys.stderr)
        return 1

    new_version = registry_version or "unknown"
    if use_json:
        print(
            _json.dumps(
                {
                    "name": args.name,
                    "status": "updated",
                    "version": new_version,
                    "location": str(dest),
                }
            )
        )
    else:
        print(f"✓ Updated '{args.name}' to version {new_version}.")
        print(f"  Location: {dest}")
    return 0


def cmd_skill_search(args) -> int:
    """Search the skill registry by name, tag, or description."""
    from framework.skills.registry import RegistryClient

    use_json = getattr(args, "json", False)
    client = RegistryClient()
    # Trigger a fetch to check availability
    index = client.fetch_index()
    if index is None:
        if use_json:
            print(
                _json.dumps(
                    {
                        "error": "registry unavailable",
                        "query": args.query,
                        "fix": "hive skill install --from <url>",
                    }
                )
            )
        else:
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

    if use_json:
        print(
            _json.dumps(
                {
                    "query": args.query,
                    "results": [
                        {
                            "name": e.get("name", ""),
                            "description": e.get("description", ""),
                            "trust_tier": e.get("trust_tier", "community"),
                            "tags": e.get("tags", []),
                        }
                        for e in results
                    ],
                }
            )
        )
        return 0

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

    use_json = getattr(args, "json", False)
    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    skills = SkillDiscovery(DiscoveryConfig(project_root=project_dir)).discover()
    source = next((s for s in skills if s.name == args.name), None)

    if source is None:
        if use_json:
            print(_json.dumps({"error": f"skill '{args.name}' not found"}))
        else:
            print(f"Error: skill '{args.name}' not found.", file=sys.stderr)
            print("  Use 'hive skill list' to see available skills.", file=sys.stderr)
        return 1

    new_name = args.new_name or f"{args.name}-fork"
    target_dir = Path(args.target_dir).resolve() if args.target_dir else USER_SKILLS_DIR
    dest = target_dir / new_name

    if not args.yes and not use_json:
        answer = _prompt_yes_no(f"Fork '{args.name}' to {dest}? [y/N] ")
        if not answer:
            print("Aborted.")
            return 0

    try:
        result = fork_skill(source, new_name, target_dir)
    except SkillError as exc:
        if use_json:
            print(_json.dumps({"error": exc.what, "why": exc.why, "fix": exc.fix}))
        else:
            print(f"Error: {exc.what}", file=sys.stderr)
            print(f"  Why: {exc.why}", file=sys.stderr)
            print(f"  Fix: {exc.fix}", file=sys.stderr)
        return 1

    if use_json:
        print(_json.dumps({"source": args.name, "new_name": new_name, "location": str(result)}))
    else:
        print(f"✓ Forked '{args.name}' → '{new_name}'")
        print(f"  Location: {result}")
        print("  Edit SKILL.md to customise, then run: hive skill validate")
    return 0


def cmd_skill_test(args) -> int:
    """Run a skill in isolation or execute its eval suite (CLI-9).

    Three progressive modes:
      1. Structural (always): validate_strict + doctor checks — no API key needed.
      2. Invocation (--input): inject skill body as system, run prompt through Claude.
      3. Eval suite (evals/ present): run each eval case + LLM-judge assertions.
    """
    from framework.skills.parser import parse_skill_md
    from framework.skills.validator import validate_strict

    use_json = getattr(args, "json", False)

    # ── 1. Resolve path ──────────────────────────────────────────────────────
    path = Path(args.path)
    if path.is_dir():
        path = path / "SKILL.md"

    # ── 2. Structural validation (always) ────────────────────────────────────
    vresult = validate_strict(path)
    structural = {
        "passed": vresult.passed,
        "errors": vresult.errors,
        "warnings": vresult.warnings,
    }

    if not use_json:
        for w in vresult.warnings:
            print(f"  [WARN]  {w}")
        for e in vresult.errors:
            print(f"  [ERROR] {e}")

    if not vresult.passed:
        if use_json:
            print(_json.dumps({"path": str(path), "skill": None, "structural": structural}))
        else:
            print(f"✗ {path} — structural validation failed. Fix errors before testing.")
        return 1

    # ── 3. Parse the skill ───────────────────────────────────────────────────
    skill = parse_skill_md(path, source_scope="user")
    if skill is None:
        if use_json:
            print(
                _json.dumps(
                    {
                        "path": str(path),
                        "skill": None,
                        "structural": {
                            "passed": False,
                            "errors": ["parse_skill_md returned None"],
                            "warnings": [],
                        },
                    }
                )
            )
        else:
            print(f"✗ {path} — skill could not be parsed.", file=sys.stderr)
        return 1

    evals_dir = path.parent / "evals"
    has_evals = evals_dir.is_dir() and any(evals_dir.glob("*.json"))
    has_input = args.input_json is not None

    # ── 4. Structural-only mode (no LLM needed) ───────────────────────────────
    if not has_input and not has_evals:
        doctor_errors = _doctor_skill_file(
            skill.name, path, parse_skill_md, json_mode=use_json, scope="user"
        )
        if use_json:
            print(
                _json.dumps(
                    {
                        "path": str(path),
                        "skill": skill.name,
                        "structural": structural,
                        "doctor": doctor_errors,
                    }
                )
            )
            return 0 if (structural["passed"] and not doctor_errors.get("errors")) else 1
        if doctor_errors == 0:
            print(f"✓ {skill.name} — structurally valid and healthy.")
            print("  No evals/ directory found. Use --input <json> for a live invocation test.")
        else:
            print(f"✗ {skill.name} — {doctor_errors} doctor error(s) found.")
        return 0 if doctor_errors == 0 else 1

    # ── 5. Initialize LLM provider ────────────────────────────────────────────
    provider = None
    provider_error = None
    try:
        from framework.llm.anthropic import AnthropicProvider

        model = getattr(args, "model", None) or "claude-haiku-4-5-20251001"
        provider = AnthropicProvider(model=model)
    except Exception as exc:
        provider_error = str(exc)

    if provider is None and has_input:
        # --input was explicitly requested but we have no provider — hard error
        if use_json:
            print(
                _json.dumps(
                    {
                        "path": str(path),
                        "skill": skill.name,
                        "error": f"Cannot initialize LLM provider: {provider_error}",
                        "fix": "Set ANTHROPIC_API_KEY to enable live invocation.",
                    }
                )
            )
        else:
            print(f"Error: Cannot initialize LLM provider: {provider_error}", file=sys.stderr)
            print("  Set ANTHROPIC_API_KEY to enable live invocation.", file=sys.stderr)
        return 1

    result: dict = {
        "path": str(path),
        "skill": skill.name,
        "structural": structural,
    }
    overall_failed = 0

    # ── 6. Invocation mode (--input) ──────────────────────────────────────────
    if has_input and provider is not None:
        raw = args.input_json
        try:
            data = _json.loads(raw)
        except ValueError:
            data = raw
        prompt = data.get("prompt", raw) if isinstance(data, dict) else str(data)

        if not use_json:
            print(f"\nRunning '{skill.name}' with provided input ...")
        try:
            response = provider.complete(
                messages=[{"role": "user", "content": prompt}],
                system=skill.body,
                max_tokens=2048,
            )
            if not use_json:
                print("\n── Response ──────────────────────────────────────────────────")
                print(response.content)
                print("──────────────────────────────────────────────────────────────")
            result["invocation"] = {
                "prompt": prompt,
                "response": response.content,
                "model": response.model,
            }
        except Exception as exc:
            if not use_json:
                print(f"Error during invocation: {exc}", file=sys.stderr)
            result["invocation"] = {"prompt": prompt, "error": str(exc)}
            overall_failed += 1

    # ── 7. Eval suite ─────────────────────────────────────────────────────────
    if has_evals:
        if provider is None:
            # Degrade gracefully: structural passed, just warn about evals
            if not use_json:
                n = len(list(evals_dir.glob("*.json")))
                print(
                    f"\nWarning: ANTHROPIC_API_KEY not set — skipping {n} eval file(s).",
                    file=sys.stderr,
                )
        else:
            from framework.testing.llm_judge import LLMJudge

            judge = LLMJudge(llm_provider=provider)
            eval_results = []

            for eval_file in sorted(evals_dir.glob("*.json")):
                try:
                    eval_data = _json.loads(eval_file.read_text(encoding="utf-8"))
                except Exception as exc:
                    if not use_json:
                        print(f"  [ERROR] Cannot parse {eval_file.name}: {exc}", file=sys.stderr)
                    overall_failed += 1
                    continue

                for eval_case in eval_data.get("evals", []):
                    case_id = eval_case.get("id", "?")
                    eval_prompt = eval_case.get("prompt", "")

                    if not use_json:
                        truncated = eval_prompt[:60] + ("..." if len(eval_prompt) > 60 else "")
                        print(f"\nEval #{case_id}: {truncated}")

                    try:
                        response = provider.complete(
                            messages=[{"role": "user", "content": eval_prompt}],
                            system=skill.body,
                            max_tokens=2048,
                        )
                        skill_response = response.content
                    except Exception as exc:
                        if not use_json:
                            print(f"  [ERROR] Invocation failed: {exc}", file=sys.stderr)
                        eval_results.append(
                            {
                                "id": case_id,
                                "prompt": eval_prompt,
                                "error": str(exc),
                                "passed": False,
                            }
                        )
                        overall_failed += 1
                        continue

                    assertion_results = []
                    case_failed = False
                    for assertion in eval_case.get("assertions", []):
                        try:
                            judged = judge.evaluate(
                                constraint=assertion,
                                source_document=eval_prompt,
                                summary=skill_response,
                                criteria=(
                                    "Evaluate whether the skill response satisfies the assertion."
                                ),
                            )
                            passes = judged.get("passes", False)
                            explanation = judged.get("explanation", "")
                        except Exception as exc:
                            passes = False
                            explanation = f"Judge error: {exc}"

                        assertion_results.append(
                            {
                                "text": assertion,
                                "passes": passes,
                                "explanation": explanation,
                            }
                        )
                        if not passes:
                            case_failed = True
                            overall_failed += 1

                        if not use_json:
                            icon = "✓" if passes else "✗"
                            print(f"  {icon} {assertion}")
                            if not passes:
                                print(f"    → {explanation}")

                    eval_results.append(
                        {
                            "id": case_id,
                            "prompt": eval_prompt,
                            "response": skill_response,
                            "assertions": assertion_results,
                            "passed": not case_failed,
                        }
                    )

            passed_count = sum(1 for e in eval_results if e.get("passed"))
            failed_count = len(eval_results) - passed_count
            result["evals"] = eval_results
            result["total_evals"] = len(eval_results)
            result["total_passed"] = passed_count
            result["total_failed"] = failed_count

            if not use_json:
                print(f"\n{passed_count}/{len(eval_results)} eval(s) passed.")

    # ── 8. Output ─────────────────────────────────────────────────────────────
    if use_json:
        print(_json.dumps(result))

    if not use_json:
        print()
        if overall_failed == 0:
            print(f"✓ {skill.name} — all tests passed.")
        else:
            print(f"✗ {skill.name} — {overall_failed} failure(s).")

    return 0 if overall_failed == 0 else 1


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


def _doctor_skill_file(
    skill_name: str,
    skill_md: Path,
    parse_fn,
    json_mode: bool = False,
    scope: str = "unknown",
):
    """Run doctor checks on a single skill file.

    Returns int (error count) when json_mode=False, or a dict report when json_mode=True.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Check 1: SKILL.md parseable
    parsed = parse_fn(skill_md)
    if parsed is None:
        msg = f"SKILL.md not parseable: {skill_md}"
        if json_mode:
            errors.append(msg)
            return {
                "name": skill_name,
                "scope": scope,
                "parseable": False,
                "errors": errors,
                "warnings": warnings,
            }
        print(f"  ✗ {msg}")
        return 1
    if not json_mode:
        print("  ✓ SKILL.md parseable")

    base_dir = skill_md.parent

    # Check 2: scripts exist and are executable
    scripts_dir = base_dir / "scripts"
    if scripts_dir.is_dir():
        for script in sorted(scripts_dir.iterdir()):
            if script.is_file():
                if not script.exists():
                    msg = f"Script missing: {script.name}"
                    errors.append(msg) if json_mode else print(f"  ✗ {msg}")
                elif not os.access(script, os.X_OK):
                    msg = f"Script not executable: {script.name}  (run: chmod +x {script})"
                    errors.append(msg) if json_mode else print(f"  ✗ {msg}")
                elif not json_mode:
                    print(f"  ✓ Script executable: {script.name}")

    # Check 3: references readable
    references_dir = base_dir / "references"
    if references_dir.is_dir():
        for ref in sorted(references_dir.iterdir()):
            if ref.is_file():
                if not os.access(ref, os.R_OK):
                    msg = f"Reference not readable: {ref.name}"
                    errors.append(msg) if json_mode else print(f"  ✗ {msg}")
                elif not json_mode:
                    print(f"  ✓ Reference readable: {ref.name}")

    # Check 4: allowed-tools available on PATH (warning, not error)
    if parsed.allowed_tools:
        for tool in parsed.allowed_tools:
            tool_name = tool.split("/")[-1].split("(")[0].strip()
            if tool_name and shutil.which(tool_name) is None:
                msg = f"Tool not found in PATH: {tool_name}  (may be an MCP tool — OK)"
                warnings.append(msg) if json_mode else print(f"  ! {msg}")

    if json_mode:
        return {
            "name": skill_name,
            "scope": scope,
            "parseable": True,
            "errors": errors,
            "warnings": warnings,
        }
    return len(errors)


def _prompt_yes_no(prompt: str) -> bool:
    """Prompt the user for yes/no. Returns True for y/Y. Non-interactive → False."""
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(prompt).strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False
