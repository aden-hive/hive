# Known Limitations

This document outlines the current limitations of the Contract Evaluation Agent.

## Scope Limitations

### Contract Types
- **Supported**: NDAs (Non-Disclosure Agreements) only
- **Not Supported**: 
  - Service agreements
  - Purchase orders
  - License agreements
  - Employment contracts
  - Lease agreements
  - Any other contract type

**Why**: The agent was designed and validated specifically for NDAs. Different contract types have fundamentally different structures and risk profiles.

### Language Support
- **Supported**: English only
- **Not Supported**: Any other language

**Why**: LLM prompts are tuned for English legal language. Legal terminology varies significantly across languages.

### Document Format
- **Fully Supported**: 
  - PDF with embedded text
  - DOCX (Microsoft Word)
  - Plain text

- **Partially Supported**:
  - Scanned PDF (requires OCR, unreliable)

- **Not Supported**:
  - Handwritten documents
  - Images
  - Encrypted PDFs

## Accuracy Limitations

### Test Set Size
- **Current**: 20 NDA contracts
- **Industry Standard**: 100+ contracts for production ML systems

**Impact**: Limited statistical confidence. Real-world accuracy may vary from reported metrics.

### Ground Truth
- **Current**: Single reviewer
- **Best Practice**: Multiple independent reviewers with inter-rater reliability measurement

**Impact**: Ground truth may contain subjective interpretations.

### Edge Cases

The agent struggles with:

1. **Implicit Obligations**: Clauses that imply duties without stating them explicitly
  
2. **Non-Standard Language**: Contracts using uncommon terminology or structure

3. **Amendments**: Documents that reference and modify other contracts

4. **Conditional Clauses**: Complex "if-then" provisions with multiple conditions

5. **Jurisdictional Nuances**: Subtle differences in legal interpretation across jurisdictions

## Technical Limitations

### Processing Speed
- **Average**:38 seconds per contract
- **Limiting Factor**: LLM API latency (multiple sequential calls)

**Mitigation**: Parallel analysis nodes help, but overall speed is bound by longest path.

### API Cost
- **Average**: $0.18 per contract (using GPT-4)
- **Variation**: Depends on contract length and complexity

**Note**: Costs may increase with longer contracts or if using more expensive models.

### Hallucination Risk
While mitigated by:
- Grounding in source text
- Structured output schemas
- Low temperature settings

There is still a **~5% risk** of the LLM generating information not present in the contract.

**Mitigation**: All high-risk contracts escalate to human review.

## Validation Limitations

### Compliance Checking
The agent does **NOT**:
- Guarantee compliance with any regulation
- Verify regulatory accuracy
- Replace compliance audits

**Why**: Compliance is contextual and requires domain-specific legal expertise.

### Legal Advice
The agent does **NOT**:
- Constitute legal advice
- Replace qualified attorneys
- Make binding legal determinations

**Why**: Legal interpretation requires human judgment and understanding of specific business context.

## Operational Limitations

### Human-in-the-Loop
- **Requires**: Human availability for high-risk contracts
- **Timeout**: Configurable, but defaults to 1 hour

**Impact**: Pipeline may pause waiting for human input.

### State Management
- **Current**: Stateless (each contract analyzed independently)
- **Missing**: 
  - Learning from corrections
  - Tracking changes across contract versions
  - Organizational policy customization

### Multi-Document Analysis
- **Not Supported**: Analyzing multiple related contracts together
- **Example**: Parent contract + amendments

## Reporting Limitations

### Redlining
- **Current**: Text recommendations only
- **Missing**: Actual redlined document generation

### Negotiation Guidance
- **Current**: Generic recommendations
- **Missing**: 
  - Industry-specific benchmarks
  - Negotiation priority ranking
  - Historical outcome data

## Security & Privacy

### Data Handling
- **Current**: Contract text sent to external LLM providers
- **Risk**: Sensitive information transmitted to third parties

**Mitigation**: 
- Use self-hosted LLMs (if available in Hive)
- Redact sensitive information before analysis
- Review provider's data retention policies

### Audit Trail
- **Current**: Basic execution logging
- **Missing**:
  - Detailed audit logs
  - Version control for analysis
  - Compliance reporting

## Roadmap

Many of these limitations are planned for future versions. See [README.md](../README.md#roadmap) for details.

## Questions?

If you encounter limitations not listed here, please:
- **File an issue**: https://github.com/adenhq/hive/issues
- **Discussion**: https://discord.com/invite/MXE49hrKDk
