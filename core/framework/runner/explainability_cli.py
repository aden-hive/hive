def register_explainability_commands(subparsers):
    explain_parser = subparsers.add_parser(
        "show-run-log",
        help="Show agent reasoning and decision log for a run",
        description="Display the reasoning, decisions, and actions for a given agent run."
    )
    explain_parser.add_argument(
        "run_file",
        type=str,
        help="Path to the run log file (JSON or pickle)"
    )
    explain_parser.set_defaults(func=cmd_show_run_log)

def cmd_show_run_log(args):
    import json
    from pathlib import Path
    run_path = Path(args.run_file)
    if not run_path.exists():
        print(f"Run file not found: {run_path}")
        return 1
    # Try to load as JSON
    try:
        with open(run_path, "r") as f:
            run = json.load(f)
    except Exception as e:
        print(f"Failed to load run file: {e}")
        return 1
    print(f"Run ID: {run.get('id', 'unknown')}")
    print(f"Goal: {run.get('goal_description', '')}")
    print(f"Status: {run.get('status', '')}")
    print("\nDecisions and Reasoning:")
    for dec in run.get("decisions", []):
        print(f"\n- Node: {dec.get('node_id', 'unknown')}")
        print(f"  Intent: {dec.get('intent', '')}")
        print(f"  Reasoning: {dec.get('reasoning', '')}")
        print(f"  Chosen Option: {dec.get('chosen_option_id', '')}")
        if 'options' in dec:
            print("  Options:")
            for opt in dec['options']:
                print(f"    - {opt.get('id', '')}: {opt.get('description', '')}")
        if 'outcome' in dec:
            print(f"  Outcome: {dec['outcome'].get('success', '')}")
            if dec['outcome'].get('result'):
                print(f"    Result: {dec['outcome']['result']}")
            if dec['outcome'].get('error'):
                print(f"    Error: {dec['outcome']['error']}")
    print("\n--- End of Run Log ---\n")
    return 0
