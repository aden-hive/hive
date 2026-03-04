"""
Entry point for the Document Intake Agent.
Usage: PYTHONPATH=exports uv run python -m document_intake_agent
"""

import click
import asyncio
import json
from pathlib import Path

from .agent import default_agent, goal, nodes, edges, entry_node


@click.group()
def cli():
    """Universal Document Intake & Action Agent CLI."""
    pass


@cli.command()
@click.option("--file-path", required=True, help="Path to the document to process")
@click.option("--source-channel", default="upload", help="Source channel (upload, email, api, webhook)")
@click.option("--metadata", default="{}", help="Additional metadata as JSON string")
def process(file_path: str, source_channel: str, metadata: str):
    """Process a single document."""
    try:
        metadata_dict = json.loads(metadata)
    except json.JSONDecodeError:
        click.echo("Error: Invalid JSON in metadata parameter")
        return

    input_data = {
        "file_path": file_path,
        "source_channel": source_channel,
        "metadata": metadata_dict,
    }

    click.echo(f"Processing document: {file_path}")

    # For now, just show what would be processed
    # In a full implementation, this would use the agent runtime
    click.echo(f"Input data: {json.dumps(input_data, indent=2)}")
    click.echo("Note: Full agent runtime integration pending framework setup")


@cli.command()
def validate():
    """Validate the agent configuration."""
    click.echo("Validating agent configuration...")

    if default_agent.validate():
        click.echo("✓ Agent configuration is valid")
        click.echo(f"✓ Goal: {goal.name}")
        click.echo(f"✓ Nodes: {len(nodes)} defined")
        click.echo(f"✓ Edges: {len(edges)} defined")
        click.echo(f"✓ Entry node: {entry_node}")
    else:
        click.echo("✗ Agent configuration is invalid")
        exit(1)


@cli.command()
def info():
    """Show agent information."""
    from .agent import metadata

    click.echo("Universal Document Intake & Action Agent")
    click.echo("=" * 45)
    click.echo(f"Version: {metadata['version']}")
    click.echo(f"Description: {metadata['description']}")
    click.echo()
    click.echo("Supported Formats:")
    for fmt in metadata['supported_formats']:
        click.echo(f"  • {fmt}")
    click.echo()
    click.echo("Supported Categories:")
    for cat in metadata['supported_categories']:
        click.echo(f"  • {cat}")


@cli.command()
def test():
    """Run basic tests on the agent."""
    click.echo("Running basic agent tests...")

    # Test 1: Validation
    if not default_agent.validate():
        click.echo("✗ Agent validation failed")
        return
    click.echo("✓ Agent validation passed")

    # Test 2: Node definitions
    node_ids = {node.id for node in nodes}
    expected_nodes = {"intake", "classify", "extract", "merge", "review"}
    if not expected_nodes.issubset(node_ids):
        click.echo(f"✗ Missing expected nodes: {expected_nodes - node_ids}")
        return
    click.echo("✓ All expected nodes present")

    # Test 3: Edge connectivity (fanout/fanin pattern)
    edge_connections = {(edge.source, edge.target) for edge in edges}
    expected_edges = {
        ("intake", "classify"), ("intake", "extract"),  # fanout
        ("classify", "merge"), ("extract", "merge"),    # fanin
        ("merge", "review"), ("review", "intake")       # loop
    }
    if not expected_edges.issubset(edge_connections):
        click.echo(f"✗ Missing expected edges: {expected_edges - edge_connections}")
        return
    click.echo("✓ All expected edges present (fanout/fanin pattern)")

    # Test 4: Advanced features
    try:
        from .evolution import get_evolution_tracker
        from .budget_control import get_budget_controller
        click.echo("✓ Self-evolution system available")
        click.echo("✓ Budget control system available")
    except ImportError as e:
        click.echo(f"✗ Advanced features missing: {e}")
        return

    click.echo("✓ All basic tests passed")


if __name__ == "__main__":
    cli()