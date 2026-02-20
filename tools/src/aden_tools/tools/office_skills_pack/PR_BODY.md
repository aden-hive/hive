## What
Adds a schema-first Office Skills Pack (local-only MVP):
- XLSX: multi-sheet writer + formatting + image embed (charts)
- PPTX: slide deck generator (title/bullets/images) + chart PNG embedding
- DOCX: report generator (sections/bullets/tables)
- PNG charts: render via matplotlib for artifact embedding

## Why
Fixes the "last-mile disconnect" where agents compute results but users manually copy into Excel/PowerPoint.

## How to run demo
From repo root:
python tools/examples/office_skills_pack_demo.py

## How to run tests
cd tools
python -m pytest -q

## Security
All inputs/outputs resolved using session sandbox via get_secure_path (no arbitrary FS writes).
No cloud APIs/OAuth in MVP.

## Why Pack Tool Exists
`office_pack_generate` gives orchestration agents a single deterministic interface to produce
charts + XLSX + PPTX + DOCX and return a normalized manifest, instead of coordinating many tool calls manually.

## Guardrails / Limits
- Slides <= 30
- Sheet rows <= 2000
- Chart points <= 5000

In strict mode, limits return `INVALID_SCHEMA`; in non-strict mode, outputs are truncated/skipped safely.

## How to review
1) Run one-call pack demo:
   python -m aden_tools.cli.office_pack --spec tools/examples/pack_finance.json
2) Run tests:
   cd tools && python -m pytest -q
3) Key files:
   - office_skills_pack/pack_tool.py (one-call orchestration + guardrails)
   - chart_tool/chart_tool.py (PNG charts)
   - excel_write_tool/excel_write_tool.py (xlsx + images)
4) Custom template dry-run:
   python -m aden_tools.cli.office_pack --spec tools/examples/pack_custom_template.json --dry-run --print-markdown

## Review map
- Core: `office_skills_pack/pack_tool.py`, `limits.py`, `contracts.py`
- Tools: `excel_write_tool`, `powerpoint_tool`, `word_tool`, `chart_tool`
- CLI: `aden_tools/cli/office_pack.py`
- Templates: `tools/examples/pack_*.json`
- Docs: `README.md`, `SCHEMAS.md`
- Tests: `tools/tests/examples/test_office_pack_*`, `golden` tests

## Suggested merge
Squash into:
1) feat: Office Skills Pack (schema-first XLSX/PPTX/DOCX + charts + pack tool + CLI)
2) chore: docs/tests/ci/dev tooling

Suggested PR title:
`feat(tools): schema-first Office Skills Pack (XLSX/PPTX/DOCX + charts + one-call pack + CLI)`
