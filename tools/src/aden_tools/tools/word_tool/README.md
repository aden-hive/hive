# Word Tool (Schema-First)

Generates local `.docx` reports from a strict schema.

## Tool
- `word_generate(path, doc, workspace_id, agent_id, session_id)`

## Schema (MVP)
- DocSpec: { title: str, sections: [SectionSpec] }
- SectionSpec: { heading: str, paragraphs: [str], bullets: [str], table: Optional[TableSpec] }
- TableSpec: { columns: [str], rows: [[Any]] }

## Notes
- Paths are relative to the session sandbox.
- Uses `python-docx` optional dependency group: `word`.
