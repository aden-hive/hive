from argparse import ArgumentParser
import asyncio
import json
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.prompt import Prompt

from framework.builder.workflow import GraphBuilder
from framework.graph.goal import Goal, SuccessCriterion

console = Console()

def register_preview_commands(subparsers):
    """Register preview commands."""
    parser = subparsers.add_parser("preview", help="Preview agent architecture from a goal description")
    parser.add_argument("goal", help="Description of the goal")
    parser.add_argument("--name", help="Name of the agent", default="preview-agent")
    parser.add_argument("--criteria", help="Comma-separated success criteria", default="")
    parser.set_defaults(func=handle_preview)

def _ask(message, choices=None, default=None):
    """A robust prompt that works in non-interactive environments."""
    import sys
    if sys.stdin.isatty():
        return Prompt.ask(message, choices=choices, default=default)
    
    # Fallback for pipes
    console.print(f"[dim](Non-interactive: reading stdin for '{message}')...[/dim]")
    try:
        line = sys.stdin.readline().strip().lower()
        choice = line[0] if line else (default[0] if default else "y")
        # Validate simple 1-char choices
        if choices and choice not in [c[0].lower() for c in choices]:
             choice = default[0].lower() if default else choices[0].lower()
        return choice
    except (EOFError, IndexError):
        return default[0].lower() if default else (choices[0].lower() if choices else "y")

def handle_preview(args):
    """Handle the preview command."""
    current_goal = args.goal
    current_name = args.name

    while True:
        # Create a goal
        criteria = [
            SuccessCriterion(id=f"sc-{i}", description=c.strip(), metric="llm_judge", target=True)
            for i, c in enumerate(args.criteria.split(",")) if c.strip()
        ]
        
        # If no explicit criteria but goal is detailed, we might want to auto-extract (future)
        # For now, ensure at least one
        if not criteria:
            criteria.append(SuccessCriterion(id="default", description="Goal achieved", metric="llm_judge", target=True))
    
        goal = Goal(
            id="preview-goal",
            name=current_name,
            description=current_goal,
            success_criteria=criteria
        )
    
        # Initialize builder
        builder = GraphBuilder(name=current_name)
        builder.set_goal(goal)
        
        # Run preview
        console.print(f"[bold blue]Generating preview for goal:[/bold blue] {current_goal}")
        print("Generating preview...")
        result = asyncio.run(builder.generate_preview())
    
        if not result:
            console.print("[bold red]Failed to generate preview.[/bold red]")
            # allow retry logic...
            
            # Allow retry on failure
            if _ask("Retry with different goal?", choices=["y", "n"], default="y") == "y":
                import sys
                if sys.stdin.isatty():
                    current_goal = Prompt.ask("Enter refined goal description")
                else:
                    console.print("Enter refined goal description: ", end="", flush=True)
                    current_goal = sys.stdin.readline().strip() or current_goal
                continue
            return 1
    
        _display_preview(result)
        
        # Interactive Prompt
        console.print("\n[bold]What would you like to do?[/bold]")
        console.print("[y] Proceed (Generate Scaffold)")
        console.print("[n] Cancel / Exit")
        console.print("[r] Refine Goal (Enter new prompt)")
        
        choice = _ask("Select an option", choices=["y", "n", "r"], default="y")

        if choice == "n":
            console.print("[yellow]Cancelled.[/yellow]")
            return 0
        
        elif choice == "r":
            # Refinement needs a real string, so we try reading full line
            import sys
            if sys.stdin.isatty():
                current_goal = Prompt.ask("Enter refined goal description")
            else:
                console.print("Enter refined goal description: ", end="", flush=True)
                current_goal = sys.stdin.readline().strip() or current_goal
            console.print("[blue]Regenerating...[/blue]")
            continue
            
        elif choice == "y":
            _generate_agent_scaffold(builder, result, current_name)
            
            if _ask("Save preview report?", choices=["y", "n"], default="n") == "y":
                _save_preview_report(current_name, result)
            
            return 0
    
    return 0

