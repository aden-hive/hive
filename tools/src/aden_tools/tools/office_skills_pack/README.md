# Office Skills Pack (MVP)

Schema-first, local generation of business artifacts:

- Excel: `.xlsx` (multi-sheet + formatting via openpyxl)
- PowerPoint: `.pptx` (title + bullets + optional images via python-pptx)
- Word: `.docx` (sections + bullets + tables via python-docx)
- Charts: `.png` (matplotlib)

## Install
From `tools/`:

```bash
python -m pip install -e ".[excel,word,powerpoint,charts]"
```

## Dev setup
```bash
cd tools
pip install -e ".[dev,excel,word,powerpoint,charts]"
pre-commit run -a
python scripts/typecheck_office.py
```

## Contract
All tools return:

- `success: bool`
- `output_path: str | null`
- `contract_version: "0.1.0"`
- `error: { code, message, details } | null`
- `metadata: {...}`

## Error codes
- `INVALID_PATH`
- `INVALID_SCHEMA`
- `DEP_MISSING`
- `IO_ERROR`
- `UNKNOWN`

Example error payload:

```json
{
  "success": false,
  "output_path": null,
  "contract_version": "0.1.0",
  "error": {
    "code": "INVALID_SCHEMA",
    "message": "Invalid workbook schema",
    "details": "..."
  },
  "metadata": {}
}
```

## Charts
Generate PNG using `chart_render_png`, then embed into:

- PPTX via `powerpoint_generate` (`image_paths` / `charts`)
- XLSX via `excel_write` (`sheets[].images`)
- DOCX via `word_generate` (`sections[].image_paths` / `sections[].charts`)

## Demo
From repo root:

```bash
python tools/examples/office_skills_pack_demo.py
```

## Example payloads
See `tools/tests/fixtures/office_skills_pack/` for sample JSON inputs.

## Custom template
Start from:
- `tools/examples/pack_custom_template.json`

Dry-run:
```bash
python -m aden_tools.cli.office_pack --spec tools/examples/pack_custom_template.json --dry-run
```

## One-call generation
Use `office_pack_generate` to create charts + XLSX + PPTX + DOCX in one request.
It returns a manifest in `metadata.manifest`.

CLI example:

```bash
python -m aden_tools.cli.office_pack --spec tools/examples/pack_finance.json
```

CLI with markdown summary:

```bash
python -m aden_tools.cli.office_pack --spec tools/examples/pack_custom_template.json --dry-run --print-markdown
```

Installed entrypoint:

```bash
aden-office-pack --spec tools/examples/pack_custom_template.json --dry-run --print-markdown
```

Manifest example:

```json
{
  "metadata": {
    "manifest": [
      {"tool": "excel_write", "output_path": "out/pack_finance.xlsx", "metadata": {}},
      {"tool": "powerpoint_generate", "output_path": "out/pack_finance.pptx", "metadata": {}},
      {"tool": "word_generate", "output_path": "out/pack_finance.docx", "metadata": {}}
    ]
  }
}
```

## Limits (MVP)
Slides <= 30, sheet rows <= 2000, chart points <= 5000 (strict mode).

## Versioning
`contract_version` changes only on breaking schema/response changes.
