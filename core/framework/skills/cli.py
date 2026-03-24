"""CLI commands for the Hive skill system.

Phase 1 commands (AS-13):
  hive skill list             — list discovered skills across all scopes
  hive skill trust <path>    — permanently trust a project repo's skills

Full CLI suite (CLI-1 through CLI-13) is Phase 2.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


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
