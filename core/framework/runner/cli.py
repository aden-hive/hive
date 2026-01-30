"""CLI commands for agent runner."""

import argparse
import asyncio
import json
import sys
from pathlib import Path


def register_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register runner commands with the main CLI."""

    # run command
    run_parser = subparsers.add_parser(
        "run",
        help="Run an exported agent",
        description="Execute an exported agent with the given input.",
    )
    run_parser.add_argument(
        "agent_path",
        type=str,
        help="Path to agent folder (containing agent.json)",
    )
    run_parser.add_argument(
        "--input",
        "-i",
        type=str,
        help="Input context as JSON string",
    )
    run_parser.add_argument(
        "--input-file",
        "-f",
        type=str,
        help="Input context from JSON file",
    )
    run_parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in mock mode (no real LLM calls)",
    )
    run_parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Write results to file instead of stdout",
    )
    run_parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only output the final result JSON",
    )
    run_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed execution logs (steps, LLM calls, etc.)",
    )
    run_parser.set_defaults(func=cmd_run)

    # info command
    info_parser = subparsers.add_parser(
        "info",
        help="Show agent information",
        description="Display details about an exported agent.",
    )
    info_parser.add_argument(
        "agent_path",
        type=str,
        help="Path to agent folder (containing agent.json)",
    )
    info_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    info_parser.set_defaults(func=cmd_info)

    # validate command
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate an exported agent",
        description="Check that an exported agent is valid and runnable.",
    )
    validate_parser.add_argument(
        "agent_path",
        type=str,
        help="Path to agent folder (containing agent.json)",
    )
    validate_parser.set_defaults(func=cmd_validate)

    # list command
    list_parser = subparsers.add_parser(
        "list",
        help="List available agents",
        description="List all exported agents in a directory.",
    )
    list_parser.add_argument(
        "directory",
        type=str,
        nargs="?",
        default="exports",
        help="Directory to search (default: exports)",
    )
    list_parser.set_defaults(func=cmd_list)

    # dispatch command (multi-agent)
    dispatch_parser = subparsers.add_parser(
        "dispatch",
        help="Dispatch request to multiple agents",
        description="Route a request to the best agent(s) using the orchestrator.",
    )
    dispatch_parser.add_argument(
        "agents_dir",
        type=str,
        nargs="?",
        default="exports",
        help="Directory containing agent folders (default: exports)",
    )
    dispatch_parser.add_argument(
        "--input",
        "-i",
        type=str,
        required=True,
        help="Input context as JSON string",
    )
    dispatch_parser.add_argument(
        "--intent",
        type=str,
        help="Description of what you want to accomplish",
    )
    dispatch_parser.add_argument(
        "--agents",
        "-a",
        type=str,
        nargs="+",
        help="Specific agent names to use (default: all in directory)",
    )
    dispatch_parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only output the final result JSON",
    )
    dispatch_parser.set_defaults(func=cmd_dispatch)

    # shell command (interactive agent session)
    shell_parser = subparsers.add_parser(
        "shell",
        help="Interactive agent session",
        description="Start an interactive REPL session with agents.",
    )
    shell_parser.add_argument(
        "agent_path",
        type=str,
        nargs="?",
        help="Path to agent folder (optional, can select interactively)",
    )
    shell_parser.add_argument(
        "--agents-dir",
        type=str,
        default="exports",
        help="Directory containing agents (default: exports)",
    )
    shell_parser.add_argument(
        "--multi",
        action="store_true",
        help="Enable multi-agent mode with orchestrator",
    )
    shell_parser.add_argument(
        "--no-approve",
        action="store_true",
        help="Disable human-in-the-loop approval (auto-approve all steps)",
    )
    shell_parser.set_defaults(func=cmd_shell)

    # version command
    version_parser = subparsers.add_parser(
        "version",
        help="Manage agent versions",
        description="Version control for agent graphs and goals.",
    )
    version_subparsers = version_parser.add_subparsers(dest="version_command", required=True)

    # version save
    save_parser = version_subparsers.add_parser(
        "save",
        help="Save a new version",
        description="Create a new version of an agent.",
    )
    save_parser.add_argument("agent_path", type=str, help="Path to agent folder")
    save_parser.add_argument(
        "--description", "-d", type=str, required=True, help="Description of changes"
    )
    save_parser.add_argument(
        "--bump",
        "-b",
        type=str,
        choices=["major", "minor", "patch"],
        default="patch",
        help="Version bump type (default: patch)",
    )
    save_parser.add_argument("--tag", "-t", type=str, help="Optional tag for this version")
    save_parser.add_argument("--created-by", type=str, help="User creating this version")
    save_parser.set_defaults(func=cmd_version_save)

    # version list
    list_versions_parser = version_subparsers.add_parser(
        "list", help="List all versions", description="Show all versions of an agent."
    )
    list_versions_parser.add_argument("agent_id", type=str, help="Agent identifier")
    list_versions_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )
    list_versions_parser.set_defaults(func=cmd_version_list)

    # version rollback
    rollback_parser = version_subparsers.add_parser(
        "rollback",
        help="Rollback to a version",
        description="Restore an agent to a previous version.",
    )
    rollback_parser.add_argument("agent_id", type=str, help="Agent identifier")
    rollback_parser.add_argument("version", type=str, help="Version to rollback to")
    rollback_parser.add_argument(
        "--export",
        "-e",
        type=str,
        help="Export path to save rolled-back agent (default: exports/{agent_id})",
    )
    rollback_parser.set_defaults(func=cmd_version_rollback)

    # version diff
    diff_parser = version_subparsers.add_parser(
        "diff",
        help="Compare versions",
        description="Show differences between two versions.",
    )
    diff_parser.add_argument("agent_id", type=str, help="Agent identifier")
    diff_parser.add_argument("from_version", type=str, help="Starting version")
    diff_parser.add_argument("to_version", type=str, help="Target version")
    diff_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )
    diff_parser.set_defaults(func=cmd_version_diff)

    # version tag
    tag_parser = version_subparsers.add_parser(
        "tag", help="Tag a version", description="Add a tag to a version (e.g., production)."
    )
    tag_parser.add_argument("agent_id", type=str, help="Agent identifier")
    tag_parser.add_argument("version", type=str, help="Version to tag")
    tag_parser.add_argument("tag", type=str, help="Tag name")
    tag_parser.set_defaults(func=cmd_version_tag)

    # version ab-test
    ab_test_parser = version_subparsers.add_parser(
        "ab-test",
        help="Create A/B test",
        description="Set up A/B testing between two versions.",
    )
    ab_test_parser.add_argument("agent_id", type=str, help="Agent identifier")
    ab_test_parser.add_argument("version_a", type=str, help="First version")
    ab_test_parser.add_argument("version_b", type=str, help="Second version")
    ab_test_parser.add_argument(
        "--split",
        "-s",
        type=float,
        default=0.5,
        help="Traffic split for version A (0.0-1.0, default: 0.5)",
    )
    ab_test_parser.add_argument(
        "--metrics",
        "-m",
        nargs="+",
        help="Metrics to track (e.g., response_time success_rate)",
    )
    ab_test_parser.set_defaults(func=cmd_version_ab_test)


def cmd_run(args: argparse.Namespace) -> int:
    """Run an exported agent."""
    import logging

    from framework.runner import AgentRunner

    # Set logging level (quiet by default for cleaner output)
    if args.quiet:
        logging.basicConfig(level=logging.ERROR, format="%(message)s")
    elif getattr(args, "verbose", False):
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    else:
        logging.basicConfig(level=logging.WARNING, format="%(message)s")

    # Load input context
    context = {}
    if args.input:
        try:
            context = json.loads(args.input)
        except json.JSONDecodeError as e:
            print(f"Error parsing --input JSON: {e}", file=sys.stderr)
            return 1
    elif args.input_file:
        try:
            with open(args.input_file) as f:
                context = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error reading input file: {e}", file=sys.stderr)
            return 1

    # Load and run agent
    try:
        runner = AgentRunner.load(
            args.agent_path,
            mock_mode=args.mock,
            model=getattr(args, "model", "claude-haiku-4-5-20251001"),
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Auto-inject user_id if the agent expects it but it's not provided
    entry_input_keys = runner.graph.nodes[0].input_keys if runner.graph.nodes else []
    if "user_id" in entry_input_keys and context.get("user_id") is None:
        import os

        context["user_id"] = os.environ.get("USER", "default_user")

    if not args.quiet:
        info = runner.info()
        print(f"Agent: {info.name}")
        print(f"Goal: {info.goal_name}")
        print(f"Steps: {info.node_count}")
        print(f"Input: {json.dumps(context)}")
        print()
        print("=" * 60)
        print("Executing agent...")
        print("=" * 60)
        print()

    # Run the agent
    result = asyncio.run(runner.run(context))

    # Format output
    output = {
        "success": result.success,
        "steps_executed": result.steps_executed,
        "output": result.output,
    }
    if result.error:
        output["error"] = result.error
    if result.paused_at:
        output["paused_at"] = result.paused_at

    # Output results
    if args.output:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2, default=str)
        if not args.quiet:
            print(f"Results written to {args.output}")
    else:
        if args.quiet:
            print(json.dumps(output, indent=2, default=str))
        else:
            print()
            print("=" * 60)
            status_str = "SUCCESS" if result.success else "FAILED"
            print(f"Status: {status_str}")
            print(f"Steps executed: {result.steps_executed}")
            print(f"Path: {' → '.join(result.path)}")
            print("=" * 60)

            if result.success:
                print("\n--- Results ---")
                # Show only meaningful output keys (skip internal/intermediate values)
                meaningful_keys = ["final_response", "response", "result", "answer", "output"]

                # Try to find the most relevant output
                shown = False
                for key in meaningful_keys:
                    if key in result.output:
                        value = result.output[key]
                        if isinstance(value, str) and len(value) > 10:
                            print(value)
                            shown = True
                            break
                        elif isinstance(value, (dict, list)):
                            print(json.dumps(value, indent=2, default=str))
                            shown = True
                            break

                # If no meaningful key found, show all non-internal keys
                if not shown:
                    for key, value in result.output.items():
                        if not key.startswith("_") and key not in [
                            "user_id",
                            "request",
                            "memory_loaded",
                            "user_profile",
                            "recent_context",
                        ]:
                            if isinstance(value, (dict, list)):
                                print(f"\n{key}:")
                                value_str = json.dumps(value, indent=2, default=str)
                                if len(value_str) > 300:
                                    value_str = value_str[:300] + "..."
                                print(value_str)
                            else:
                                val_str = str(value)
                                if len(val_str) > 200:
                                    val_str = val_str[:200] + "..."
                                print(f"{key}: {val_str}")
            elif result.error:
                print(f"\nError: {result.error}")

    runner.cleanup()
    return 0 if result.success else 1


def cmd_info(args: argparse.Namespace) -> int:
    """Show agent information."""
    from framework.runner import AgentRunner

    try:
        runner = AgentRunner.load(args.agent_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    info = runner.info()

    if args.json:
        print(
            json.dumps(
                {
                    "name": info.name,
                    "description": info.description,
                    "goal_name": info.goal_name,
                    "goal_description": info.goal_description,
                    "node_count": info.node_count,
                    "nodes": info.nodes,
                    "edges": info.edges,
                    "success_criteria": info.success_criteria,
                    "constraints": info.constraints,
                    "required_tools": info.required_tools,
                    "has_tools_module": info.has_tools_module,
                },
                indent=2,
            )
        )
    else:
        print(f"Agent: {info.name}")
        print(f"Description: {info.description}")
        print()
        print(f"Goal: {info.goal_name}")
        print(f"  {info.goal_description}")
        print()
        print(f"Nodes ({info.node_count}):")
        for node in info.nodes:
            inputs = f" [in: {', '.join(node['input_keys'])}]" if node.get("input_keys") else ""
            outputs = f" [out: {', '.join(node['output_keys'])}]" if node.get("output_keys") else ""
            print(f"  - {node['id']}: {node['name']}{inputs}{outputs}")
        print()
        print(f"Success Criteria ({len(info.success_criteria)}):")
        for sc in info.success_criteria:
            print(f"  - {sc['description']} ({sc['metric']} = {sc['target']})")
        print()
        print(f"Constraints ({len(info.constraints)}):")
        for c in info.constraints:
            print(f"  - [{c['type']}] {c['description']}")
        print()
        print(f"Required Tools ({len(info.required_tools)}):")
        for tool in info.required_tools:
            status = "✓" if runner._tool_registry.has_tool(tool) else "✗"
            print(f"  {status} {tool}")
        print()
        print(f"Tools Module: {'✓ tools.py found' if info.has_tools_module else '✗ no tools.py'}")

    runner.cleanup()
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate an exported agent."""
    from framework.runner import AgentRunner

    try:
        runner = AgentRunner.load(args.agent_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    validation = runner.validate()

    if validation.valid:
        print("✓ Agent is valid")
    else:
        print("✗ Agent has errors:")
        for error in validation.errors:
            print(f"  ERROR: {error}")

    if validation.warnings:
        print("\nWarnings:")
        for warning in validation.warnings:
            print(f"  WARNING: {warning}")

    if validation.missing_tools:
        print("\nMissing tool implementations:")
        for tool in validation.missing_tools:
            print(f"  - {tool}")
        print("\nTo fix: Create tools.py in the agent folder or register tools programmatically")

    runner.cleanup()
    return 0 if validation.valid else 1


def cmd_list(args: argparse.Namespace) -> int:
    """List available agents."""
    from framework.runner import AgentRunner

    directory = Path(args.directory)
    if not directory.exists():
        # FIX: Handle missing directory gracefully on fresh install
        print(f"No agents found in {directory}")
        return 0

    agents = []
    for path in directory.iterdir():
        if path.is_dir() and (path / "agent.json").exists():
            try:
                runner = AgentRunner.load(path)
                info = runner.info()
                agents.append(
                    {
                        "path": str(path),
                        "name": info.name,
                        "description": info.description[:60] + "..."
                        if len(info.description) > 60
                        else info.description,
                        "nodes": info.node_count,
                        "tools": len(info.required_tools),
                    }
                )
                runner.cleanup()
            except Exception as e:
                agents.append(
                    {
                        "path": str(path),
                        "error": str(e),
                    }
                )

    if not agents:
        print(f"No agents found in {directory}")
        return 0

    print(f"Agents in {directory}:\n")
    for agent in agents:
        if "error" in agent:
            print(f"  {agent['path']}: ERROR - {agent['error']}")
        else:
            print(f"  {agent['name']}")
            print(f"    Path: {agent['path']}")
            print(f"    Description: {agent['description']}")
            print(f"    Steps: {agent['steps']}, Tools: {agent['tools']}")
            print()

    return 0


def cmd_dispatch(args: argparse.Namespace) -> int:
    """Dispatch request to multiple agents via orchestrator."""
    from framework.runner import AgentOrchestrator

    # Parse input
    try:
        context = json.loads(args.input)
    except json.JSONDecodeError as e:
        print(f"Error parsing --input JSON: {e}", file=sys.stderr)
        return 1

    # Find agents
    agents_dir = Path(args.agents_dir)
    if not agents_dir.exists():
        print(f"Directory not found: {agents_dir}", file=sys.stderr)
        return 1

    # Create orchestrator and register agents
    orchestrator = AgentOrchestrator()

    agent_paths = []
    if args.agents:
        # Use specific agents
        for agent_name in args.agents:
            agent_path = agents_dir / agent_name
            if not (agent_path / "agent.json").exists():
                print(f"Agent not found: {agent_path}", file=sys.stderr)
                return 1
            agent_paths.append((agent_name, agent_path))
    else:
        # Discover all agents
        for path in agents_dir.iterdir():
            if path.is_dir() and (path / "agent.json").exists():
                agent_paths.append((path.name, path))

    if not agent_paths:
        print(f"No agents found in {agents_dir}", file=sys.stderr)
        return 1

    # Register agents
    for name, path in agent_paths:
        try:
            orchestrator.register(name, path)
            if not args.quiet:
                print(f"Registered agent: {name}")
        except Exception as e:
            print(f"Failed to register {name}: {e}", file=sys.stderr)

    if not args.quiet:
        print()
        print(f"Input: {json.dumps(context)}")
        if args.intent:
            print(f"Intent: {args.intent}")
        print()
        print("=" * 60)
        print("Dispatching to agents...")
        print("=" * 60)
        print()

    # Dispatch
    result = asyncio.run(orchestrator.dispatch(context, intent=args.intent))

    # Output results
    if args.quiet:
        output = {
            "success": result.success,
            "handled_by": result.handled_by,
            "results": result.results,
            "error": result.error,
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        print()
        print("=" * 60)
        print(f"Success: {result.success}")
        print(f"Handled by: {', '.join(result.handled_by) or 'none'}")
        if result.error:
            print(f"Error: {result.error}")
        print("=" * 60)

        if result.results:
            print("\n--- Results by Agent ---")
            for agent_name, data in result.results.items():
                print(f"\n{agent_name}:")
                status = data.get("status", "unknown")
                print(f"  Status: {status}")
                if "completed_steps" in data:
                    print(f"  Steps: {len(data['completed_steps'])}")
                if "results" in data:
                    results_preview = json.dumps(data["results"], default=str)
                    if len(results_preview) > 200:
                        results_preview = results_preview[:200] + "..."
                    print(f"  Results: {results_preview}")

        if not args.quiet:
            print(f"\nMessage trace: {len(result.messages)} messages")

    orchestrator.cleanup()
    return 0 if result.success else 1


def _interactive_approval(request):
    """Interactive approval callback for HITL mode."""
    from framework.graph import ApprovalDecision, ApprovalResult

    print()
    print("=" * 60)
    print("🔔 APPROVAL REQUIRED")
    print("=" * 60)
    print(f"\nStep: {request.step_id}")
    print(f"Description: {request.step_description}")

    if request.approval_message:
        print(f"\nMessage: {request.approval_message}")

    if request.preview:
        print(f"\nPreview:\n{request.preview}")

    if request.context:
        print("\n--- Content to be sent ---")
        for key, value in request.context.items():
            print(f"\n[{key}]:")
            if isinstance(value, (dict, list)):
                import json

                value_str = json.dumps(value, indent=2, default=str)
                # Show more content for approval - up to 2000 chars
                if len(value_str) > 2000:
                    value_str = value_str[:2000] + "\n... (truncated)"
                print(value_str)
            else:
                value_str = str(value)
                if len(value_str) > 500:
                    value_str = value_str[:500] + "... (truncated)"
                print(f"  {value_str}")

    print()
    print("Options:")
    print("  [a] Approve - Execute as planned")
    print("  [r] Reject  - Skip this step")
    print("  [s] Skip all - Reject and skip dependent steps")
    print("  [x] Abort   - Stop entire execution")
    print()

    while True:
        try:
            choice = input("Your choice (a/r/s/x): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborting...")
            return ApprovalResult(decision=ApprovalDecision.ABORT, reason="User interrupted")

        if choice == "a":
            print("✓ Approved")
            return ApprovalResult(decision=ApprovalDecision.APPROVE)
        elif choice == "r":
            reason = input("Reason (optional): ").strip() or "Rejected by user"
            print(f"✗ Rejected: {reason}")
            return ApprovalResult(decision=ApprovalDecision.REJECT, reason=reason)
        elif choice == "s":
            print("✗ Rejected (skipping dependent steps)")
            return ApprovalResult(decision=ApprovalDecision.REJECT, reason="User skipped")
        elif choice == "x":
            reason = input("Reason (optional): ").strip() or "Aborted by user"
            print(f"⛔ Aborted: {reason}")
            return ApprovalResult(decision=ApprovalDecision.ABORT, reason=reason)
        else:
            print("Invalid choice. Please enter a, r, s, or x.")


def _format_natural_language_to_json(
    user_input: str, input_keys: list[str], agent_description: str, session_context: dict = None
) -> dict:
    """Use Haiku to convert natural language input to JSON based on agent's input schema."""
    import os

    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    # Build prompt for Haiku
    session_info = ""
    if session_context:
        # Extract the main field (usually 'objective') that we'll append to
        main_field = input_keys[0] if input_keys else "objective"
        existing_value = session_context.get(main_field, "")

        session_info = (
            f'\n\nExisting {main_field}: "{existing_value}"\n\n'
            f"The user is providing ADDITIONAL information. Append this new "
            f"information to the existing {main_field} to create an enriched, "
            "more detailed version."
        )

    prompt = f"""You are formatting user input for an agent that requires specific input fields.

Agent: {agent_description}

Required input fields: {", ".join(input_keys)}{session_info}

User input: {user_input}

{"If this is a follow-up, APPEND new info to the existing field value." if session_context else ""}

Output ONLY valid JSON, no explanation:"""

    try:
        message = client.messages.create(
            model="claude-3-5-haiku-20241022",  # Fast and cheap
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        json_str = message.content[0].text.strip()
        # Remove markdown code blocks if present
        if json_str.startswith("```"):
            json_str = json_str.split("```")[1]
            if json_str.startswith("json"):
                json_str = json_str[4:]
        json_str = json_str.strip()

        return json.loads(json_str)
    except Exception:
        # Fallback: try to infer the main field
        if len(input_keys) == 1:
            return {input_keys[0]: user_input}
        else:
            # Put it in the first field as fallback
            return {input_keys[0]: user_input}


def cmd_shell(args: argparse.Namespace) -> int:
    """Start an interactive agent session."""
    import logging

    from framework.runner import AgentRunner

    # Configure logging to show runtime visibility
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",  # Simple format for clean output
    )

    agents_dir = Path(args.agents_dir)

    # Multi-agent mode with orchestrator
    if args.multi:
        return _interactive_multi(agents_dir)

    # Single agent mode
    agent_path = args.agent_path
    if not agent_path:
        # List available agents and let user choose
        agent_path = _select_agent(agents_dir)
        if not agent_path:
            return 1

    try:
        runner = AgentRunner.load(agent_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Set up approval callback by default (unless --no-approve is set)
    if not getattr(args, "no_approve", False):
        runner.set_approval_callback(_interactive_approval)
        print("\n🔔 Human-in-the-loop mode enabled")
        print("   Steps marked for approval will pause for your review")
    else:
        print("\n⚠️  Auto-approve mode: all steps will execute without review")

    info = runner.info()

    # Get entry node's input keys for smart formatting
    entry_node = next((n for n in info.nodes if n["id"] == info.entry_node), None)
    entry_input_keys = entry_node["input_keys"] if entry_node else []

    print(f"\n{'=' * 60}")
    print(f"Agent: {info.name}")
    print(f"Goal: {info.goal_name}")
    print(f"Description: {info.description[:100]}...")
    print(f"{'=' * 60}")
    print("\nInteractive mode. Enter natural language or JSON:")
    print("  /info    - Show agent details")
    print("  /nodes   - Show agent nodes")
    print("  /reset   - Reset conversation state")
    print("  /quit    - Exit interactive mode")
    print("  {...}    - JSON input to run agent")
    print("  anything else - Natural language (auto-formatted with Haiku)")
    print()

    # Session state: accumulate context across multiple inputs
    session_memory = {}
    conversation_history = []
    agent_session_state = None  # Track paused agent state

    while True:
        try:
            user_input = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            break

        if user_input == "/info":
            print(f"\nAgent: {info.name}")
            print(f"Goal: {info.goal_name}")
            print(f"Description: {info.goal_description}")
            print(f"Nodes: {info.node_count}")
            print(f"Edges: {info.edge_count}")
            print(f"Required tools: {', '.join(info.required_tools)}")
            print()
            continue

        if user_input == "/nodes":
            print("\nAgent nodes:")
            for node in info.nodes:
                inputs = f" [in: {', '.join(node['input_keys'])}]" if node.get("input_keys") else ""
                outputs = (
                    f" [out: {', '.join(node['output_keys'])}]" if node.get("output_keys") else ""
                )
                print(f"  {node['id']}: {node['name']}{inputs}{outputs}")
                print(f"    {node['description']}")
            print()
            continue

        if user_input == "/reset":
            session_memory = {}
            conversation_history = []
            agent_session_state = None  # Clear agent's internal state too
            print("✓ Conversation state and agent session cleared")
            print()
            continue

        # Try to parse as JSON first
        try:
            context = json.loads(user_input)
            print("✓ Parsed as JSON")
        except json.JSONDecodeError:
            # Not JSON - check for key=value format
            if "=" in user_input and " " not in user_input.split("=")[0]:
                context = {}
                for part in user_input.split():
                    if "=" in part:
                        key, value = part.split("=", 1)
                        context[key] = value
                print("✓ Parsed as key=value")
            else:
                # Natural language - use Haiku to format
                print("🤖 Formatting with Haiku...")
                try:
                    context = _format_natural_language_to_json(
                        user_input,
                        entry_input_keys,
                        info.description,
                        session_context=session_memory,
                    )
                    print(f"✓ Formatted to: {json.dumps(context)}")
                except Exception as e:
                    print(f"Error formatting input: {e}")
                    print("Please try JSON format: {...} or key=value format")
                    continue

        # Handle context differently based on whether we're resuming or starting fresh
        if agent_session_state:
            # RESUMING: Pass only the new input in the "input" key
            # The executor will restore all session memory automatically
            # The resume node expects fresh input, not merged session context
            run_context = {"input": user_input}  # Pass raw user input for resume nodes
            print(f"\n🔄 Resuming from paused state: {agent_session_state.get('paused_at')}")
            print(f"User's answer: {user_input}")
        else:
            # STARTING FRESH: Merge new input with accumulated session memory
            run_context = {**session_memory, **context}

            # Auto-inject user_id if missing (for personal assistant agents)
            if "user_id" in entry_input_keys and run_context.get("user_id") is None:
                import os

                run_context["user_id"] = os.environ.get("USER", "default_user")

            # Add conversation history to context if agent expects it
            if conversation_history:
                run_context["_conversation_history"] = conversation_history.copy()

            print(f"\nRunning with: {json.dumps(context)}")
            if session_memory:
                print(f"Session context: {json.dumps(session_memory)}")

        print("-" * 40)

        # Pass agent session state to enable resumption
        result = asyncio.run(runner.run(run_context, session_state=agent_session_state))

        status_str = "SUCCESS" if result.success else "FAILED"
        print(f"\nStatus: {status_str}")
        print(f"Steps executed: {result.steps_executed}")
        print(f"Path: {' → '.join(result.path)}")

        # Show clean output - prioritize meaningful keys
        if result.output:
            meaningful_keys = ["final_response", "response", "result", "answer", "output"]
            shown = False

            for key in meaningful_keys:
                if key in result.output:
                    value = result.output[key]
                    if isinstance(value, str) and len(value) > 10:
                        print(f"\n{value}\n")
                        shown = True
                        break

            if not shown:
                print("\nOutput:")
                for key, value in result.output.items():
                    if not key.startswith("_"):
                        val_str = str(value)[:200]
                        print(f"  {key}: {val_str}")

        if result.error:
            print(f"\nError: {result.error}")

        if result.total_tokens > 0:
            print(f"\nTokens used: {result.total_tokens}")
            print(f"Latency: {result.total_latency_ms}ms")

        # Update agent session state if paused
        if result.paused_at:
            agent_session_state = result.session_state
            print(f"⏸ Agent paused at: {result.paused_at}")
            print("   Next input will resume from this point")
        else:
            # Execution completed (not paused), clear session state
            agent_session_state = None

        # Update session memory with outputs from this run
        # This allows follow-up inputs to reference previous context
        if result.output:
            for key, value in result.output.items():
                # Don't store internal keys or very large values
                if not key.startswith("_") and len(str(value)) < 5000:
                    session_memory[key] = value

        # Track conversation history
        conversation_history.append(
            {
                "input": context,
                "output": result.output if result.output else {},
                "status": "success" if result.success else "failed",
                "paused_at": result.paused_at,
            }
        )

        print()

    runner.cleanup()
    return 0


def _select_agent(agents_dir: Path) -> str | None:
    """Let user select an agent from available agents."""
    if not agents_dir.exists():
        print(f"Directory not found: {agents_dir}", file=sys.stderr)
        # fixes issue #696, creates an exports folder if it does not exist
        agents_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created directory: {agents_dir}", file=sys.stderr)
        # return None

    agents = []
    for path in agents_dir.iterdir():
        if path.is_dir() and (path / "agent.json").exists():
            agents.append(path)

    if not agents:
        print(f"No agents found in {agents_dir}", file=sys.stderr)
        return None

    print(f"\nAvailable agents in {agents_dir}:\n")
    for i, agent_path in enumerate(agents, 1):
        try:
            from framework.runner import AgentRunner

            runner = AgentRunner.load(agent_path)
            info = runner.info()
            desc = info.description[:50] + "..." if len(info.description) > 50 else info.description
            print(f"  {i}. {info.name}")
            print(f"     {desc}")
            runner.cleanup()
        except Exception as e:
            print(f"  {i}. {agent_path.name} (error: {e})")

    print()
    try:
        choice = input("Select agent (number): ").strip()
        idx = int(choice) - 1
        if 0 <= idx < len(agents):
            return str(agents[idx])
        print("Invalid selection")
        return None
    except (ValueError, EOFError, KeyboardInterrupt):
        return None


def _interactive_multi(agents_dir: Path) -> int:
    """Interactive multi-agent mode with orchestrator."""
    from framework.runner import AgentOrchestrator

    if not agents_dir.exists():
        print(f"Directory not found: {agents_dir}", file=sys.stderr)
        return 1

    orchestrator = AgentOrchestrator()
    agent_count = 0

    # Register all agents
    for path in agents_dir.iterdir():
        if path.is_dir() and (path / "agent.json").exists():
            try:
                orchestrator.register(path.name, path)
                agent_count += 1
            except Exception as e:
                print(f"Warning: Failed to register {path.name}: {e}")

    if agent_count == 0:
        print(f"No agents found in {agents_dir}", file=sys.stderr)
        return 1

    print(f"\n{'=' * 60}")
    print("Multi-Agent Interactive Mode")
    print(f"Registered {agent_count} agents")
    print(f"{'=' * 60}")
    print("\nCommands:")
    print("  /agents  - List registered agents")
    print("  /quit    - Exit")
    print("  {...}    - JSON input to dispatch")
    print()

    while True:
        try:
            user_input = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            break

        if user_input == "/agents":
            print("\nRegistered agents:")
            for agent in orchestrator.list_agents():
                print(f"  - {agent['name']}: {agent['description'][:60]}...")
            print()
            continue

        # Parse intent if provided
        intent = None
        if user_input.startswith("/intent "):
            parts = user_input.split(" ", 2)
            if len(parts) >= 3:
                intent = parts[1]
                user_input = parts[2]

        # Try to parse as JSON
        try:
            context = json.loads(user_input)
        except json.JSONDecodeError:
            print("Error: Invalid JSON input. Use {...} format.")
            continue

        print(f"\nDispatching: {json.dumps(context)}")
        if intent:
            print(f"Intent: {intent}")
        print("-" * 40)

        result = asyncio.run(orchestrator.dispatch(context, intent=intent))

        print(f"\nSuccess: {result.success}")
        print(f"Handled by: {', '.join(result.handled_by) or 'none'}")

        if result.error:
            print(f"Error: {result.error}")

        if result.results:
            print("\nResults by agent:")
            for agent_name, data in result.results.items():
                print(f"\n  {agent_name}:")
                status = data.get("status", "unknown")
                print(f"    Status: {status}")
                if "results" in data:
                    results_preview = json.dumps(data["results"], default=str)
                    if len(results_preview) > 150:
                        results_preview = results_preview[:150] + "..."
                    print(f"    Results: {results_preview}")

        print(f"\nMessage trace: {len(result.messages)} messages")
        print()

    orchestrator.cleanup()
    return 0

# Version Management Commands

def cmd_version_save(args: argparse.Namespace) -> int:
    from framework.runner import AgentRunner
    from framework.runner.versioning import AgentVersionManager

    try:
        runner = AgentRunner.load(args.agent_path)
    except Exception as e:
        print(f"Error loading agent: {e}", file=sys.stderr)
        return 1

    agent_path = Path(args.agent_path)
    agent_id = agent_path.name

    versions_dir = Path(".aden/versions")
    manager = AgentVersionManager(versions_dir)

    try:
        version = manager.save_version(
            agent_id=agent_id,
            graph=runner.graph,
            goal=runner.goal,
            description=args.description,
            bump=args.bump,
            created_by=args.created_by,
            tags=[args.tag] if args.tag else None,
        )

        print(f"Saved version {version.version} of {agent_id}")
        print(f"Description: {version.description}")
        if args.tag:
            manager.tag_version(agent_id, version.version, args.tag)
            print(f"Tagged as: {args.tag}")

        return 0

    except Exception as e:
        print(f"Error saving version: {e}", file=sys.stderr)
        return 1


def cmd_version_list(args: argparse.Namespace) -> int:
    from framework.runner.versioning import AgentVersionManager

    versions_dir = Path(".aden/versions")
    manager = AgentVersionManager(versions_dir)

    try:
        versions = manager.list_versions(args.agent_id)

        if not versions:
            print(f"No versions found for agent: {args.agent_id}")
            return 0

        registry = manager._load_registry(args.agent_id)

        if args.json:
            output = {
                "agent_id": args.agent_id,
                "current_version": registry.current_version,
                "versions": [v.model_dump() for v in versions],
                "tags": registry.tags,
            }
            print(json.dumps(output, indent=2, default=str))
        else:
            print(f"\nVersions for {args.agent_id}:")
            print(f"Current: {registry.current_version}\n")

            for v in versions:
                marker = "*" if v.version == registry.current_version else " "
                tags_str = f" [{', '.join(v.tags)}]" if v.tags else ""
                print(f"{marker} {v.version}{tags_str}")
                print(f"  {v.description}")
                print(f"  Created: {v.created_at}")
                if v.created_by:
                    print(f"  By: {v.created_by}")
                print()

            if registry.tags:
                print("Tags:")
                for tag, version in registry.tags.items():
                    print(f"  {tag} -> {version}")
                print()

        return 0

    except Exception as e:
        print(f"Error listing versions: {e}", file=sys.stderr)
        return 1


def cmd_version_rollback(args: argparse.Namespace) -> int:
    from framework.runner.versioning import AgentVersionManager

    versions_dir = Path(".aden/versions")
    manager = AgentVersionManager(versions_dir)

    try:
        graph, goal = manager.rollback(args.agent_id, args.version)

        print(f"Rolled back {args.agent_id} to version {args.version}")

        if args.export:
            export_path = Path(args.export)
        else:
            export_path = Path("exports") / args.agent_id

        export_path.mkdir(parents=True, exist_ok=True)

        export_data = {
            "graph": graph.model_dump(),
            "goal": goal.model_dump(),
            "version": args.version,
        }

        agent_file = export_path / "agent.json"
        with open(agent_file, "w") as f:
            json.dump(export_data, f, indent=2, default=str)

        print(f"Exported to: {export_path}")

        return 0

    except Exception as e:
        print(f"Error during rollback: {e}", file=sys.stderr)
        return 1


def cmd_version_diff(args: argparse.Namespace) -> int:
    """Compare two versions"""
    from framework.runner.versioning import AgentVersionManager

    versions_dir = Path(".aden/versions")
    manager = AgentVersionManager(versions_dir)

    try:
        diff = manager.compare_versions(
            args.agent_id, args.from_version, args.to_version
        )

        if args.json:
            print(json.dumps(diff.model_dump(), indent=2))
        else:
            print(f"\nDiff: {args.from_version} → {args.to_version}")
            print(f"Agent: {args.agent_id}\n")
            print(f"Summary: {diff.summary}\n")

            if diff.nodes_added:
                print(f"Nodes added ({len(diff.nodes_added)}):")
                for node_id in diff.nodes_added:
                    print(f"  + {node_id}")
                print()

            if diff.nodes_removed:
                print(f"Nodes removed ({len(diff.nodes_removed)}):")
                for node_id in diff.nodes_removed:
                    print(f"  - {node_id}")
                print()

            if diff.nodes_modified:
                print(f"Nodes modified ({len(diff.nodes_modified)}):")
                for node in diff.nodes_modified:
                    print(f"  ~ {node['id']}")
                print()

            if diff.edges_added:
                print(f"Edges added ({len(diff.edges_added)}):")
                for edge_id in diff.edges_added:
                    print(f"  + {edge_id}")
                print()

            if diff.edges_removed:
                print(f"Edges removed ({len(diff.edges_removed)}):")
                for edge_id in diff.edges_removed:
                    print(f"  - {edge_id}")
                print()

            if diff.edges_modified:
                print(f"Edges modified ({len(diff.edges_modified)}):")
                for edge in diff.edges_modified:
                    print(f"  ~ {edge['id']}")
                print()

            changes = []
            if diff.success_criteria_changed:
                changes.append("success criteria")
            if diff.constraints_changed:
                changes.append("constraints")
            if diff.capabilities_changed:
                changes.append("capabilities")

            if changes:
                print(f"Goal changes: {', '.join(changes)}")
                print()

        return 0

    except Exception as e:
        print(f"Error comparing versions: {e}", file=sys.stderr)
        return 1


def cmd_version_tag(args: argparse.Namespace) -> int:
    from framework.runner.versioning import AgentVersionManager

    versions_dir = Path(".aden/versions")
    manager = AgentVersionManager(versions_dir)

    try:
        manager.tag_version(args.agent_id, args.version, args.tag)
        print(f"Tagged version {args.version} as '{args.tag}'")
        return 0

    except Exception as e:
        print(f"Error tagging version: {e}", file=sys.stderr)
        return 1


def cmd_version_ab_test(args: argparse.Namespace) -> int:
    from framework.runner.versioning import AgentVersionManager

    versions_dir = Path(".aden/versions")
    manager = AgentVersionManager(versions_dir)

    try:
        config = manager.create_ab_test(
            agent_id=args.agent_id,
            version_a=args.version_a,
            version_b=args.version_b,
            traffic_split=args.split,
            metrics=args.metrics,
        )

        print(f"Created A/B test for {args.agent_id}")
        print(f"Version A: {args.version_a} ({args.split * 100:.0f}% traffic)")
        print(f"Version B: {args.version_b} ({(1 - args.split) * 100:.0f}% traffic)")
        if args.metrics:
            print(f"Metrics: {', '.join(args.metrics)}")

        print(f"\nA/B test configuration saved.")
        print(f"Use AgentVersionManager.route_ab_test() to route requests.")

        return 0

    except Exception as e:
        print(f"Error creating A/B test: {e}", file=sys.stderr)
        return 1
