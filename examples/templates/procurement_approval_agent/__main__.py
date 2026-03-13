"""CLI entry point for Procurement Approval Agent."""

import asyncio
import json
import os
from pathlib import Path
import sys

import click

from .agent import default_agent
from .monitor import RequestMonitor, spawn_daemon, write_launchd_plist
from .nodes.quickbooks import has_quickbooks_api_credentials


@click.group()
@click.version_option(version="1.0.0")
def cli() -> None:
    """Procurement Approval Agent."""


def _setup_state_path() -> Path:
    storage_root = Path(os.environ.get("HIVE_AGENT_STORAGE_ROOT", str(Path.home() / ".hive" / "agents")))
    return storage_root / "procurement_approval_agent" / "setup_config.json"


@cli.command()
@click.option("--item", required=True)
@click.option("--cost", type=float, required=True)
@click.option("--department", required=True)
@click.option("--requester", required=True)
@click.option("--justification", required=True)
@click.option("--vendor", default="Unknown")
@click.option("--mock", is_flag=True, help="Run with no LLM provider")
@click.option(
    "--mock-qb/--no-mock-qb",
    default=True,
    help="Mock QuickBooks API sync (default: enabled for testing).",
)
@click.option("--interactive/--no-interactive", default=False, help="Prompt for yes/no workflow checkpoints.")
@click.option("--process/--skip-process", default=True, help="Default request processing decision.")
@click.option("--sync-confirm/--sync-cancel", default=True, help="Default final sync/export decision.")
@click.option(
    "--sync-method",
    type=click.Choice(["auto", "api", "csv"]),
    default="auto",
    show_default=True,
    help="Force sync route or auto-detect from QuickBooks credentials.",
)
@click.option(
    "--qb-available",
    type=click.Choice(["auto", "yes", "no"]),
    default="auto",
    show_default=True,
    help="Declare QuickBooks API credential availability for this run.",
)
@click.option(
    "--qb-credential-ref",
    default=None,
    help="Hive credential reference in {name}/{alias} format (example: quickbooks/default).",
)
def run(
    item,
    cost,
    department,
    requester,
    justification,
    vendor,
    mock,
    mock_qb,
    interactive,
    process,
    sync_confirm,
    sync_method,
    qb_available,
    qb_credential_ref,
) -> None:
    """Submit a purchase request."""
    context = {
        "item": item,
        "cost": cost,
        "department": department,
        "requester": requester,
        "justification": justification,
        "vendor": vendor,
    }
    if qb_credential_ref:
        context["qb_credential_ref"] = qb_credential_ref
    if interactive:
        process = click.confirm("Process this purchase request now?", default=process)
        context["process_request"] = process
        if process:
            default_has_qb = has_quickbooks_api_credentials()
            if qb_credential_ref:
                default_has_qb = has_quickbooks_api_credentials(credential_ref=qb_credential_ref)
            has_qb = click.confirm(
                "Do you have QuickBooks API credentials configured for this run?",
                default=default_has_qb,
            )
            context["declared_qb_api_available"] = has_qb
            context["declared_sync_preference"] = "api" if has_qb else "csv"
            context["sync_confirmed"] = click.confirm(
                "Proceed with final sync/export step after PO generation?",
                default=sync_confirm,
            )
        else:
            context["sync_confirmed"] = False
    else:
        context["process_request"] = process
        context["sync_confirmed"] = sync_confirm
        if sync_method in {"api", "csv"}:
            context["declared_sync_preference"] = sync_method
            context["declared_qb_api_available"] = sync_method == "api"
        elif qb_available in {"yes", "no"}:
            has_qb = qb_available == "yes"
            context["declared_qb_api_available"] = has_qb
            context["declared_sync_preference"] = "api" if has_qb else "csv"

    result = asyncio.run(default_agent.run(context, mock_mode=mock, mock_qb=mock_qb))

    output_data = {
        "success": result.success,
        "steps_executed": result.steps_executed,
        "output": result.output,
    }
    if result.error:
        output_data["error"] = result.error
    if not mock_qb:
        output_data["quickbooks_note"] = (
            "Real QuickBooks sync path is reserved for future credential/API integration."
        )

    click.echo(json.dumps(output_data, indent=2, default=str))
    sys.exit(0 if result.success else 1)


@cli.command()
def tui() -> None:
    """Launch TUI for interactive approval workflow."""
    click.echo("Use Hive TUI runner to launch this agent interactively.")
    click.echo(
        "Example: PYTHONPATH=core python hive run examples/templates/procurement_approval_agent --tui"
    )


@cli.command()
@click.option("--json", "output_json", is_flag=True)
def info(output_json) -> None:
    """Show agent information."""
    info_data = default_agent.info()
    if output_json:
        click.echo(json.dumps(info_data, indent=2))
        return

    click.echo(f"Agent: {info_data['name']}")
    click.echo(f"Version: {info_data['version']}")
    click.echo(f"Description: {info_data['description']}")
    click.echo(f"Nodes: {', '.join(info_data['nodes'])}")
    click.echo(f"Client-facing: {', '.join(info_data['client_facing_nodes'])}")
    click.echo(f"Entry: {info_data['entry_node']}")
    click.echo(f"Terminal: {', '.join(info_data['terminal_nodes'])}")


