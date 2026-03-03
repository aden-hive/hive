"""CLI entry point for Credential Tester agent."""

import asyncio
import logging
import sys

import click

from .agent import CredentialTesterAgent


def setup_logging(verbose=False, debug=False):
    if debug:
        level, fmt = logging.DEBUG, "%(asctime)s %(name)s: %(message)s"
    elif verbose:
        level, fmt = logging.INFO, "%(message)s"
    else:
        level, fmt = logging.WARNING, "%(levelname)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)


def pick_account(agent: CredentialTesterAgent) -> dict | None:
    """Interactive account picker. Returns selected account dict or None."""
    accounts = agent.list_accounts()
    if not accounts:
        click.echo("No connected accounts found.")
        click.echo("Set ADEN_API_KEY and connect accounts at https://app.adenhq.com")
        return None

    click.echo("\nConnected accounts:\n")
    for i, acct in enumerate(accounts, 1):
        provider = acct.get("provider", "?")
        alias = acct.get("alias", "?")
        identity = acct.get("identity", {})
        detail_parts = [f"{k}: {v}" for k, v in identity.items() if v]
        detail = f"  ({', '.join(detail_parts)})" if detail_parts else ""
        click.echo(f"  {i}. {provider}/{alias}{detail}")

    click.echo()
    while True:
        choice = click.prompt("Pick an account to test", type=int, default=1)
        if 1 <= choice <= len(accounts):
            return accounts[choice - 1]
        click.echo(f"Invalid choice. Enter 1-{len(accounts)}.")


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """Credential Tester — verify synced credentials via live API calls."""
    pass


@cli.command()
@click.option("--verbose", "-v", is_flag=True)
@click.option("--debug", is_flag=True)
def tui(verbose, debug):
    """Launch TUI to test a credential interactively."""
    setup_logging(verbose=verbose, debug=debug)

    try:
        from framework.tui.app import AdenTUI
    except ImportError:
        click.echo("TUI requires 'textual'. Install with: pip install textual")
        sys.exit(1)

    agent = CredentialTesterAgent()
    account = pick_account(agent)
    if account is None:
        sys.exit(1)

    agent.select_account(account)
    provider = account.get("provider", "?")
    alias = account.get("alias", "?")
    click.echo(f"\nTesting {provider}/{alias}...\n")

    async def run_tui():
        agent._setup()
        runtime = agent._agent_runtime
        await runtime.start()
        try:
            app = AdenTUI(runtime)
            await app.run_async()
        finally:
            await runtime.stop()

    asyncio.run(run_tui())


@cli.command()
@click.option("--verbose", "-v", is_flag=True)
@click.option("--debug", is_flag=True)
def shell(verbose, debug):
    """Interactive CLI session to test a credential."""
    setup_logging(verbose=verbose, debug=debug)
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose=False):
    agent = CredentialTesterAgent()
    account = pick_account(agent)
    if account is None:
        return

    agent.select_account(account)
    provider = account.get("provider", "?")
    alias = account.get("alias", "?")

    click.echo(f"\nTesting {provider}/{alias}")
    click.echo("Type your requests or 'quit' to exit.\n")

    await agent.start()

    try:
        result = await agent._agent_runtime.trigger_and_wait(
            entry_point_id="start",
            input_data={},
        )
        if result:
            click.echo(f"\nSession ended: {'success' if result.success else result.error}")
    except KeyboardInterrupt:
        click.echo("\nGoodbye!")
    finally:
        await agent.stop()


@cli.command(name="list")
def list_accounts():
    """List all connected accounts."""
    agent = CredentialTesterAgent()
    accounts = agent.list_accounts()

    if not accounts:
        click.echo("No connected accounts found.")
        return

    click.echo("\nConnected accounts:\n")
    for acct in accounts:
        provider = acct.get("provider", "?")
        alias = acct.get("alias", "?")
        identity = acct.get("identity", {})
        detail_parts = [f"{k}: {v}" for k, v in identity.items() if v]
        detail = f"  ({', '.join(detail_parts)})" if detail_parts else ""
        click.echo(f"  {provider}/{alias}{detail}")


if __name__ == "__main__":
    cli()