def _generate_agent_scaffold(builder: GraphBuilder, preview, name):
    """Generate the agent scaffold from the preview."""
    from framework.graph.node import NodeSpec
    from framework.graph.edge import EdgeSpec, EdgeCondition

    console.print("\n[bold blue]Generating Agent Scaffold...[/bold blue]")

    # 1. Approve Goal (transitions to GOAL_APPROVED)
    builder.approve("Approved via CLI Preview")

    # 2. Add Nodes
    # Map preview nodes to NodeSpec
    node_id_map = {} # name -> id
    
    for p_node in preview.proposed_nodes:
        node_id = p_node.name.lower().replace(" ", "_")
        node_id_map[p_node.name] = node_id
        
        # Map node type
        node_type = p_node.node_type
        if node_type == "llm_generate":
             # Deprecated type, map to llm_tool_use with no tools or event_loop
             node_type = "llm_tool_use" 
        
        spec = NodeSpec(
            id=node_id,
            name=p_node.name,
            description=p_node.purpose,
            node_type=node_type,
            # Defaults
            input_keys=[],
            output_keys=[],
            max_retries=3
        )
        
        builder.add_node(spec)
        # Auto-approve nodes for scaffolding
        builder.validate() 
        builder.approve(f"Scaffolded node {node_id}")

    # 3. Add Edges
    for p_edge in preview.proposed_edges:
        source_id = node_id_map.get(p_edge.source)
        target_id = node_id_map.get(p_edge.target)
        
        if not source_id or not target_id:
            console.print(f"[red]Skipping edge {p_edge.source}->{p_edge.target}: Node not found[/red]")
            continue

        edge_id = f"{source_id}_to_{target_id}"
        
        # Map condition
        cond = EdgeCondition.ALWAYS
        if p_edge.condition_type == "on_success":
            cond = EdgeCondition.ON_SUCCESS
        elif p_edge.condition_type == "on_failure":
            cond = EdgeCondition.ON_FAILURE
        elif p_edge.condition_type == "conditional":
            cond = EdgeCondition.CONDITIONAL
        elif p_edge.condition_type == "llm_decide":
            cond = EdgeCondition.LLM_DECIDE

        spec = EdgeSpec(
            id=edge_id,
            source=source_id,
            target=target_id,
            condition=cond,
            description=p_edge.routing_summary
        )
        
        builder.add_edge(spec)
        builder.validate()
        builder.approve(f"Scaffolded edge {edge_id}")
    
    console.print(f"[green]✓ Added {len(preview.proposed_nodes)} nodes and {len(preview.proposed_edges)} edges to build session.[/green]")
    
    session_file = builder.storage_path / f"{builder.session.id}.json"
    console.print(f"[green]Session saved to: {session_file}[/green]")
    console.print("[dim]You can continue building with: hive build --resume <session_id>[/dim]")

    # Generate Python code
    graph = builder._build_graph()
    code = builder._generate_code(graph)
    
    output_file = f"{name.lower().replace(' ', '_')}.py"
    with open(output_file, "w") as f:
        f.write(code)
    console.print(f"[bold green]✓ Agent scaffold saved to {output_file}[/bold green]")


def _save_preview_report(name, preview):
    """Save preview as markdown."""
    filename = f"{name}_preview_report.md"
    content = f"# Agent Preview: {name}\n\n"
    content += f"**Goal**: {preview.goal_summary}\n\n"
    content += "## Nodes\n| Name | Type | Purpose |\n|---|---|---|\n"
    for n in preview.proposed_nodes:
        content += f"| {n.name} | {n.node_type} | {n.purpose} |\n"
    
    content += "\n## Edges\n"
    for e in preview.proposed_edges:
        content += f"- **{e.source}** -> **{e.target}**: {e.routing_summary} ({e.condition_type})\n"
        
    with open(filename, "w") as f:
        f.write(content)
    console.print(f"[green]Report saved to {filename}[/green]")

def _display_preview(preview):
    """Render the preview to the console using Rich."""
    console.print("\n")
    console.print(Panel(Markdown(f"## {preview.goal_summary}"), title="Goal Summary", border_style="blue"))
    
    # Nodes Table
    table = Table(title="Proposed Nodes", border_style="cyan")
    table.add_column("Node Name", style="cyan", no_wrap=True)
    table.add_column("Type", style="magenta")
    table.add_column("Purpose", style="green")
    table.add_column("Est. Cost", justify="right")

    for node in preview.proposed_nodes:
        table.add_row(
            node.name, 
            node.node_type, 
            node.purpose, 
            str(node.estimated_llm_calls)
        )
    console.print(table)

    # Output Edges (Generic List for now)
    console.print("\n[bold]Flow Logic:[/bold]")
    for edge in preview.proposed_edges:
        console.print(f" • [cyan]{edge.source}[/cyan] -> [cyan]{edge.target}[/cyan]: {edge.routing_summary} ([i]{edge.condition_type}[/i])")

    # Risks
    if preview.risk_flags:
        console.print("\n[bold red]Risk Analysis:[/bold red]")
        for risk in preview.risk_flags:
            icon = "⚠️" if risk.severity == "warning" else "ℹ️"
            console.print(f" {icon} [{risk.severity.upper()}] {risk.message}")
            console.print(f"    [dim]Suggestion: {risk.suggestion}[/dim]")

    # Cost Estimates
    console.print("\n[bold]Estimates:[/bold]")
    console.print(f" • Complexity: {preview.estimated_complexity}")
    console.print(f" • Build Cost: ${preview.estimated_generation_cost:.4f}")
    console.print(f" • Run Cost:   ${preview.estimated_per_run_cost:.4f}/run")
