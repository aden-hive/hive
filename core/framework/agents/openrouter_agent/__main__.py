"""CLI entry point for the OpenRouter agent.

Usage:
    uv run python -m framework.agents.openrouter_agent
    uv run python -m framework.agents.openrouter_agent shell
    uv run python -m framework.agents.openrouter_agent list-models

Mirrors credential_tester/__main__.py exactly.
"""

import asyncio

import click

from framework.llm.openrouter import FREE_MODELS

from .agent import OpenRouterAgent


def setup_logging(verbose=False, debug=False):
    from framework.observability import configure_logging

    if debug:
        configure_logging(level="DEBUG")
    elif verbose:
        configure_logging(level="INFO")
    else:
        configure_logging(level="WARNING")


def pick_model() -> str | None:
    """Interactive model picker. Returns full model ID or None."""
    models = list(FREE_MODELS.items())
    click.echo("\nAvailable free models:\n")
    for i, (alias, model_id) in enumerate(models, 1):
        click.echo(f"  {i:2}. {alias:<16}  {model_id}")
    click.echo()
    while True:
        choice = click.prompt(
            f"Pick a model (1-{len(models)}, Enter for default)",
            default="1",
        )
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                return models[idx][1]
        except ValueError:
            pass
        click.echo(f"Invalid choice. Enter 1-{len(models)}.")


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """OpenRouter Agent — free open-source model chat with web search and memory."""
    pass


@cli.command()
@click.option("--model", "-m", default=None, help="Full model ID or short alias.")
@click.option("--verbose", "-v", is_flag=True)
@click.option("--debug", is_flag=True)
def shell(model, verbose, debug):
    """Start an interactive chat session."""
    setup_logging(verbose=verbose, debug=debug)
    asyncio.run(_interactive_shell(model_override=model))


@cli.command(name="list-models")
def list_models():
    """List all available free models."""
    click.echo("\nFree models available on OpenRouter:\n")
    for alias, model_id in FREE_MODELS.items():
        click.echo(f"  {alias:<16}  {model_id}")
    click.echo()


async def _interactive_shell(model_override: str | None = None) -> None:
    import litellm

    litellm.suppress_debug_info = True

    agent = OpenRouterAgent()

    model = model_override or pick_model()
    if model:
        agent.select_model(model)

    click.echo(f"\nOpenRouter Agent — {agent._model}")
    click.echo("Type your message or 'quit' to exit.\n")

    await agent.start()

    try:
        while True:
            user_input = click.prompt("You", prompt_suffix="> ").strip()
            if user_input.lower() in ("quit", "exit", "q"):
                break
            if not user_input:
                continue

            result = await agent.run(user_message=user_input)
            if result.success:
                click.echo(f"\nAgent: {result.output.get('response', '(no response)')}\n")
            else:
                click.echo(f"\n[ERROR] {result.error}\n")
    except KeyboardInterrupt:
        click.echo("\nGoodbye!")
    finally:
        await agent.stop()


if __name__ == "__main__":
    cli()
