# Policy-Aware Vendor Onboarding Agent (MVP)

This recipe demonstrates a production-style vendor onboarding workflow using Hive-style nodes and an auditable decision trail.

## What it does

- Ingests a vendor onboarding request from **structured JSON**
- Validates **required fields**
- Classifies vendor type (rule-based v1)
- Evaluates a **deterministic compliance checklist** (required documents)
- Computes a **risk score + reasons**
- Routes outcomes:
  - **needs_more_info** (missing fields/docs or medium risk)
  - **human_review** (high risk)
  - **approved** (low risk + compliant)
- Produces a final **structured recommendation** with an `audit_trail`

## Out of scope (v1)

- Third-party compliance APIs
- Email sending
- OCR/PDF extraction
- Web UI
- Multi-tenant auth

## Run

From repo root:

```bash
python3 -m examples.recipes.onboarding_assistance.vendor_onboarding_policy \
  --input examples/recipes/onboarding_assistance/vendor_onboarding_policy/input_examples/low_risk_vendor.json
