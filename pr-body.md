## PR Overview
This PR implements standardized issue templates for the fork to ensure high-quality contributions and mandatory validation evidence logs.

Fixes #45

## Root Cause
Official repository lacked structured issue templates, leading to vague bug reports and missing validation proof in the fork.

## Solution
- Added `.github/ISSUE_TEMPLATE/bug_report.md` with mandatory "Root Cause" and "Validation Evidence" sections.
- Added `.github/ISSUE_TEMPLATE/feature_request.md` with an "Alignment with Fork Direction" audit.

## Validation Results
- **Lint**: `ruff check` passed (SUCCESS).
- **Format**: 11 files standardized via `ruff format`.
- **Tests**: Targeted regression for OMEGA additions passed (25/25).
- **Templates**: Verified file presence and front-matter integrity.

## Evidence
- Logs: `.hive-ops/evidence/validation/ruff-final-audit-*.log`
- Logs: `.hive-ops/evidence/validation/pytest-additions-*.log`
- Report: `.hive-ops/reports/alignment-45-*.md`

## Risks + Mitigations
- **Risk**: Template friction. **Mitigation**: Kept fields descriptive but concise.
