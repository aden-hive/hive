# Contract Intelligence & Risk Agent

Automated contract review and clause risk scoring. This agent ingests contracts (PDF), extracts and classifies key clauses, scores each clause for risk against a configurable baseline template, flags anomalies, generates a plain-English negotiation brief, and stores a structured summary.

## Features

- **Clause Extraction**: Automatically identifies and extracts key clauses including payment terms, liability caps, indemnification, IP ownership, termination, auto-renewal, confidentiality, and governing law
- **Risk Scoring**: Scores each clause on a risk scale (Low/Medium/High) against configurable baseline templates
- **Anomaly Detection**: Flags clauses that deviate materially from standard (uncapped liability, one-sided IP assignment, auto-renewal without notice)
- **Human-in-the-Loop Review**: Presents a structured risk summary for human approval before generating outputs
- **Negotiation Brief**: Generates a concise, plain-English brief with specific push-back recommendations
- **Structured Storage**: Saves a JSON summary of the contract analysis for records

## Workflow

```
intake -> extraction -> scoring -> flag -> hitl_review -> brief -> storage
```

1. **Intake Node**: Accepts uploaded contract file (PDF) or pasted contract text
2. **Clause Extraction Node**: Uses LLM to identify and label all clauses
3. **Risk Scoring Node**: Scores each clause on risk scale by comparing against baseline template
4. **Anomaly Flag Node**: Highlights clauses that deviate materially from standard
5. **HITL Review Node**: Presents structured risk summary for user review
6. **Negotiation Brief Node**: Generates plain-English brief with recommendations
7. **Summary Storage Node**: Saves structured JSON summary for records

## Usage

### CLI

```bash
# Run with a PDF file
PYTHONPATH=core uv run python -m examples.templates.contract_intelligence_agent run --file /path/to/contract.pdf

# Run with pasted text
PYTHONPATH=core uv run python -m examples.templates.contract_intelligence_agent run --text "Contract text here..."

# Validate agent structure
PYTHONPATH=core uv run python -m examples.templates.contract_intelligence_agent validate

# Show agent info
PYTHONPATH=core uv run python -m examples.templates.contract_intelligence_agent info
```

### TUI Dashboard

```bash
PYTHONPATH=core uv run python -m examples.templates.contract_intelligence_agent tui
```

### Programmatic

```python
from examples.templates.contract_intelligence_agent import ContractIntelligenceAgent

async def analyze_contract():
    agent = ContractIntelligenceAgent()
    result = await agent.run({"file_path": "/path/to/contract.pdf"})
    print(result.output)
```

## Supported Contract Types

- **Vendor Agreements**: B2B vendor/supplier contracts
- **Client Agreements**: Contracts where you are the service provider
- **Employment**: Employment and contractor agreements
- **SaaS**: Software-as-a-Service subscription agreements
- **NDA**: Non-disclosure agreements
- **MSA**: Master Service Agreements
- **Other**: General commercial contracts

## Risk Categories

### Critical Anomalies
- Uncapped liability
- One-sided IP assignment
- Auto-renewal without notice
- Broad non-compete clauses
- Exclusive dealing requirements
- No termination rights

### Significant Anomalies
- Asymmetric indemnification
- Long auto-renewal notice periods (60+ days)
- Unfavorable venue/jurisdiction
- Broad confidentiality obligations
- Hidden fee clauses

## Configuration

The baseline template can be customized by modifying `DEFAULT_BASELINE_TEMPLATE` in `config.py`:

```python
DEFAULT_BASELINE_TEMPLATE = {
    "contract_type": "vendor",
    "payment_terms": {"max_net_days": 30, "preferred": "Net 30"},
    "liability_cap": {"max_multiplier": 1.0, "preferred": "Fees paid in prior 12 months"},
    "indemnification": {"mutual": True, "preferred": "Mutual indemnification"},
    "ip_ownership": {"client_retains": True, "preferred": "Client owns all deliverables"},
    "termination": {"notice_days": 30, "for_convenience": True},
    "auto_renewal": {"requires_notice": True, "notice_days": 30},
    "confidentiality": {"mutual": True, "survival_years": 3},
    "governing_law": {"preferred": "Client jurisdiction or Delaware"},
}
```

## Success Criteria

- Clause extraction recall ≥ 90% on standard commercial contracts
- Risk scoring agreement with legal review ≥ 85% on flagged clauses
- 100% human confirmation before negotiation brief output
- End-to-end contract review time under 3 minutes

## Requirements

- Python 3.11+
- Anthropic API key (or other configured LLM provider)
- PDF files must be readable (not encrypted/password-protected)

## License

MIT
