# Office Skills Pack (MVP)

Adds local, schema-first generation of business artifacts:
- Excel: `.xlsx` (multi-sheet + basic formatting)
- PowerPoint: `.pptx` (title + bullets + optional images)
- Word: `.docx` (report sections + bullets + optional tables)

## Why this exists
Eliminates the last-mile disconnect: agents can compute insights and ship editable office artifacts locally.

## Design
- Schema-first: strict Pydantic models per tool
- Local-only MVP (no cloud OAuth)
- Secure output paths via session sandbox (`get_secure_path`)

## Demo
Run:
- `python tools/examples/office_skills_pack_demo.py`

Outputs:
- `out/weekly_report.xlsx`
- `out/weekly_report.pptx`
- `out/weekly_report.docx`
# Office Skills Pack (MVP)

Schema-first, local generation of business artifacts:

- Excel: `.xlsx` (multi-sheet + formatting via openpyxl)
- PowerPoint: `.pptx` (title + bullets + optional images via python-pptx)
- Word: `.docx` (sections + bullets + tables via python-docx)

## Install
From `tools/`:
```bash
python -m pip install -e ".[excel,powerpoint,word]"

## Contract
All tools return a standardized response:
- `success: bool`
- `output_path: str`
- `contract_version: "0.1.0"`
- `error: { code, message, details }`
- `metadata: {...}`

This makes it safe for agents/workflows to branch on stable error codes.
