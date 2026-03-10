# Linear Triage & Auto-Labeling Agent

Autonomous triage agent that ingests raw issue descriptions, classifies them
(Bug, Feature, Security), determines priority, and uses a Router Pattern to
dispatch to specialized processing nodes before generating a simulated Linear
API payload.

## Architecture

This agent demonstrates the **Router Pattern** with **Conditional Edges**:

```
                    ┌─────────────────┐
                    │  ClassifyNode   │
                    │  (EntryPoint)   │
                    └────────┬────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
   │ SecurityNode│    │   BugNode   │    │ FeatureNode │
   │  (P0/P1)    │    │  (Analysis) │    │  (PM Eval)  │
   └──────┬──────┘    └──────┬──────┘    └──────┬──────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   ActionNode    │
                    │  (Save Payload) │
                    └─────────────────┘
```

## Features

- **Issue Classification**: Classifies raw issue descriptions into Bug,
  Feature, or Security types
- **Priority Assessment**: Assigns severity levels (P0-P3) based on impact
- **Auto-Labeling**: Suggests appropriate labels for the issue
- **Specialized Processing**:
  - **Security**: Drafts high-priority escalation alerts
  - **Bug**: Extracts reproduction steps and probable root causes
  - **Feature**: Evaluates roadmap alignment and PM questions
- **Linear API Simulation**: Generates and saves a formatted JSON payload

## Usage

### CLI

```bash
# Run triage on an issue
python -m framework.agents.linear_triage_agent --issue "Login crashes on Safari"

# Run demo with sample issues
python -m framework.agents.linear_triage_agent demo --type security

# View agent info
python -m framework.agents.linear_triage_agent info

# Validate agent structure
python -m framework.agents.linear_triage_agent validate
```

### Programmatic

```python
from framework.agents.linear_triage_agent import LinearTriageAgent

async def triage_issue():
    agent = LinearTriageAgent()
    result = await agent.run({
        "raw_issue": "Login page crashes on Safari when uploading a PDF"
    })

    if result.success:
        print("Triage complete:", result.output)
    else:
        print("Triage failed:", result.error)
```

## State Schema

```json
{
  "raw_issue": "string",
  "issue_type": "security|bug|feature",
  "severity": "P0|P1|P2|P3",
  "suggested_labels": ["list of strings"],
  "summary": "string",
  "node_context": "string (branch-specific output)",
  "escalation_required": "boolean",
  "final_payload_status": "string"
}
```

## Output

The agent saves a `linear_api_payload_simulated.json` file with the following
structure:

```json
{
  "issue": {
    "title": "Brief summary",
    "description": "Original issue description",
    "type": "security|bug|feature",
    "priority": "P0|P1|P2|P3",
    "labels": ["label1", "label2"]
  },
  "triage": {
    "classification": "security|bug|feature",
    "severity": "P0|P1|P2|P3",
    "escalation_required": true,
    "analysis": "Detailed analysis from specialized node"
  },
  "linear_api_simulation": {
    "operation": "create_issue",
    "status": "simulated",
    "timestamp": "ISO timestamp"
  }
}
```

## Testing

```bash
cd core
uv run pytest framework/agents/linear_triage_agent/tests/ -v
```

## Configuration

The agent uses the standard Hive configuration from `~/.hive/configuration.json`.
Default model is `anthropic/claude-sonnet-4-20250514`.

## Related

- Issue: #4863
- Pattern: Router Pattern with Conditional Edges
- Framework: Hive Agent Framework
