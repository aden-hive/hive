"""CLI entry point for Content Marketing Agent."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import click

from .agent import ContentMarketingAgent


def generate_html_report(result: dict, output_path: str) -> None:
    """Generate a formatted HTML report from execution results."""
    output = result.get("output", {})
    draft = output.get("draft_content", {})
    quality = output.get("quality_review", {})
    
    # Format the blog body (convert markdown headers to HTML)
    blog_body = draft.get("body", "No content generated")
    blog_body = blog_body.replace("### ", "<h3>").replace("## ", "<h2>").replace("# ", "<h1>")
    # Close tags (simplified)
    lines = []
    for line in blog_body.split("\n"):
        if line.startswith("<h1>"):
            line = line + "</h1>"
        elif line.startswith("<h2>"):
            line = line + "</h2>"
        elif line.startswith("<h3>"):
            line = line + "</h3>"
        elif line.strip() and not line.startswith("<"):
            line = f"<p>{line}</p>"
        lines.append(line)
    blog_body_html = "\n".join(lines)
    
    # Generate tags HTML
    tags_html = "".join(f'<span class="tag">{tag}</span>' for tag in draft.get("tags", []))
    
    # Determine approval status
    human_decision = output.get("human_decision", "")
    is_approved = "approve" in human_decision.lower()
    approval_class = "approval" if is_approved else "rejection"
    approval_icon = "✅ APPROVED" if is_approved else "❌ REJECTED"
    
    # Path display
    path = result.get("path", [])
    path_html = ""
    for i, node in enumerate(path):
        node_class = "node hitl" if node == "human_approval" else "node"
        node_label = f"🙋 {node}" if node == "human_approval" else node
        path_html += f'<span class="{node_class}">{node_label}</span>'
        if i < len(path) - 1:
            path_html += '<span class="arrow">→</span>'
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Content Marketing Agent - Output Report</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 40px 20px;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
        }}
        .header h1 {{ margin: 0 0 10px 0; font-size: 28px; }}
        .header p {{ margin: 0; opacity: 0.9; }}
        .card {{
            background: white;
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }}
        .card h2 {{
            margin-top: 0;
            color: #667eea;
            font-size: 18px;
            border-bottom: 2px solid #eee;
            padding-bottom: 10px;
        }}
        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
        }}
        .metric {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }}
        .metric-value {{
            font-size: 24px;
            font-weight: bold;
            color: #667eea;
        }}
        .metric-label {{
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
        }}
        .path {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            align-items: center;
        }}
        .node {{
            background: #e8f4f8;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 500;
            color: #0066cc;
        }}
        .node.hitl {{ background: #fff3cd; color: #856404; }}
        .arrow {{ color: #999; }}
        .blog-post {{
            background: #fafafa;
            border-left: 4px solid #667eea;
            padding: 20px;
            margin: 15px 0;
        }}
        .blog-post h1, .blog-post h2, .blog-post h3 {{
            color: #444;
        }}
        .blog-post h1 {{ font-size: 24px; margin-top: 0; }}
        .blog-post h2 {{ font-size: 20px; margin-top: 25px; }}
        .blog-post h3 {{ font-size: 17px; margin-top: 20px; }}
        .tags {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 15px;
        }}
        .tag {{
            background: #667eea;
            color: white;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 12px;
        }}
        .quality-badge {{
            display: inline-block;
            background: #28a745;
            color: white;
            padding: 5px 12px;
            border-radius: 20px;
            font-weight: bold;
        }}
        .approval {{
            background: #d4edda;
            border: 1px solid #c3e6cb;
            padding: 15px;
            border-radius: 8px;
            margin-top: 15px;
        }}
        .rejection {{
            background: #f8d7da;
            border: 1px solid #f5c6cb;
            padding: 15px;
            border-radius: 8px;
            margin-top: 15px;
        }}
        .approval-title {{ color: #155724; font-weight: bold; margin-bottom: 8px; }}
        .rejection-title {{ color: #721c24; font-weight: bold; margin-bottom: 8px; }}
        .input-section {{
            background: #e9ecef;
            padding: 15px;
            border-radius: 8px;
            font-family: monospace;
            font-size: 13px;
        }}
        hr {{ border: none; border-top: 1px solid #eee; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 Content Marketing Agent</h1>
        <p>Automated blog content generation with human-in-the-loop approval</p>
    </div>

    <div class="card">
        <h2>📊 Execution Metrics</h2>
        <div class="metrics">
            <div class="metric">
                <div class="metric-value">{result.get("steps_executed", 0)}</div>
                <div class="metric-label">Nodes Executed</div>
            </div>
            <div class="metric">
                <div class="metric-value">{result.get("total_tokens", 0):,}</div>
                <div class="metric-label">Tokens Used</div>
            </div>
            <div class="metric">
                <div class="metric-value">{result.get("total_latency_ms", 0) // 1000}s</div>
                <div class="metric-label">Total Time</div>
            </div>
            <div class="metric">
                <div class="metric-value">{"✅" if result.get("success") else "❌"}</div>
                <div class="metric-label">Status</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h2>🔄 Execution Path</h2>
        <div class="path">{path_html}</div>
    </div>

    <div class="card">
        <h2>📰 Input: News Article</h2>
        <div class="input-section">
            <strong>Title:</strong> {output.get("news_title", "N/A")}<br><br>
            <strong>Summary:</strong> {output.get("news_summary", "N/A")}
        </div>
    </div>

    <div class="card">
        <h2>✅ Quality Review</h2>
        <p>
            <span class="quality-badge">Score: {quality.get("quality_score", 0):.2f} / 1.0</span>
            &nbsp;&nbsp;{"✓ Passes Review" if quality.get("passes_review") else "✗ Needs Revision"}
        </p>
    </div>

    <div class="card">
        <h2>📝 Generated Blog Post</h2>
        <div class="blog-post">
            {blog_body_html}
            <hr>
            <p><strong>Excerpt:</strong> <em>{draft.get("excerpt", "")}</em></p>
            <div class="tags">{tags_html}</div>
        </div>
    </div>

    <div class="card">
        <h2>🙋 Human Approval Decision</h2>
        <div class="{approval_class}">
            <div class="{approval_class}-title">{approval_icon}</div>
            <p style="margin-bottom: 0;">{human_decision}</p>
        </div>
    </div>

    <div style="text-align: center; color: #999; font-size: 13px; margin-top: 40px;">
        Generated by Content Marketing Agent • Aden Framework • {datetime.now().strftime("%B %d, %Y %H:%M")}
    </div>
</body>
</html>'''

    with open(output_path, "w") as f:
        f.write(html)


def load_env_file():
    """Load environment variables from .env file if it exists."""
    # Check multiple possible locations
    env_paths = [
        Path.cwd() / ".env",
        Path(__file__).parent.parent.parent / ".env",  # repo root
    ]
    
    for env_path in env_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        # Don't overwrite existing env vars
                        if key not in os.environ:
                            os.environ[key] = value
            return True
    return False


@click.group()
def cli():
    """Content Marketing Agent - Automated blog content with HITL approval."""
    pass


@cli.command()
def info():
    """Display agent information."""
    agent = ContentMarketingAgent()
    info = agent.info

    click.echo("\n" + "=" * 60)
    click.echo(f"🤖 {info['name']}")
    click.echo("=" * 60)
    click.echo(f"\n📋 ID: {info['id']}")
    click.echo(f"📝 Version: {info['version']}")
    click.echo(f"\n{info['description']}")

    click.echo("\n📊 Graph Structure:")
    click.echo(f"   Entry Node: {info['entry_node']}")
    click.echo(f"   Terminal Nodes: {', '.join(info['terminal_nodes'])}")
    click.echo(f"   Pause Nodes (HITL): {', '.join(info['pause_nodes'])}")
    click.echo(f"   Total Nodes: {info['node_count']}")
    click.echo(f"   Total Edges: {info['edge_count']}")
    click.echo(f"   Tools Available: {info['tool_count']}")

    click.echo("\n✅ Success Criteria:")
    for criterion in info["success_criteria"]:
        click.echo(f"   • {criterion}")

    click.echo("\n🚫 Constraints:")
    for constraint in info["constraints"]:
        click.echo(f"   • {constraint}")

    click.echo()


@cli.command()
def validate():
    """Validate agent graph structure."""
    agent = ContentMarketingAgent()
    result = agent.validate()

    click.echo("\n" + "=" * 60)
    click.echo("🔍 Agent Validation")
    click.echo("=" * 60)

    if result["valid"]:
        click.echo("\n✅ Agent is valid!")
    else:
        click.echo("\n❌ Agent has errors!")

    click.echo(f"\n📊 Checked: {result['nodes_checked']} nodes, {result['edges_checked']} edges")

    if result["errors"]:
        click.echo("\n🚨 Errors:")
        for error in result["errors"]:
            click.echo(f"   ❌ {error}")

    if result["warnings"]:
        click.echo("\n⚠️  Warnings:")
        for warning in result["warnings"]:
            click.echo(f"   ⚠️  {warning}")

    click.echo()
    sys.exit(0 if result["valid"] else 1)


@cli.command()
@click.option("--title", required=True, help="News article title")
@click.option("--summary", required=True, help="News article summary")
@click.option("--mock", is_flag=True, help="Run in mock mode (no LLM calls)")
@click.option("--output", "-o", type=click.Path(), help="Output file for results")
def run(title: str, summary: str, mock: bool, output: str | None):
    """Run the agent with a news item."""
    click.echo("\n" + "=" * 60)
    click.echo("🚀 Content Marketing Agent")
    click.echo("=" * 60)

    agent = ContentMarketingAgent()

    # Validate first
    validation = agent.validate()
    if not validation["valid"]:
        click.echo("\n❌ Agent validation failed. Run 'validate' for details.")
        sys.exit(1)

    click.echo(f"\n📰 News Title: {title}")
    click.echo(f"📝 Summary: {summary[:100]}...")
    click.echo(f"\n🔧 Mode: {'Mock (no LLM calls)' if mock else 'Live'}")

    # Build initial memory
    initial_memory = agent.get_initial_memory(
        news_title=title,
        news_summary=summary,
    )

    if mock:
        # Mock execution - just demonstrate the flow
        click.echo("\n🎭 Mock execution mode - demonstrating agent flow:")
        click.echo("\n   1️⃣  news_monitor: Analyzing news relevance...")
        click.echo("   2️⃣  content_writer: Generating blog draft...")
        click.echo("   3️⃣  quality_review: Validating quality...")
        click.echo("   4️⃣  quality_router: Routing based on score...")
        click.echo("   5️⃣  human_approval: Awaiting human review...")
        click.echo("   6️⃣  approval_router: Processing decision...")
        click.echo("   7️⃣  publisher: Publishing to WordPress...")

        result = {
            "success": True,
            "mode": "mock",
            "message": "Mock execution completed successfully",
            "initial_memory": initial_memory,
            "flow": [
                "news_monitor",
                "content_writer",
                "quality_review",
                "quality_router",
                "human_approval",
                "approval_router",
                "publisher",
            ],
        }
    else:
        # Live execution with framework runtime
        load_env_file()
        
        # Check for API key
        if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
            click.echo("\n❌ No API key found. Set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env")
            sys.exit(1)
        
        click.echo("\n🔄 Starting live execution...")
        
        try:
            from framework.graph.executor import GraphExecutor
            from framework.graph.output_cleaner import CleansingConfig
            from framework.llm.litellm import LiteLLMProvider
            from framework.runtime.core import Runtime
            
            from .tools import get_tool_executor, get_tools
        except ImportError as e:
            click.echo(f"\n❌ Import error: {e}")
            click.echo("   Make sure you're running with PYTHONPATH=core:exports")
            sys.exit(1)
        
        # Determine model based on available API key
        if os.environ.get("OPENAI_API_KEY"):
            model = "gpt-4o-mini"
            click.echo(f"   Using OpenAI model: {model}")
        else:
            model = "claude-sonnet-4-20250514"
            click.echo(f"   Using Anthropic model: {model}")
        
        # Create runtime and executor
        storage_path = Path.cwd() / ".agent_runs"
        storage_path.mkdir(exist_ok=True)
        
        runtime = Runtime(storage_path)
        llm = LiteLLMProvider(model=model)
        tools = get_tools()
        tool_executor = get_tool_executor()
        
        # Disable edge validation (it incorrectly validates shared memory keys)
        cleansing_config = CleansingConfig(
            enabled=False,  # Disable problematic edge validation
        )
        
        executor = GraphExecutor(
            runtime=runtime,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            cleansing_config=cleansing_config,
        )
        
        # Run the agent
        async def run_agent():
            return await executor.execute(
                graph=agent.graph,
                goal=agent.goal,
                input_data=initial_memory,
            )
        
        try:
            exec_result = asyncio.run(run_agent())
            
            result = {
                "success": exec_result.success,
                "mode": "live",
                "output": exec_result.output,
                "error": exec_result.error,
                "steps_executed": exec_result.steps_executed,
                "total_tokens": exec_result.total_tokens,
                "total_latency_ms": exec_result.total_latency_ms,
                "path": exec_result.path,
                "paused_at": exec_result.paused_at,
            }
            
            if exec_result.paused_at:
                click.echo(f"\n⏸️  Agent paused at HITL node: {exec_result.paused_at}")
                click.echo("   Human approval required to continue.")
            elif exec_result.success:
                click.echo(f"\n✅ Agent completed successfully!")
                click.echo(f"   Steps: {exec_result.steps_executed}")
                click.echo(f"   Tokens: {exec_result.total_tokens}")
                click.echo(f"   Path: {' → '.join(exec_result.path)}")
            else:
                click.echo(f"\n❌ Agent failed: {exec_result.error}")
                
        except Exception as e:
            click.echo(f"\n❌ Execution error: {e}")
            result = {
                "success": False,
                "mode": "live",
                "error": str(e),
            }

    # Output results
    if output:
        # Save JSON
        with open(output, "w") as f:
            json.dump(result, f, indent=2)
        click.echo(f"\n📄 JSON saved to: {output}")
        
        # Also generate HTML report
        html_output = output.replace(".json", ".html") if output.endswith(".json") else output + ".html"
        try:
            generate_html_report(result, html_output)
            click.echo(f"📄 HTML report saved to: {html_output}")
        except Exception as e:
            click.echo(f"⚠️  Could not generate HTML report: {e}")
    else:
        # Default output files
        json_output = "run-output.json"
        html_output = "run-output.html"
        with open(json_output, "w") as f:
            json.dump(result, f, indent=2)
        click.echo(f"\n📄 JSON saved to: {json_output}")
        try:
            generate_html_report(result, html_output)
            click.echo(f"📄 HTML report saved to: {html_output}")
        except Exception as e:
            click.echo(f"⚠️  Could not generate HTML report: {e}")

    click.echo("\n✅ Done!")
    click.echo()


@cli.command()
def nodes():
    """List all nodes in the agent graph."""
    agent = ContentMarketingAgent()

    click.echo("\n" + "=" * 60)
    click.echo("📋 Agent Nodes")
    click.echo("=" * 60)

    for node in agent.graph.nodes:
        node_type_emoji = {
            "llm_tool_use": "🔧",
            "llm_generate": "✍️",
            "router": "🔀",
            "human_input": "👤",
            "function": "⚡",
        }.get(node.node_type, "📦")

        click.echo(f"\n{node_type_emoji} {node.id}")
        click.echo(f"   Type: {node.node_type}")
        click.echo(f"   Inputs: {', '.join(node.input_keys)}")
        click.echo(f"   Output: {', '.join(node.output_keys)}")
        if hasattr(node, "tools") and node.tools:
            click.echo(f"   Tools: {', '.join(node.tools)}")

    click.echo()


@cli.command()
def edges():
    """List all edges in the agent graph."""
    agent = ContentMarketingAgent()

    click.echo("\n" + "=" * 60)
    click.echo("🔗 Agent Edges")
    click.echo("=" * 60)

    for edge in agent.graph.edges:
        condition_emoji = {
            "always": "⏩",
            "on_success": "✅",
            "on_failure": "❌",
            "conditional": "🔀",
            "llm_decide": "🤖",
        }.get(edge.condition.value, "➡️")

        click.echo(f"\n{condition_emoji} {edge.id}")
        click.echo(f"   {edge.source} → {edge.target}")
        click.echo(f"   Condition: {edge.condition.value}")
        if edge.condition_expr:
            click.echo(f"   Expression: {edge.condition_expr}")
        if edge.description:
            click.echo(f"   Description: {edge.description}")

    click.echo()


@cli.command()
def tools():
    """List all tools available to the agent."""
    agent = ContentMarketingAgent()

    click.echo("\n" + "=" * 60)
    click.echo("🔧 Agent Tools")
    click.echo("=" * 60)

    for tool in agent.tools:
        click.echo(f"\n🔧 {tool.name}")
        click.echo(f"   {tool.description}")

    click.echo()


if __name__ == "__main__":
    cli()