@cli.command()
def validate() -> None:
    """Validate agent structure."""
    validation = default_agent.validate()
    if validation["valid"]:
        click.echo("Agent is valid")
        for warning in validation["warnings"]:
            click.echo(f"  WARNING: {warning}")
        sys.exit(0)

    click.echo("Agent has errors:")
    for error in validation["errors"]:
        click.echo(f"  ERROR: {error}")
    sys.exit(1)


@cli.command()
@click.option("--watch-dir", default="/watched_requests", show_default=True)
@click.option("--poll-interval", default=2.0, show_default=True, type=float)
@click.option("--mock", is_flag=True, help="Run requests with mock LLM.")
@click.option(
    "--mock-qb/--no-mock-qb",
    default=True,
    help="Mock QuickBooks API sync path (default: enabled).",
)
@click.option("--auto-open-csv", is_flag=True, help="Reveal CSV export in file manager on fallback.")
@click.option("--notify/--no-notify", default=True, help="Send Slack/SMTP notifications if configured.")
@click.option("--force", is_flag=True, help="Override 24-hour duplicate request check.")
@click.option("--interactive/--no-interactive", default=False, help="Prompt for yes/no workflow checkpoints.")
@click.option("--process/--skip-process", default=True, help="Default request processing decision.")
@click.option("--sync-confirm/--sync-cancel", default=True, help="Default final sync/export decision.")
@click.option(
    "--sync-method",
    type=click.Choice(["auto", "api", "csv"]),
    default="auto",
    show_default=True,
    help="Force sync route or auto-detect from QuickBooks credentials.",
)
@click.option(
    "--qb-available",
    type=click.Choice(["auto", "yes", "no"]),
    default="auto",
    show_default=True,
    help="Declare QuickBooks API credential availability for this run.",
)
@click.option(
    "--qb-credential-ref",
    default=None,
    help="Hive credential reference in {name}/{alias} format (example: quickbooks/default).",
)
@click.option("--daemon/--no-daemon", default=False, help="Run monitor in background.")
@click.option("--log-file", default="/tmp/procurement_approval_agent_monitor.log", show_default=True)
def monitor(
    watch_dir,
    poll_interval,
    mock,
    mock_qb,
    auto_open_csv,
    notify,
    force,
    interactive,
    process,
    sync_confirm,
    sync_method,
    qb_available,
    qb_credential_ref,
    daemon,
    log_file,
) -> None:
    """Continuously monitor request folder and auto-process new JSON requests."""
    watch_path = Path(watch_dir).expanduser()
    if daemon and interactive:
        click.echo("--interactive is not supported with --daemon.", err=True)
        sys.exit(2)
    if daemon:
        pid = spawn_daemon(
            watch_dir=watch_path,
            poll_interval=poll_interval,
            mock_mode=mock,
            mock_qb=mock_qb,
            auto_open_csv=auto_open_csv,
            notify=notify,
            force=force,
            default_process_request=process,
            default_sync_confirmed=sync_confirm,
            sync_method=sync_method,
            qb_available=qb_available,
            qb_credential_ref=qb_credential_ref,
            log_file=Path(log_file).expanduser(),
        )
        click.echo(f"Started monitor daemon (PID: {pid})")
        click.echo(f"Log file: {Path(log_file).expanduser()}")
        return

    worker = RequestMonitor(
        watch_dir=watch_path,
        poll_interval=poll_interval,
        mock_mode=mock,
        mock_qb=mock_qb,
        auto_open_csv=auto_open_csv,
        notify=notify,
        force=force,
        interactive=interactive,
        default_process_request=process,
        default_sync_confirmed=sync_confirm,
        sync_method=sync_method,
        qb_available=qb_available,
        qb_credential_ref=qb_credential_ref,
    )
    click.echo(f"Monitoring {watch_path} for request files (*.json). Press Ctrl+C to stop.")
    try:
        asyncio.run(worker.run_forever())
    except KeyboardInterrupt:
        click.echo("Stopped monitor.")


@cli.command("write-launchd")
@click.option("--label", default="com.hive.procurement-approval-agent", show_default=True)
@click.option(
    "--destination",
    default="examples/templates/procurement_approval_agent/deploy/com.hive.procurement-approval-agent.plist",
    show_default=True,
)
@click.option("--watch-dir", default="/watched_requests", show_default=True)
@click.option("--poll-interval", default=2.0, show_default=True, type=float)
@click.option("--log-file", default="/tmp/procurement_approval_agent_launchd.log", show_default=True)
def write_launchd(label, destination, watch_dir, poll_interval, log_file) -> None:
    """Write a macOS launchd plist for background monitoring service."""
    plist_path = write_launchd_plist(
        destination=Path(destination).expanduser(),
        label=label,
        working_dir=Path.cwd(),
        watch_dir=Path(watch_dir).expanduser(),
        log_file=Path(log_file).expanduser(),
        poll_interval=poll_interval,
    )
    click.echo(f"Launchd plist written: {plist_path}")
    click.echo("Load with: launchctl load -w <plist-path>")


@cli.command("reset-setup")
def reset_setup() -> None:
    """Reset first-run setup wizard state file."""
    path = _setup_state_path()
    if path.exists():
        path.unlink()
        click.echo(f"Removed setup state: {path}")
    else:
        click.echo(f"No setup state file found: {path}")


if __name__ == "__main__":
    cli()
