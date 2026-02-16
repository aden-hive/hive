# Usage Examples

## Basic Usage

### Analyze a Single Contract

```bash
# Using Hive CLI
hive run examples/templates/contract_evaluator \\
  --input '{"contract_path": "/path/to/contracts/vendor_nda.pdf"}'

# Using Python module directly
python -m examples.templates.contract_evaluator run \\
  --contract-path /path/to/contracts/vendor_nda.pdf \\
  --output report.md
```

### Batch Processing

```python
import asyncio
from pathlib import Path
from examples.templates.contract_evaluator import default_agent

async def process_all_contracts(contracts_dir: Path):
    results = []
    
    for contract_file in contracts_dir.glob("*.pdf"):
        print(f"Processing {contract_file.name}...")
        
        result = await default_agent.run({
            "contract_path": str(contract_file)
        })
        
        results.append({
            "contract": contract_file.name,
            "risk_score": result["risk_assessment"]["overall_risk_score"],
            "needs_review": result["risk_assessment"]["human_review_required"],
        })
    
    return results

# Run batch processing
contracts = Path("./contracts")
results = asyncio.run(process_all_contracts(contracts))

# Print summary
for r in sorted(results, key=lambda x: x["risk_score"], reverse=True):
    print(f"{r['contract']:30s} | Risk: {r['risk_score']:.1f}/10 | Review: {r['needs_review']}")
```

## Advanced Usage

### Custom Risk Threshold

```python
from examples.templates.contract_evaluator import ContractEvaluationAgent
from examples.templates.contract_evaluator.config import RuntimeConfig

# Create custom config
config = RuntimeConfig(
    model="anthropic/claude-sonnet-4-20250514",
    temperature=0.2,
    risk_threshold=8.5,  # Higher threshold = fewer escalations
)

# Create agent with custom config
agent = ContractEvaluationAgent(config=config)
agent.start()

# Run analysis
result = await agent.run({"contract_path": "contract.pdf"})
```

### Integrating with TUI

```bash
# Run with interactive dashboard
hive run examples/templates/contract_evaluator --tui

# The TUI will show:
# - Real-time node execution
# - Progress through analysis pipeline
# - Human review prompts (if needed)
# - Final report
```

### Extracting Specific Information

```python
result = await default_agent.run({"contract_path": "contract.pdf"})

# Get risk assessment
risk = result["risk_assessment"]
print(f"Overall Risk: {risk['overall_risk_score']}/10")
print(f"Critical Issues: {len(risk['critical_issues'])}")

# Get confidentiality details
conf = result["confidentiality"]
print(f"Type: {conf['type']}")
print(f"Duration: {conf['duration_months']} months")

# Get liability info
liab = result["liability"]
if liab["unlimited_liability"]:
    print("⚠️ WARNING: Unlimited liability detected!")
```

### Saving Reports

```python
from pathlib import Path

result = await default_agent.run({"contract_path": "contract.pdf"})

# Save markdown report
report_path = Path("reports/contract_analysis.md")
report_path.write_text(result["report_markdown"])

# Save JSON for programmatic access
import json
json_path = Path("reports/contract_analysis.json")
json_path.write_text(json.dumps(result["report_json"], indent=2))
```

## Integration Patterns

### Contract Management System

```python
class ContractReviewPipeline:
    """Integrate with your CLM system."""
    
    async def review_new_contract(self, contract_id: str):
        # 1. Download contract from CLM
        contract_path = self.clm.download(contract_id)
        
        # 2. Run AI analysis
        result = await default_agent.run({"contract_path": contract_path})
        
        # 3. Store results in CLM
        self.clm.update_metadata(contract_id, {
            "ai_risk_score": result["risk_assessment"]["overall_risk_score"],
            "requires_review": result["risk_assessment"]["human_review_required"],
        })
        
        # 4. Create ticket for high-risk contracts
        if result["risk_assessment"]["human_review_required"]:
            self.ticketing_system.create_review_ticket(
                contract_id=contract_id,
                priority="high",
                summary=result["risk_assessment"]["human_review_reason"],
                issues=result["risk_assessment"]["critical_issues"],
            )
        
        return result
```

### Slack Notification

```python
import aiohttp

async def analyze_and_notify(contract_path: str, slack_webhook: str):
    result = await default_agent.run({"contract_path": contract_path})
    
    risk = result["risk_assessment"]
    
    message = {
        "text": f"Contract Analysis Complete: {result['contract_id']}",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Risk Score:* {risk['overall_risk_score']:.1f}/10"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Critical Issues:* {len(risk['critical_issues'])}"
                }
            }
        ]
    }
    
    async with aiohttp.ClientSession() as session:
        await session.post(slack_webhook, json=message)
```

## Error Handling

```python
try:
    result = await default_agent.run({"contract_path": "contract.pdf"})
    
    if not result.get("success"):
        error = result.get("error", "Unknown error")
        print(f"Analysis failed: {error}")
        # Fall back to manual review
        
except FileNotFoundError:
    print("Contract file not found")
except Exception as e:
    print(f"Unexpected error: {e}")
    # Log for debugging
```
