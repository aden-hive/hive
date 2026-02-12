Evolution demo
----------------

This folder contains a small demo script that listens for `GRAPH_EVOLUTION_REQUEST` and proposes
a candidate graph to `AgentRuntime.update_graph(...)`.

How to run

1. Activate the project's virtualenv (created with proto as described in repo docs):

```bash
source .venv/bin/activate
```

2. Run the demo script:

```bash
python core/examples/evolution_demo.py
```

3. Optionally start the TUI in another terminal to see the visual diff when the candidate is applied:

```bash
# In separate terminal
source .venv/bin/activate
python -m framework.tui.app
```

Notes
- The demo uses simple stub guards to demonstrate both approve and reject flows.
- Audit entries are persisted to `storage_path/evolution_audit/` or written to the runtime log store if provided.
