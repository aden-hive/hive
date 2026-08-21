"""
CLI entry point for Automated HR Screener.

Uses AgentRuntime for multi-entrypoint support with HITL pause/resume.
"""

import asyncio
import json
import logging
import sys
import click

from .agent import default_agent, HRScreenerAgent


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
    """Automated HR Screener - Screen resumes and rank candidates."""
    pass


@cli.command()
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(quiet, verbose, debug):
    """Execute the HR screener agent."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    context = {}

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
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def tui(verbose, debug):
    """Launch the TUI dashboard for interactive HR screening."""
    setup_logging(verbose=verbose, debug=debug)

    import os
    import sys

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        console = Console()
        welcome_text = Text()
        welcome_text.append("Welcome to the ", style="yellow")
        welcome_text.append("HR Screener Agent", style="bold yellow")
        welcome_text.append(" \n\n", style="yellow")
        welcome_text.append(
            "• Drag & drop PDF resumes to screen them automatically.\n", style="yellow"
        )
        welcome_text.append(
            "• Evaluates candidates against your specific Job Description.\n",
            style="yellow",
        )
        welcome_text.append(
            "• Sends official formatted acceptance/rejection emails via Resend.\n\n",
            style="yellow",
        )
        welcome_text.append("Press ", style="yellow")
        welcome_text.append("Ctrl+C", style="bold yellow")
        welcome_text.append(" at any time to exit.", style="yellow")

        console.print(
            Panel(
                welcome_text,
                title="[bold yellow]Automated HR Screener[/bold yellow]",
                border_style="yellow",
                expand=False,
            )
        )
        print("\n")
    except ImportError:
        print("\n=== Welcome to the HR Screener Agent ===\n")

    # Clean up quotes if user used `set KEY="value"` in Windows CMD
    for env_key in [
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "HUGGINGFACE_API_KEY",
        "CEREBRAS_API_KEY",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "SAMBANOVA_API_KEY",
        "RESEND_API_KEY",
    ]:
        val = os.environ.get(env_key, "").strip("\"'")
        if val:
            os.environ[env_key] = val

    # Check Resend key for email notifications
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not resend_key:
        print("\n  ℹ RESEND_API_KEY not set — email notifications will be unavailable.")
        resend_input = input(
            "  Enter Resend API key (or press Enter to skip): "
        ).strip()
        if resend_input:
            os.environ["RESEND_API_KEY"] = resend_input
            print("  ✓ RESEND_API_KEY set successfully.")

    # --- Collect inputs upfront in Python ---
    print("\n" + "=" * 60)
    print("  🐝 HR SCREENER SETUP")
    print("=" * 60)

    # 1. Job Description
    print("\n🐝 [1/3] Job Description")
    print("Paste the full job description below.")
    print("When finished, type --- on a new line and press Enter.")
    jd_lines = []
    while True:
        line = input()
        if line.strip() == "---":
            break
        jd_lines.append(line)
    job_description = "\n".join(jd_lines).strip()

    # 2. Resume PDF patha
    print("\n🐝 [2/3] Resume File Path")
    while True:
        resume_path = (
            input("Enter the full path to the resume PDF: ").strip().strip('"')
        )
        if resume_path:
            break
        print("  Path cannot be empty.")

    # 3. Email notifications
    print("\n🐝 [3/3] Email Notifications")
    while True:
        notify = (
            input("Send email notifications to candidates after screening? (yes/no): ")
            .strip()
            .lower()
        )
        if notify in ("yes", "no", "y", "n"):
            notify_candidates = "yes" if notify in ("yes", "y") else "no"
            break
        print("  Please type yes or no.")

    # Summary
    print("\n" + "-" * 60)
    print(
        f"  Job Description : {job_description[:60]}..."
        if len(job_description) > 60
        else f"  Job Description : {job_description}"
    )
    print(f"  Resume File     : {resume_path}")
    print(f"  Email Notify    : {notify_candidates}")
    print("-" * 60)
    input("Press Enter to start screening...")

    # Store collected inputs as environment variables for the intake node
    os.environ["HR_JOB_DESCRIPTION"] = job_description
    os.environ["HR_RESUME_FILES"] = resume_path
    os.environ["HR_NOTIFY_CANDIDATES"] = notify_candidates

    try:
        from framework.tui.app import AdenTUI
    except ImportError:
        click.echo(
            "TUI requires the 'textual' package. Install with: pip install textual"
        )
        sys.exit(1)

    from pathlib import Path

    from framework.llm import LiteLLMProvider
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.agent_runtime import create_agent_runtime
    from framework.runtime.event_bus import EventBus
    from framework.runtime.execution_stream import EntryPointSpec

    async def run_with_tui():
        agent = HRScreenerAgent()

        agent._event_bus = EventBus()
        agent._tool_registry = ToolRegistry()

        storage_path = Path.home() / ".hive" / "agents" / "hr_screener"
        storage_path.mkdir(parents=True, exist_ok=True)

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            agent._tool_registry.load_mcp_config(mcp_config_path)

        llm = LiteLLMProvider(
            model=agent.config.model,
            api_key=agent.config.api_key,
            api_base=agent.config.api_base,
        )

        tools = list(agent._tool_registry.get_tools().values())
        tool_executor = agent._tool_registry.get_executor()
        graph = agent._build_graph()

        runtime = create_agent_runtime(
            graph=graph,
            goal=agent.goal,
            storage_path=storage_path,
            entry_points=[
                EntryPointSpec(
                    id="start",
                    name="Start HR Screening",
                    entry_node="intake",
                    trigger_type="manual",
                    isolation_level="isolated",
                ),
            ],
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
        )

        await runtime.start()

        # Set welcome message for TUI chat pane
        jd_short = (
            job_description[:60] + "..."
            if len(job_description) > 60
            else job_description
        )
        runtime.intro_message = (
            f"Welcome to the Automated HR Screener!\n\n"
            f"  Job Description : {jd_short}\n"
            f"  Resume File     : {resume_path}\n"
            f"  Email Notify    : {notify_candidates}\n\n"
            f"Type 'yes' to start screening."
        )

        try:
            app = AdenTUI(runtime)
            await app.run_async()
        finally:
            await runtime.stop()

    asyncio.run(run_with_tui())


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


@cli.command()
def validate():
    """Validate agent structure."""
    validation = default_agent.validate()
    if validation["valid"]:
        click.echo("Agent is valid")
        if validation["warnings"]:
            for warning in validation["warnings"]:
                click.echo(f"  WARNING: {warning}")
    else:
        click.echo("Agent has errors:")
        for error in validation["errors"]:
            click.echo(f"  ERROR: {error}")
    sys.exit(0 if validation["valid"] else 1)


@cli.command()
@click.option("--verbose", "-v", is_flag=True)
def shell(verbose):
    """Interactive HR screening session (CLI, no TUI)."""
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose=False):
    """Async interactive shell."""
    setup_logging(verbose=verbose)

    click.echo("=== Automated HR Screener ===")
    click.echo("Paste a job description and provide a resume folder to get started.")
    click.echo(
        "Commands: /sessions to see previous sessions, /pause to pause execution\n"
    )

    agent = HRScreenerAgent()
    await agent.start()

    try:
        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, input, "HR> "
                )
                if user_input.lower() in ["quit", "exit", "q"]:
                    click.echo("Goodbye!")
                    break

                click.echo("\nProcessing resumes...\n")

                result = await agent.trigger_and_wait("start", {})

                if result is None:
                    click.echo("\n[Execution timed out]\n")
                    continue

                if result.success:
                    output = result.output
                    if "report_file" in output:
                        click.echo(f"\nReport saved: {output['report_file']}\n")
                else:
                    click.echo(f"\nFailed: {result.error}\n")

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
