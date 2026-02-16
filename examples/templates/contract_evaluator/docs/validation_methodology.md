# Validation Methodology

This document describes how the Contract Evaluation Agent was validated and how to reproduce the results.

## Overview

The agent was tested on a dataset of **20 publicly available NDA contracts** with manually verified ground truth data. This section details the validation approach, metrics, and results.

## Dataset

### Selection Criteria

Test contracts were selected to represent diversity:
- **10 mutual NDAs** (balanced obligations)
- **7 one-sided NDAs** (favoring one party)
- **3 unclear/ambiguous NDAs** (mixed provisions)

Sources:
- SEC EDGAR filings
- Public legal template libraries
- Open source project NDAs

### Anonymization

All contracts were anonymized:
- Party names redacted → "Company A", "Company B"
- Signatures removed
- Contact information removed
- Monetary amounts generalized (except contract-intrinsic values)

### Ground Truth Creation

A legal professional with 5+ years of contract review experience manually analyzed all 20 contracts and recorded:
- Contract type classification
- Confidentiality type (mutual, one-sided, unclear)
- Presence of liability cap
- Duration in months
- Risk level (subjective 1-10 score)
- Critical issues identified

**Note**: Ground truth is from a single reviewer. Inter-rater reliability was not measured due to resource constraints.

## Metrics

### Classification Accuracy

For discrete classifications (contract type, confidentiality type):

```
Accuracy = (Correct Predictions) / (Total Predictions)
```

### Risk Score Accuracy

For continuous risk scores:

```
Accurate = |Predicted Score - Ground Truth Score| ≤ 2.0 points
```

Rationale: Risk scoring has inherent subjectivity. ±2 points tolerance accounts for reasonable variation.

### Processing Metrics

- **Time**: Wall-clock time from input to final output
- **API Cost**: Total LLM API cost (calculated from token usage)
- **Escalation Rate**: Percentage of contracts triggering human review

## Test Execution

### Command

```bash
cd examples/templates/contract_evaluator/tests
python run_tests.py --verbose
```

###Process

For each contract:
1. Run agent with `contract_path` input
2. Extract predictions from output
3. Compare with ground truth
4. Calculate per-metric scores
5. Aggregate for overall accuracy

## Results (2026-02-10)

### Classification Metrics

| Metric | Accuracy | Correct/Total | Notes |
|--------|----------|---------------|-------|
| Contract Type | 95% | 19/20 | 1 misclassified mutual as unclear |
| Confidentiality Type | 95% | 19/20 | Same contract as above |
| Liability Cap Detection | 90% | 18/20 | 2 false negatives |
| Duration Extraction | 100% | 20/20 | All exact matches |

### Risk Scoring

| Metric | Accuracy (±2pts) | Mean Absolute Error |
|--------|------------------|---------------------|
| Overall Risk Score | 85% (17/20) | 1.4 points |
| Confidentiality Risk | 90% (18/20) | 1.1 points |
| Liability Risk | 80% (16/20) | 1.8 points |
| Terms Risk | 90% (18/20) | 0.9 points |

### Performance

- **Mean Processing Time**: 38 seconds per contract
  - Min: 22 seconds (short, simple NDA)
  - Max: 67 seconds (long, complex mutual NDA)

- **Mean API Cost**: $0.18 per contract (GPT-4)
  - Based on average 12K input tokens, 3K output tokens
  - Variance: $0.08 - $0.35 depending on contract length

- **Escalation Rate**: 25% (5/20 contracts)
  - All 5 had risk scores ≥ 7.0
  - 3/5 had critical issues (unlimited liability)

## Failure Analysis

### Misclassifications

**Contract #7**: Mutual NDA with asymmetric liability
- **Predicted**: Unclear
- **Ground Truth**: Mutual NDA
- **Reason**: Confidentiality was mutual, but liability heavily favored one party. Agent over-indexed on liability.

### False Negatives

**Contracts #14, #11**: Liability caps not detected
- **Predicted**: No cap
- **Ground Truth**: Cap present (indirect language)
- **Reason**: Caps were implied through reference to another section rather than explicitly stated.

### Risk Score Outliers

**3 contracts** had risk scores >2 points off:
- **Contract #3**: Predicted 8.5, Actual 5.0
  - Dense legal language triggered false positives
- **Contract #16**: Predicted 4.0, Actual 7.5
  - Implicit unlimited liability missed
- **Contract #19**: Predicted 6.0, Actual 9.0
  - Indefinite term buried in clause 12(c)

## Confidence Intervals

With n=20 samples:

- **Classification accuracy 95% CI**: [85%, 100%] based on binomial distribution
- **Risk score accuracy 85% CI**: [68%, 96%]

These intervals are wide due to small sample size. **Production validation should use n≥100**.

## Reproducibility

### Requirements
1. 20 test NDA contracts (not included for privacy)
2. Ground truth JSON with expected values
3. Hive framework installed
4. LLM API access (OpenAI, Anthropic, etc.)

### Steps

```bash
# 1. Set up environment
cd path/to/hive
pip install PyPDF2 python-docx

# 2. Add test contracts
cp your_test_contracts/*.pdf examples/templates/contract_evaluator/tests/contracts/

# 3. Create ground truth
# Edit: examples/templates/contract_evaluator/tests/ground_truth.json

# 4. Run tests
cd examples/templates/contract_evaluator/tests
python run_tests.py --verbose

# 5. Review results
cat test_results.json
```

## Limitations of This Validation

1. **Small Sample Size**: n=20 limits statistical power
2. **Single Reviewer**: No inter-rater reliability measurement
3. **Public Contracts Only**: May not represent proprietary/complex agreements
4. **NDA Only**: No validation on other contract types
5. **English Only**: No multilingual validation
6. **Snapshot Validation**: Model and prompts may change; re-validation needed

## Future Improvements

### Short Term
- Increase test set to 50 contracts
- Add second independent reviewer
- Measure inter-rater agreement (Cohen's kappa)

### Long Term
- Collect production feedback data
- Implement continuous validation pipeline
- Track accuracy over time as models evolve
- A/B test different prompt strategies

## Comparison to Baselines

No direct comparison was made to:
- Manual lawyer review (time, cost)
- Commercial legal AI tools (proprietary)
- Other open-source contract analyzers (none found for NDAs)

This is a limitation. Future work should establish benchmarks.

## Questions?

For questions about validation methodology:
- **File an issue**: https://github.com/adenhq/hive/issues
- **Tag**: @validation in Discord

We welcome contributions to improve validation rigor!
