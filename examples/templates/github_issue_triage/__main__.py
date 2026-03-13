"""
CLI entry point for GitHub Issue Triage Agent.

Usage:
  hive open                                  — launch the GUI (recommended)
  python -m github_issue_triage run --owner adenhq --repo hive
  python -m github_issue_triage info
  python -m github_issue_triage validate
  python -m github_issue_triage shell
"""

import asyncio
import json
import logging
import sys
import click

from .agent import default_agent, GitHubIssueTriageAgent
from .config import agent_config


def setup_logging(verbose=False, debug=False):
    """Configure logging for execution visibility."""
    if debug:
        level, fmt = logging.DEBUG, "%(asctime)s %(name)s: %(message)s"
    elif verbose:
        level, fmt = logging.INFO, "%(message)s"
    else:
        level, fmt = logging.WARNING, "%(levelname)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)
    logging.getLogger("framework").setLevel(level)


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """GitHub Issue Triage Agent - Automated issue classification and routing."""
    pass


@cli.command()
@click.option("--owner", "-o", type=str, default="", help="GitHub repo owner (overrides config.py)")
@click.option("--repo", "-r", type=str, default="", help="GitHub repo name (overrides config.py)")
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(owner, repo, quiet, verbose, debug):
    """Triage open issues in a GitHub repository.

    owner and repo default to the values in config.py if not passed as flags.
    """
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    # Prefer CLI args; fall back to config.py values.
    resolved_owner = owner or agent_config.owner
    resolved_repo = repo or agent_config.repo

    context = {"owner": resolved_owner, "repo": resolved_repo}

    result = asyncio.run(default_agent.run(context))

    output_data = {
        "success": result.success,
        "steps_executed": result.steps_executed,
        "output": result.output,
    }
    if result.error:
        output_data["error"] = result.error

    click.echo(json.dumps(output_data, indent=2, default=str))
    sys.exit(0 if result.success else 1)


@cli.command()
@click.option("--json", "output_json", is_flag=True)
def info(output_json):
    """Show agent information."""
    info_data = default_agent.info()
    if output_json:
        click.echo(json.dumps(info_data, indent=2))
    else:
        click.echo(f"Agent: {info_data['name']}")
        click.echo(f"Version: {info_data['version']}")
        click.echo(f"Description: {info_data['description']}")
        click.echo(f"\nNodes: {', '.join(info_data['nodes'])}")
        click.echo(f"Client-facing: {', '.join(info_data['client_facing_nodes'])}")
        click.echo(f"Entry: {info_data['entry_node']}")
        click.echo(f"Terminal: {', '.join(info_data['terminal_nodes'])}")
        sec = info_data.get("security", {})
        click.echo(f"\nSecurity:")
        click.echo(f"  owner configured: {sec.get('owner_configured')}")
        click.echo(f"  repo configured:  {sec.get('repo_configured')}")
        click.echo(f"  allowed_repos:    {sec.get('allowed_repos')}")


@cli.command()
def validate():
    """Validate agent structure."""
    validation = default_agent.validate()
    if validation["valid"]:
        click.echo("✓ Agent structure is valid")
    else:
        click.echo("✗ Agent has errors:")
        for error in validation["errors"]:
            click.echo(f"  ERROR: {error}")
    if validation.get("warnings"):
        click.echo("\nWarnings:")
        for warning in validation["warnings"]:
            click.echo(f"  WARN: {warning}")
    sys.exit(0 if validation["valid"] else 1)


@cli.command()
@click.option("--verbose", "-v", is_flag=True)
def shell(verbose):
    """Interactive triage session (CLI)."""
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose=False):
    """Async interactive shell."""
    setup_logging(verbose=verbose)

    click.echo("=== GitHub Issue Triage Agent ===")
    click.echo("Enter owner/repo to triage (or 'quit' to exit):\n")

    agent = GitHubIssueTriageAgent()
    await agent.start()

    try:
        while True:
            try:
                raw = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Repo> "
                )
                if raw.lower() in ["quit", "exit", "q"]:
                    click.echo("Goodbye!")
                    break

                if not raw.strip():
                    continue

                parts = raw.strip().split("/")
                if len(parts) != 2:
                    click.echo("Format: owner/repo (e.g. your-org/your-repo)")
                    continue

                owner, repo = parts
                click.echo(f"\nTriaging {owner}/{repo}...\n")

                result = await agent.trigger_and_wait(
                    "start", {"owner": owner, "repo": repo}
                )

                if result is None:
                    click.echo("\n[Execution timed out]\n")
                    continue

                if result.success:
                    output = result.output
                    triaged = output.get("triage_summary", {}).get("triaged", 0)
                    click.echo(f"\nTriage complete — {triaged} issues processed\n")
                else:
                    click.echo(f"\nTriage failed: {result.error}\n")

            except KeyboardInterrupt:
                click.echo("\nGoodbye!")
                break
            except Exception as e:
                click.echo(f"Error: {e}", err=True)
                import traceback
                traceback.print_exc()
    finally:
        await agent.stop()


if __name__ == "__main__":
    cli()
