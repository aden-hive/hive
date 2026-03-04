# Universal Document Intake & Action Agent

> The intelligent front door for any business — accepts any document, extracts structured data, classifies, validates, and routes.

## Problem

80% of business information is locked in emails, PDFs, images, and documents. Every company — from 3-person startups to Fortune 500 — manually processes invoices, contracts, receipts, and forms. This agent automates that universal pain point.

## Architecture

```
┌─────────────────────────┐
│  process (autonomous)    │
│  in:  file_path         │
│  tools: save_data,      │
│         load_data       │
│  • Document reception   │
│  • Content extraction   │
│  • Classification       │
│  • Field extraction     │
└────────────┬────────────┘
             │ on_success
             ▼
┌─────────────────────────┐
│  review (client-facing)  │
│  tools: load_data       │
│  • Validation           │
│  • Routing decision     │
│  • Result presentation  │
└────────────┬────────────┘
             │ on_success
             └──────► back to process
```

## Supported Documents

| Category | Auto-Process | Example |
|---|---|---|
| Invoice | ✅ | Vendor bills, payment requests |
| Receipt | ✅ | Purchase receipts, payment confirmations |
| Expense Report | ✅ | Employee expense claims |
| Contract | ❌ (Human Review) | Legal agreements |
| Bank Statement | ✅ | Monthly account statements |
| Tax Form | ❌ (Human Review) | W-9, 1099, etc. |
| Purchase Order | ✅ | Vendor orders |
| Compliance Doc | ❌ (Human Review) | Regulatory documents |

## Hive Features Used

- **Node graph execution** — 2-node processing pipeline
- **LLM integration** — Classification and extraction via LiteLLM
- **Pydantic validation** — Structured outputs on all LLM calls
- **Human-in-the-loop** — Client-facing review node for low-confidence results
- **Event loop nodes** — Continuous processing with real-time streaming
- **Forever-alive agent** — Processes documents continuously
- **Confidence-based routing** — Auto-process high confidence, human review for complex cases

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/adenhq/hive.git
cd hive

# Set up the environment
./quickstart.sh

# Set your API key
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Basic Usage

```bash
# Validate the agent
PYTHONPATH=exports:core .venv/bin/python -m document_intake_agent validate

# Get agent info
PYTHONPATH=exports:core .venv/bin/python -m document_intake_agent info

# Run tests
PYTHONPATH=exports:core .venv/bin/python -m document_intake_agent test

# Process a document
PYTHONPATH=exports:core .venv/bin/python -m document_intake_agent process \
  --file-path exports/document_intake_agent/sample_docs/invoice_sample.txt
```

### Using with Hive Framework

```python
from document_intake_agent import default_agent

# Validate configuration
assert default_agent.validate()

# The agent is ready to be loaded into Hive runtime
```

## Example Output

```json
{
  "document_id": "doc_a1b2c3d4e5f6",
  "format_detected": "text",
  "classification": {
    "category": "invoice",
    "confidence": 0.95,
    "confidence_level": "high",
    "reasoning": "Contains vendor information, invoice number, line items, and total amount"
  },
  "extraction": {
    "entities": [
      {"field_name": "vendor_name", "value": "Acme Software Solutions", "confidence": 0.98},
      {"field_name": "invoice_number", "value": "INV-2024-0123", "confidence": 0.99},
      {"field_name": "total_amount", "value": "$8,029.00", "confidence": 0.97},
      {"field_name": "due_date", "value": "March 31, 2024", "confidence": 0.94}
    ],
    "processing_time_ms": 1250
  },
  "validation": {
    "is_valid": true,
    "completeness_score": 1.0,
    "warnings": []
  },
  "routing": {
    "action": "auto_process",
    "destination": "accounts_payable",
    "priority": "normal",
    "requires_human": false
  }
}
```

## Configuration

The agent behavior can be customized via `config.py`:

```python
# Confidence thresholds
HIGH_CONFIDENCE_THRESHOLD = 0.85  # Auto-process above this
MEDIUM_CONFIDENCE_THRESHOLD = 0.60  # Flag for review

# Auto-routing rules
AUTO_PROCESS_CATEGORIES = ["invoice", "receipt", "expense_report"]
HUMAN_REVIEW_CATEGORIES = ["contract", "compliance_doc", "tax_form"]

# Required fields per category
REQUIRED_FIELDS = {
    "invoice": ["vendor_name", "invoice_number", "total_amount", "due_date"],
    "receipt": ["merchant_name", "total_amount", "date"],
    # ... more categories
}
```

## Testing

The agent includes comprehensive test coverage:

```bash
# Run all tests
PYTHONPATH=exports:core .venv/bin/python -m document_intake_agent test

# Test with sample documents
ls exports/document_intake_agent/sample_docs/
# invoice_sample.txt
# receipt_sample.txt
# contract_sample.txt
# bank_statement_sample.csv
```

## Architecture Details

### Node Flow

1. **Process Node (Autonomous)**:
   - Receives file path and metadata
   - Validates document exists and detects format
   - Extracts content using appropriate method (OCR, text parsing)
   - Classifies document type using LLM
   - Extracts structured fields based on classification
   - Saves all intermediate results for review

2. **Review Node (Client-Facing)**:
   - Validates extracted data completeness and formats
   - Makes routing decision based on confidence and category
   - Presents complete results to user
   - Determines next action (continue processing or done)

### Confidence-Based Automation

- **High Confidence (≥85%)**: Auto-process if category supports it
- **Medium Confidence (60-85%)**: Proceed with warning flag
- **Low Confidence (<60%)**: Route to human review

### Supported Formats

- **PDF**: Text extraction + OCR fallback for scanned documents
- **Images**: OCR with preprocessing (PNG, JPG, TIFF)
- **CSV**: Structured data parsing
- **Text**: Direct content reading
- **DOCX**: Document text extraction (future)
- **Email**: EML format parsing (future)

## Contributing

This agent demonstrates production-grade Hive agent development patterns:

1. **Pydantic schemas** for type safety
2. **Node graph design** with clear separation of concerns
3. **LLM prompt engineering** for reliable structured outputs
4. **Confidence-based routing** for quality control
5. **Client-facing interactions** for human oversight
6. **Comprehensive validation** and error handling

To extend the agent:
- Add new document categories in `schemas.py` and `config.py`
- Implement additional extraction methods in `tools.py`
- Enhance validation rules for specific document types
- Add more sophisticated routing logic

## Version History

- **v0.1.0**: Initial implementation with core document processing pipeline