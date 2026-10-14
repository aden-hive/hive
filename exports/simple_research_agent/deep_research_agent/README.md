# Deep Research Agent

A template agent designed to perform comprehensive research on a specific topic and generate a structured report.

## Usage

Run the agent using the following command:

### Linux / Mac
```bash
PYTHONPATH=core:examples/templates python -m deep_research_agent run --mock --topic "Artificial Intelligence"
```

### Windows
```powershell
$env:PYTHONPATH="core;examples\templates"
python -m deep_research_agent run --mock --topic "Artificial Intelligence"
```

## Options

- `-t, --topic`: The research topic (required).
- `--mock`: Run without calling real LLM APIs (simulated execution).
- `--help`: Show all available options.
