"""Skill trust CLI commands.

This module provides CLI commands for managing trusted repositories
for skill loading.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def register_skill_trust_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register skill trust subcommands.

    Args:
        subparsers: The subparsers action from the main parser
    """
    trust_parser = subparsers.add_parser(
        "skill",
        help="Manage skills and trust",
    )
    trust_subparsers = trust_parser.add_subparsers(dest="skill_command", required=True)

    trust_list = trust_subparsers.add_parser(
        "trust",
        help="Manage trusted repositories",
    )
    trust_list_subparsers = trust_list.add_subparsers(dest="trust_command", required=True)

    trust_list_subparsers.add_parser(
        "list",
        help="List trusted repositories",
    ).set_defaults(func=_cmd_trust_list)

    add_parser = trust_list_subparsers.add_parser(
        "add",
        help="Add a repository to trusted list",
    )
    add_parser.add_argument("url", help="Repository URL to trust")
    add_parser.add_argument(
        "--permanent",
        action="store_true",
        help="Trust permanently (not just for this session)",
    )
    add_parser.set_defaults(func=_cmd_trust_add)

    remove_parser = trust_list_subparsers.add_parser(
        "remove",
        help="Remove a repository from trusted list",
    )
    remove_parser.add_argument("url", help="Repository URL to untrust")
    remove_parser.set_defaults(func=_cmd_trust_remove)

    status_parser = trust_list_subparsers.add_parser(
        "status",
        help="Check trust status of a project",
    )
    status_parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help="Project path (default: current directory)",
    )
    status_parser.set_defaults(func=_cmd_trust_status)


def _cmd_trust_list(args: argparse.Namespace) -> int:
    """List trusted repositories."""
    from framework.trust import get_trust_store

    store = get_trust_store()
    trusted = store.list_trusted()

    if not trusted:
        print("No trusted repositories.")
        return 0

    print(f"{'Repository':<50} {'Trusted At':<25} {'Permanent'}")
    print("-" * 85)

    for repo in trusted:
        print(f"{repo.remote_url:<50} {repo.trusted_at.isoformat():<25} {repo.permanent}")

    return 0


def _cmd_trust_add(args: argparse.Namespace) -> int:
    """Add a repository to trusted list."""
    from framework.trust import get_trust_store

    store = get_trust_store()
    url = args.url

    store.trust(url, permanent=args.permanent)

    if args.permanent:
        print(f"✓ Added '{url}' to permanent trusted repositories")
    else:
        print(f"✓ Added '{url}' to session-trusted repositories")

    return 0


def _cmd_trust_remove(args: argparse.Namespace) -> int:
    """Remove a repository from trusted list."""
    from framework.trust import get_trust_store

    store = get_trust_store()
    url = args.url

    if store.untrust(url):
        print(f"✓ Removed '{url}' from trusted repositories")
    else:
        print(f"✗ '{url}' was not in the trusted list")
        return 1

    return 0


def _cmd_trust_status(args: argparse.Namespace) -> int:
    """Check trust status of a project."""
    from framework.skills import display_trust_status
    from framework.trust.detector import check_project_trust
    from framework.trust.store import get_trust_store

    project_path = Path(args.project).resolve()
    store = get_trust_store()
    status = check_project_trust(project_path, store)

    display_trust_status(project_path, status)

    return 0
