# Developer Experience (DX) Friction Log
**Agent Built:** Competitor SWOT Analysis (Sample)
**Date:** [Current Date]

While building this sample agent from scratch (without using the `deep_research` template), I encountered several friction points that new developers will likely face.

### 1. Prerequisite Confusion (`uv`)
* **Issue:** The setup guide assumes `uv` is installed. When running the recommended commands on a fresh environment, it failed with `Command 'uv' not found`.
* **Impact:** Blocking.
* **Suggestion:** Add the explicit curl install command (`curl -LsSf https://astral.sh/uv/install.sh | sh`) to the "Initial Setup" section of the README.

### 2. Missing "Entry Points" in Runtime
* **Issue:** The `create_agent_runtime()` function has a required argument `entry_points` that is not documented in the basic examples.
* **Error:** `TypeError: create_agent_runtime() missing 1 required positional argument: 'entry_points'`
* **Fix:** I had to manually import `EntryPointSpec` and define a default entry point pointing to my start node.
* **Suggestion:** Update the `create_agent_runtime` defaults to automatically create a "default" entry point if one isn't provided, or update the docs to show this requirement.

### 3. CLI Input Mapping
* **Issue:** The standard `__main__.py` pattern parses arguments into a generic dictionary, but Agent Nodes require specific keys (e.g., `target_company`).
* **Error:** `Validation warnings: ['Missing required input: target_company']`
* **Fix:** I had to manually map `args.company` to `{"target_company": args.company}` in the main execution loop.
* **Suggestion:** The CLI generator or template should include a clearer example of mapping `argparse` arguments to the specific `input_keys` defined in the Agent's Goal.

### 4. Missing Local Templates
* **Issue:** The `examples/` folder referenced in documentation doesn't exist in the pip-installed package or the basic clone without extra steps.
* **Impact:** I had to reverse-engineer the folder structure (`__init__.py`, `agent.py`) manually.