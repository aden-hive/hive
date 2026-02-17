"""CLI entry point for Salesforce Manager Agent."""

import asyncio
import json
import logging
import sys
import click
from .agent import SalesforceManagerAgent

def setup_logging(verbose=False, debug=False):
    if debug:
        level, fmt = logging.DEBUG, "%(asctime)s %(name)s: %(message)s"
    elif verbose:
        level, fmt = logging.INFO, "%(message)s"
    else:
        level, fmt = logging.WARNING, "%(levelname)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)

@click.group()
def cli():
    """Salesforce Manager Agent - Manage Salesforce CRM records and perform queries."""
    pass

@cli.command()
@click.option("--query", "-q", type=str, help="Salesforce task or query")
@click.option("--verbose", "-v", is_flag=True)
def run(query, verbose):
    """Run a single Salesforce task."""
    setup_logging(verbose=verbose)
    agent = SalesforceManagerAgent()
    
    async def _run():
        await agent.start()
        try:
            result = await agent.trigger_and_wait("default", {"user_query": query})
            if result:
                click.echo(json.dumps(result.output, indent=2))
            else:
                click.echo("Task failed.")
        finally:
            await agent.stop()
            
    asyncio.run(_run())

@cli.command()
def shell():
    """Interactive shell for Salesforce Manager."""
    asyncio.run(_interactive_shell())

async def _interactive_shell():
    click.echo("=== Salesforce Manager Agent ===")
    agent = SalesforceManagerAgent()
    await agent.start()
    
    try:
        while True:
            query = await asyncio.get_event_loop().run_in_executor(None, input, "Salesforce> ")
            if query.lower() in ["exit", "quit", "q"]:
                break
            if not query.strip():
                continue
            
            result = await agent.trigger_and_wait("default", {"user_query": query})
            if result and result.success:
                click.echo(f"\nResult: {result.output.get('salesforce_result', 'No result')}\n")
            elif result:
                click.echo(f"\nError: {result.error}\n")
    finally:
        await agent.stop()

if __name__ == "__main__":
    cli()
