# Contract Evaluation Agent

Automated NDA analysis agent that extracts key information, identifies risk factors, checks compliance, and generates structured reports. Demonstrates Hive's multi-node architecture with human-in-the-loop capabilities.

## ⚠️ Important Disclaimers

- **NOT LEGAL ADVICE**: This agent provides analysis and suggestions only. It does not constitute legal advice.
- **REQUIRES HUMAN OVERSIGHT**: All high-risk contracts are escalated to human legal reviewers.
- **NDA FOCUS**: Currently supports NDA analysis only. Other contract types are not supported.
- **VALIDATION STATUS**: Tested on limited dataset (n=20). Accuracy may vary on unseen contracts.

## Features

-  **Document Processing**: Extracts text from PDF and DOCX files
- 📊 **Risk Assessment**: Assigns risk scores (1-10) to contracts and specific clauses
- 🔍 **Clause Detection**: Identifies confidentiality, liability, and term provisions
- ⚖️ **Compliance Checks**: Flags potential compliance issues
- 👤 **Human-in-the-Loop**: Escalates high-risk contracts to legal reviewers
- 📝 **Report Generation**: Creates markdown and JSON reports with recommendations

## Supported Contract Types

- Non-Disclosure Agreements (NDAs)
- Mutual NDAs
- One-Sided NDAs

## Quick Start

### Installation

Ensure the Hive framework is installed and configured:

```bash
cd /path/to/hive
./quickstart.sh
```

### Usage

#### Run on a single contract:

```bash
hive run examples/templates/contract_evaluator \\
  --input '{"contract_path": "path/to/contract.pdf"}'
```

#### Run with TUI dashboard:

```bash
hive run examples/templates/contract_evaluator --tui
```

#### Using Python directly:

```python
from examples.templates.contract_evaluator import default_agent

input_data = {"contract_path": "contracts/vendor_nda.pdf"}
result = await default_agent.run(input_data)

print(result["report_markdown"])
```

## Architecture

### Node Graph

```
Contract Input (PDF/DOCX)
         ↓
[Document Ingestion]
         ↓
[Classification]
         ↓
[Parallel Analysis]
├─ Confidentiality
├─ Liability
└─ Terms & Obligations
         ↓
[Synthesis & Risk Scoring]
         ↓
    High Risk?
    /        \\
[Human Review] → [Report Generation]
              ↘  ↗
```

### Nodes

1. **Document Ingestion**: Extracts text from PDF/DOCX files
2. **Classification**: Identifies contract type and jurisdiction
3. **Confidentiality Analysis**: Examines mutual vs one-sided obligations
4. **Liability Analysis**: Checks caps, indemnification, insurance
5. **Term & Obligations**: Extracts duration, renewal, obligations
6. **Synthesis**: Aggregates findings and calculates risk score
7. **Human Review**: Escalates to reviewer if risk ≥ 7/10 or critical issues found
8. **Report Generation**: Creates comprehensive markdown and JSON reports

## Example Output

### Sample Report

```markdown
# Contract Evaluation Report

## Contract Information
- **Contract ID**: vendor_nda_2024
- **Type**: Mutual NDA
- **Jurisdiction**: California
- **Overall Risk Score**: 6.5/10

## Critical Issues
- ⚠️ Unlimited liability exposure detected

## Recommendations
1. Add limitation of liability clause with reasonable cap
2. Clarify definition of 'confidential information'
```

### JSON Output

```json
{
  "contract_id": "vendor_nda_2024",
  "overall_risk_score": 6.5,
  "findings": {
    "confidentiality": {"type": "mutual", "risk_level": "medium"},
    "liability": {"unlimited_liability": true, "risk_level": "high"},
    "terms": {"duration_months": 24, "risk_level": "low"}
  },
  "human_review_required": true
}
```

## Configuration

Edit `config.py` to customize:

- **Risk threshold**: Default is 7.0 (contracts with risk ≥ 7 escalate to human review)
- **LLM model**: Uses your Hive default model (claude-sonnet-4, gpt-4, etc.)
- **Temperature**: Default is 0.3 for consistent legal analysis

## Dependencies

### Required
- PyPDF2 (PDF extraction)
- python-docx (DOCX parsing)
- Hive framework

### Optional
- pytesseract (OCR for scanned documents)

Install dependencies:
```bash
pip install PyPDF2 python-docx
```

## Validation

This agent has been tested on 20 publicly available NDA contracts.

### Test Results (as of 2026-02-10)

| Capability | Precision | Recall | F1 Score |
|------------|-----------|--------|----------|
| Mutual confidentiality detection | 95% (19/20) | 95% | 0.95 |
| Liability clause identification | 84% (16/19) | 80% | 0.82 |
| Term length extraction | 100% (20/20) | 100% | 1.00 |

**Performance:**
- Average processing time: 38 seconds per NDA
- Average API cost: $0.18 per contract (GPT-4)
- Human escalation rate: 25% (5/20 contracts)

### Known Limitations

- **Contract types**: Only NDAs currently supported
- **Language**: English only
- **Test set size**: Small (n=20), limiting statistical confidence
- **Ground truth**: Single reviewer, no inter-rater reliability
- **OCR**: Scanned documents not reliably processed
- **Implicit language**: May miss implicit liability or obligations

## Testing

Run the test suite:

```bash
cd examples/templates/contract_evaluator/tests
python run_tests.py --verbose
```

## Development

### Project Structure

```
contract_evaluator/
├── config.py                    # Configuration
├── agent.py                     # Main agent orchestration
├── __init__.py                  # Package exports
├── __main__.py                  # CLI entry point
├── nodes/                       # Analysis nodes
│   ├── document_ingestion.py
│   ├── classification.py
│   ├── confidentiality_analysis.py
│   ├── liability_analysis.py
│   ├── term_obligations.py
│   ├── synthesis.py
│   ├── human_review.py
│   └── report_generation.py
├── schemas/                     # Pydantic models
│   ├── contract_metadata.py
│   ├── clause_findings.py
│   └── risk_assessment.py
├── tests/                       # Test suite
│   ├── contracts/               # Test NDAs
│   ├── ground_truth.json        # Expected results
│   └── run_tests.py             # Test runner
└── docs/                        # Additional documentation
    ├── usage_examples.md
    ├── limitations.md
    └── validation_methodology.md
```

### Adding New Contract Types

To extend beyond NDAs:

1. Update `schemas/contract_metadata.py` with new `ContractType` enum
2. Add specialized analysis nodes for new contract type
3. Update graph edges in `agent.py`
4. Test and validate on sample contracts

## Roadmap

### v1.0 (Current)
- ✅ NDA analysis
- ✅ Risk scoring
- ✅ Human-in-the-loop
- ✅ Markdown/JSON reports

### v1.1 (Planned)
- [ ] Master Service Agreements (MSAs)
- [ ] Employment agreements
- [ ] Enhanced redlining capabilities

### v1.2 (Future)
- [ ] Multi-language support
- [ ] CLM system integrations
- [ ] Advanced analytics dashboard

## Contributing

See [CONTRIBUTING.md](../../../CONTRIBUTING.md) for guidelines.

## License

Apache 2.0 - See [LICENSE](../../../LICENSE)

## Support

- **Issues**: https://github.com/adenhq/hive/issues
- **Discord**: https://discord.com/invite/MXE49hrKDk
- **Documentation**: https://docs.adenhq.com

---

**Legal Disclaimer**: This tool is for informational purposes only and does not constitute legal advice. Always consult qualified legal counsel before making contractual decisions.
