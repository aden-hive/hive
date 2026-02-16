# Test Contracts

This directory should contain test NDA contracts in PDF format.

## Required for Testing

To run the test suite, add sample NDA contracts here:

```
contracts/
├── sample_mutual_nda.pdf
├── vendor_nda_onesided.pdf
├── tech_company_nda.pdf
└── ... (more test contracts)
```

## Sources for Test Contracts

You can find publicly available NDAs from:

1. **SEC EDGAR Database**: https://www.sec.gov/edgar/searchedgar/companysearch.html
   - Search for "NDA" or "Non-Disclosure Agreement"
   - Download as PDF

2. **Public Templates**:
   - https://www.lawdepot.com/contracts/non-disclosure-agreement/
   - https://www.rocketlawyer.com/business-and-contracts/intellectual-property/document/nda

3. **Open Source Projects**:
   - Many open source projects publish their NDAs on GitHub

## Anonymization

For privacy, please:
- Remove or redact party names (replace with "Company A" and "Company B")
- Remove signatures and contact information
- Remove any confidential business terms

## Ground Truth

After adding contracts, update `ground_truth.json` with expected results for each contract.

Example:
```json
{
  "contract_filename": {
    "contract_type": "Mutual NDA",
    "confidentiality_type": "mutual",
    "risk_score": 5.0,
    "duration_months": 24,
    "has_liability_cap": false,
    "description": "Brief description of the contract"
  }
}
```

## Running Tests

```bash
cd tests
python run_tests.py --verbose
```
